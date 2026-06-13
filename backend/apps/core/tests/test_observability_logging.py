"""
Tests for apps/core/observability_logging.py — P2-02.

Doctrine:
- Default-dash tests run unconditionally (no OTel dependency) — guarantees the
  test suite stays green even when OTel is OFF / not installed.
- Active-span test uses pytest.importorskip("opentelemetry") so it is skipped
  automatically when the SDK is absent, and runs when libs are present (P2-01
  already installed them in the image).
"""

from __future__ import annotations

import logging

import pytest
from django.test import TestCase

from apps.core.observability_logging import OTelTraceLogFilter


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_record() -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test message",
        args=(),
        exc_info=None,
    )


# ===========================================================================
# P2-02 — Default / degraded path (always runs — OTel OFF or not installed)
# ===========================================================================


class OTelTraceLogFilterDefaultTests(TestCase):
    """Filter must degrade gracefully when no span is active."""

    def test_filter_defaults_to_dash_when_no_span(self):
        """
        Without an active span the filter must set otel_trace_id='-' and
        otel_span_id='-', and must return True.
        """
        record = _make_record()
        result = OTelTraceLogFilter().filter(record)

        self.assertTrue(result)
        self.assertEqual(record.otel_trace_id, "-")
        self.assertEqual(record.otel_span_id, "-")

    def test_filter_never_raises(self):
        """
        The filter must never raise an exception regardless of the environment
        — return value must be True even under adverse conditions.
        """
        record = _make_record()
        try:
            result = OTelTraceLogFilter().filter(record)
        except Exception as exc:  # pragma: no cover
            self.fail(f"OTelTraceLogFilter.filter() raised unexpectedly: {exc!r}")
        self.assertTrue(result)

    def test_filter_always_returns_true(self):
        """Filter must never suppress log records (always return True)."""
        record = _make_record()
        self.assertIs(OTelTraceLogFilter().filter(record), True)


# ===========================================================================
# P2-02 — Active span path (skipped when OTel SDK not installed)
# ===========================================================================


@pytest.mark.django_db
class OTelTraceLogFilterActiveSpanTests(TestCase):
    """Filter must inject real trace/span IDs when a span is active."""

    @classmethod
    def setUpClass(cls):
        # Skip the entire class if the OTel SDK is not installed.
        try:
            import opentelemetry  # noqa: F401
        except ImportError:
            import unittest

            raise unittest.SkipTest(
                "opentelemetry SDK not installed — active-span OTel log filter "
                "tests skipped. Rebuild the image to run these."
            )
        super().setUpClass()

    def test_filter_populates_from_active_span(self):
        """
        Inside an active span context the filter must inject hex-encoded
        trace_id (32 chars) and span_id (16 chars) that match the span context.
        """
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        # Set a fresh provider so this test is isolated.
        original_provider = trace.get_tracer_provider()
        trace.set_tracer_provider(provider)
        try:
            tracer = trace.get_tracer("vitali.test.log_filter")
            with tracer.start_as_current_span("test-log-span") as span:
                span_ctx = span.get_span_context()
                record = _make_record()
                result = OTelTraceLogFilter().filter(record)

            # Filter must return True
            self.assertTrue(result)

            # IDs must be properly formatted hex strings
            self.assertEqual(len(record.otel_trace_id), 32)
            self.assertEqual(len(record.otel_span_id), 16)

            # IDs must match the span context
            expected_trace_id = format(span_ctx.trace_id, "032x")
            expected_span_id = format(span_ctx.span_id, "016x")
            self.assertEqual(record.otel_trace_id, expected_trace_id)
            self.assertEqual(record.otel_span_id, expected_span_id)

            # IDs must be non-trivial (not all-zeros)
            self.assertNotEqual(record.otel_trace_id, "0" * 32)
            self.assertNotEqual(record.otel_span_id, "0" * 16)
        finally:
            # Restore original provider so subsequent tests are not polluted.
            trace.set_tracer_provider(original_provider)
