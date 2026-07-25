"""Sprint C4 — serializers for the P&L surface.

The P&L payload is a computed roll-up (Decimals + a per-service list), returned
as-is by the view. Here we only validate the read query params (period + an
optional single unit) so the endpoint parses ``?start=&end=&unit=`` safely.
"""

from rest_framework import serializers


class PnlQuerySerializer(serializers.Serializer):
    """Validate the P&L read query params."""

    start = serializers.DateField(required=False, allow_null=True)
    end = serializers.DateField(required=False, allow_null=True)
    unit = serializers.UUIDField(required=False, allow_null=True)
