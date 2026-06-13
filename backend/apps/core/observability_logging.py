"""
OTel Trace Log Filter
=====================
Injects ``otel_trace_id`` and ``otel_span_id`` into every log record so that
structured JSON log lines can be correlated with distributed traces.

Degrades gracefully to ``"-"`` when:
- OpenTelemetry is not installed (lazy import fails)
- OTel is disabled / no span is active (span context is not valid)
- Any unexpected error occurs

Never raises. Always returns True (never suppresses log records).
"""

from __future__ import annotations

import logging


class OTelTraceLogFilter(logging.Filter):
    """
    Injects ``otel_trace_id`` and ``otel_span_id`` into every log record.

    Reads the current active OpenTelemetry span context via a lazy import so
    that the filter works correctly even when OTel is disabled or not installed.
    Falls back to ``"-"`` in all failure/absent-span cases.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            from opentelemetry import trace  # lazy import — no-op when OTel absent

            span = trace.get_current_span()
            ctx = span.get_span_context()
            if ctx.is_valid:
                record.otel_trace_id = format(ctx.trace_id, "032x")
                record.otel_span_id = format(ctx.span_id, "016x")
            else:
                record.otel_trace_id = "-"
                record.otel_span_id = "-"
        except Exception:
            record.otel_trace_id = "-"
            record.otel_span_id = "-"
        return True
