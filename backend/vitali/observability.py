"""
Vitali — OpenTelemetry observability bootstrap.

Design invariant (OTEL default OFF):
- When OTEL_ENABLED=False (the default) this module is a pure no-op.
- ALL opentelemetry imports live INSIDE setup_observability(), after the gate.
  With OTEL_ENABLED=False the interpreter never imports any opentelemetry module,
  so the 474-test suite stays green without the OTel packages installed.
- With OTEL_ENABLED=True the packages must be present (production image layer).

Security hardening (P2):
- PHIScrubbingSpanProcessor: always added when OTel is enabled. Redacts
  db.statement (raw SQL may contain PII/PHI) and strips query strings from
  http.target / http.url / url.full (URLs may carry patient identifiers).
  Exposed as a callable at module level (PHIScrubbingSpanProcessor()) so tests
  can instantiate it directly.  The actual SpanProcessor subclass is built
  lazily inside the factory to preserve the no-import invariant.
- ConsoleExporter blocked in production: if OTEL_ENABLED=True and no OTLP
  endpoint is configured and DEBUG=False, the bootstrap raises
  ImproperlyConfigured rather than leaking spans to stdout.

Entry points:
  vitali/wsgi.py          → setup_observability("web")
  vitali/celery.py        → setup_observability("worker")  [via worker_process_init]
"""

from __future__ import annotations

_INSTRUMENTED: bool = False


# ---------------------------------------------------------------------------
# PHI Scrubbing Span Processor (lazy factory)
# ---------------------------------------------------------------------------


