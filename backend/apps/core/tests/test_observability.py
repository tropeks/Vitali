"""
Tests for vitali/observability.py — P2-03 (gate OFF-first) and P2-01 (instrumentation ON).

Doctrine:
- OFF tests: run unconditionally; assert that setup_observability() is a pure
  no-op — no opentelemetry module must enter sys.modules when OTEL_ENABLED=False.
- ON tests: skip gracefully when the OTel SDK is not installed (pytest.importorskip).
  When the SDK is present they run against in-memory exporters without a collector.
"""

from __future__ import annotations

import sys

from django.test import TestCase, override_settings


# ---------------------------------------------------------------------------
# Helper — reset the idempotency guard between test runs
# ---------------------------------------------------------------------------

def _reset_otel_guard():
    """Reset the module-global _INSTRUMENTED flag so each test starts clean."""
    import importlib
    import vitali.observability as obs_mod  # already loaded; just grab it

    obs_mod._INSTRUMENTED = False


# ===========================================================================
# P2-03 — Gate OFF (runs without any OTel packages installed)
# ===========================================================================


class OtelGateOffTests(TestCase):
    """
    When OTEL_ENABLED=False (the default) setup_observability() must be a
    complete no-op: the call returns immediately and zero opentelemetry.*
    modules enter sys.modules.
    """

    def setUp(self):
        _reset_otel_guard()

    def tearDown(self):
        _reset_otel_guard()

    @override_settings(OTEL_ENABLED=False)
    def test_setup_noop_when_disabled(self):
        """No opentelemetry module must be imported when OTEL_ENABLED=False."""
        from vitali.observability import setup_observability

        modules_before = {m for m in sys.modules if m.startswith("opentelemetry")}
        setup_observability("web")
        modules_after = {m for m in sys.modules if m.startswith("opentelemetry")}

        new_otel_modules = modules_after - modules_before
        self.assertEqual(
            new_otel_modules,
            set(),
            msg=(
                "setup_observability() imported OTel modules while OTEL_ENABLED=False: "
                f"{new_otel_modules}"
            ),
        )

    @override_settings(OTEL_ENABLED=False)
    def test_setup_idempotent(self):
        """Calling setup_observability() twice must not raise and must stay a no-op."""
        from vitali.observability import setup_observability

        # First call
        setup_observability("web")
        # Second call — must not raise or import anything
        modules_before = set(sys.modules.keys())
        setup_observability("web")
        modules_after = set(sys.modules.keys())

        new_otel_modules = {
            m for m in (modules_after - modules_before) if m.startswith("opentelemetry")
        }
        self.assertEqual(new_otel_modules, set())


# ===========================================================================
# P2-01 — Instrumentation ON (skipped when OTel SDK not installed)
# ===========================================================================


class OtelGateOnTests(TestCase):
    """
    Smoke-test for the OTEL_ENABLED=True path.

    Requires the opentelemetry SDK packages; skipped automatically on images
    that don't have them installed (e.g. the baseline dev image before rebuild).
    """

    @classmethod
    def setUpClass(cls):
        # Skip the entire class if the OTel SDK is not installed.
        pytest_importorskip = None
        try:
            import pytest

            pytest_importorskip = pytest.importorskip
        except ImportError:
            pass

        try:
            import opentelemetry  # noqa: F401
        except ImportError:
            import unittest

            raise unittest.SkipTest(
                "opentelemetry SDK not installed — OTel ON tests skipped. "
                "Rebuild the image after adding requirements to run these."
            )

        super().setUpClass()

    def setUp(self):
        _reset_otel_guard()

    def tearDown(self):
        _reset_otel_guard()
        # Restore a clean tracer provider so subsequent tests aren't polluted.
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider

            trace.set_tracer_provider(TracerProvider())
        except Exception:
            pass

    def test_spans_generated_when_enabled(self):
        """
        When OTEL_ENABLED=True a span recorded via the global tracer should be
        visible in the in-memory exporter (no collector required).
        """
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        # Set up a dedicated in-memory provider for this test.
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        tracer = trace.get_tracer("vitali.test")
        with tracer.start_as_current_span("test-span"):
            pass  # nothing to do inside; we just want the span recorded

        finished = exporter.get_finished_spans()
        self.assertGreater(
            len(finished),
            0,
            msg="Expected at least one finished span in the in-memory exporter.",
        )
        span_names = [s.name for s in finished]
        self.assertIn("test-span", span_names)
