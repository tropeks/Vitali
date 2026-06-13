"""
Vitali — OpenTelemetry observability bootstrap.

Design invariant (OTEL default OFF):
- When OTEL_ENABLED=False (the default) this module is a pure no-op.
- ALL opentelemetry imports live INSIDE setup_observability(), after the gate.
  With OTEL_ENABLED=False the interpreter never imports any opentelemetry module,
  so the 474-test suite stays green without the OTel packages installed.
- With OTEL_ENABLED=True the packages must be present (production image layer).

Entry points:
  vitali/wsgi.py          → setup_observability("web")
  vitali/celery.py        → setup_observability("worker")  [via worker_process_init]
"""

from __future__ import annotations

_INSTRUMENTED: bool = False


def setup_observability(service_role: str) -> None:
    """
    Bootstrap OpenTelemetry for the current process.

    Parameters
    ----------
    service_role : str
        Either "web" (WSGI/gunicorn) or "worker" (Celery).

    The function is idempotent: subsequent calls are no-ops.
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
    from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
    from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
    from opentelemetry.sdk.trace.export import (  # noqa: PLC0415
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )
    from opentelemetry.propagators.composite import CompositePropagator  # noqa: PLC0415
    from opentelemetry.propagate import set_global_textmap  # noqa: PLC0415
    from opentelemetry.trace.propagation.tracecontext import (  # noqa: PLC0415
        TraceContextTextMapPropagator,
    )
    from opentelemetry.baggage.propagation import W3CBaggagePropagator  # noqa: PLC0415

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
        exporter = ConsoleSpanExporter()

    provider = TracerProvider(resource=resource)
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

        DjangoInstrumentor().instrument()
        Psycopg2Instrumentor().instrument()
        RequestsInstrumentor().instrument()

    elif service_role == "worker":
        from opentelemetry.instrumentation.celery import CeleryInstrumentor  # noqa: PLC0415
        from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor  # noqa: PLC0415
        from opentelemetry.instrumentation.requests import RequestsInstrumentor  # noqa: PLC0415

        CeleryInstrumentor().instrument()
        Psycopg2Instrumentor().instrument()
        RequestsInstrumentor().instrument()

    _INSTRUMENTED = True