def PHIScrubbingSpanProcessor():  # noqa: N802 — intentional CamelCase factory
    """
    Factory that builds and returns a SpanProcessor that redacts PHI/PII
    from span attributes before they reach any exporter.

    Named with CamelCase so callers can treat it as a class (``PHIScrubbingSpanProcessor()``).
    The actual subclass is constructed lazily to keep the opentelemetry SDK import
    inside this function — preserving the module-level no-import invariant when
    OTEL_ENABLED=False.

    Redactions applied in ``on_end`` (before export):
    - ``db.statement``: removed entirely — raw SQL may carry patient data
      (CPF, name, DOB, etc.) interpolated by the ORM or the psycopg2 driver.
    - ``http.target``, ``http.url``, ``url.full``: query string stripped —
      query parameters frequently carry patient identifiers (e.g. ``?cpf=…``).
    - ``http.request.header.*``: any request-header attribute removed —
      headers may carry auth tokens or correlation IDs tied to patients.
    """
    from opentelemetry.sdk.trace import SpanProcessor  # noqa: PLC0415

    class _PHIScrubbingSpanProcessor(SpanProcessor):
        # Attributes to remove completely.
        _REMOVE = frozenset({"db.statement"})

        # Attributes whose query string must be stripped (keep path only).
        _STRIP_QS = frozenset({"http.target", "http.url", "url.full"})

        # Prefix for request headers (all removed).
        _HEADER_PREFIX = "http.request.header."

        @staticmethod
        def _strip_query_string(value: str) -> str:
            """Return *value* with the query string (and fragment) removed."""
            qs_start = value.find("?")
            if qs_start == -1:
                frag_start = value.find("#")
                return value[:frag_start] if frag_start != -1 else value
            return value[:qs_start]

        def on_end(self, span) -> None:
            """Redact PHI attributes from the finished span before export."""
            # span._attributes is a BoundedAttributes mapping that supports pop/update.
            attrs = getattr(span, "_attributes", None)
            if attrs is None:
                return

            keys_to_delete = []
            keys_to_update = {}

            for key, value in list(attrs.items()):
                if key in self._REMOVE:
                    keys_to_delete.append(key)
                elif key in self._STRIP_QS and isinstance(value, str):
                    stripped = self._strip_query_string(value)
                    if stripped != value:
                        keys_to_update[key] = stripped
                elif key.startswith(self._HEADER_PREFIX):
                    keys_to_delete.append(key)

            for key in keys_to_delete:
                attrs.pop(key, None)
            for key, value in keys_to_update.items():
                attrs[key] = value

    return _PHIScrubbingSpanProcessor()


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def setup_observability(service_role: str) -> None:
    """
    Bootstrap OpenTelemetry for the current process.

    Parameters
    ----------
    service_role : str
        Either "web" (WSGI/gunicorn) or "worker" (Celery).

    The function is idempotent: subsequent calls are no-ops.

    Raises
    ------
    django.core.exceptions.ImproperlyConfigured
        When OTEL_ENABLED=True, no OTLP endpoint is configured, and DEBUG=False.
        The ConsoleSpanExporter must not run in production because span data may
        contain PHI that would then flow to stdout / container log aggregators.
    """
    # ── Gate: default OFF ─────────────────────────────────────────────────────
    from django.conf import settings  # noqa: PLC0415

    if not getattr(settings, "OTEL_ENABLED", False):
        return

    global _INSTRUMENTED  # noqa: PLW0603
    if _INSTRUMENTED:
        return

    # ── Lazy imports (only reached when OTEL_ENABLED=True) ───────────────────
    from opentelemetry import trace  # noqa: PLC0415
    from opentelemetry.baggage.propagation import W3CBaggagePropagator  # noqa: PLC0415
    from opentelemetry.propagate import set_global_textmap  # noqa: PLC0415
    from opentelemetry.propagators.composite import CompositePropagator  # noqa: PLC0415
    from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
    from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
    from opentelemetry.sdk.trace.export import (  # noqa: PLC0415
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )
    from opentelemetry.trace.propagation.tracecontext import (  # noqa: PLC0415
        TraceContextTextMapPropagator,
    )

    # ── Provider & exporter ───────────────────────────────────────────────────
    service_name = getattr(settings, "OTEL_SERVICE_NAME", "vitali-backend")
    resource = Resource({"service.name": service_name})

    endpoint = getattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # noqa: PLC0415
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=endpoint)
    else:
        # ── P2 Hardening: ConsoleExporter blocked in production ───────────────
        # If no OTLP endpoint is set and we are NOT in debug/dev mode, fail
        # fast rather than silently leaking span data to stdout.  Container
        # logs are often collected by log-aggregators, and PHI must not flow
        # through an unintended channel.
        debug = getattr(settings, "DEBUG", False)
        if not debug:
            from django.core.exceptions import ImproperlyConfigured  # noqa: PLC0415

            raise ImproperlyConfigured(
                "OTEL_ENABLED=True but OTEL_EXPORTER_OTLP_ENDPOINT is not set "
                "and DEBUG=False. The ConsoleSpanExporter must not run in "
                "production because span data may contain PHI. "
                "Either set OTEL_EXPORTER_OTLP_ENDPOINT to an OTLP collector "
                "endpoint or set OTEL_ENABLED=False."
            )
        exporter = ConsoleSpanExporter()

    provider = TracerProvider(resource=resource)

    # ── P2 Hardening: PHI scrubbing processor (always first in pipeline) ─────
    # The scrubber must be added before the exporting processor so that no
    # PHI reaches any backend (OTLP collector or console).
    provider.add_span_processor(PHIScrubbingSpanProcessor())
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # ── Propagators (W3C TraceContext + W3C Baggage) ─────────────────────────
    set_global_textmap(
        CompositePropagator(
            [
                TraceContextTextMapPropagator(),
                W3CBaggagePropagator(),
            ]
        )
    )

    # ── Instrumentation by role ───────────────────────────────────────────────
    if service_role == "web":
        from opentelemetry.instrumentation.django import DjangoInstrumentor  # noqa: PLC0415
        from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor  # noqa: PLC0415
        from opentelemetry.instrumentation.requests import RequestsInstrumentor  # noqa: PLC0415

        # enable_commenter=False: avoid injecting OTel metadata into SQL comments
        # which could expose trace context in DB logs and slow log aggregators.
        DjangoInstrumentor().instrument()
        Psycopg2Instrumentor().instrument(enable_commenter=False)
        RequestsInstrumentor().instrument()

    elif service_role == "worker":
        from opentelemetry.instrumentation.celery import CeleryInstrumentor  # noqa: PLC0415
        from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor  # noqa: PLC0415
        from opentelemetry.instrumentation.requests import RequestsInstrumentor  # noqa: PLC0415

        CeleryInstrumentor().instrument()
        Psycopg2Instrumentor().instrument(enable_commenter=False)
        RequestsInstrumentor().instrument()

    _INSTRUMENTED = True
