"""
Custom DRF throttle for MFA verification endpoints.
Rate: 3 attempts per 5 minutes (300 seconds) per user.

This prevents brute-force attacks against TOTP codes.
Fail-closed: if the throttle check errors, the request is blocked.
"""
from rest_framework.throttling import UserRateThrottle


class MFAVerifyThrottle(UserRateThrottle):
    """
    3 verification attempts per 5-minute window per authenticated user.
    Cache key: mfa_verify:{user.id}
    """

    scope = "mfa_verify"
    rate = "3/300s"

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": str(request.user.id),
        }

    def parse_rate(self, rate):
        """
        Override to handle '3/300s' format (non-standard period).
        Returns (num_requests, duration_seconds).
        """
        if rate is None:
            return (None, None)
        num, period = rate.split("/")
        num_requests = int(num)
        # Support numeric seconds directly: '300s'
        if period.endswith("s"):
            duration = int(period[:-1])
        else:
            duration = super().parse_rate(rate)[1]
        return (num_requests, duration)
