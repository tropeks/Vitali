"""
Shared constants for the core app.
Import from here — don't redefine inline in views, serializers, or elsewhere.
"""

ALLOWED_MODULE_KEYS: frozenset = frozenset(
    {
        "emr",
        "billing",
        "pharmacy",
        "ai_tuss",
        "whatsapp",
        "analytics",
        "rh",
    }
)
