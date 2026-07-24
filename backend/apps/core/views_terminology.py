"""
E1-T4 — Terminology autocomplete API (read-only).

GET /api/v1/terminology/<system>/?q=<query>&limit=<n>

Authenticated read of the SHARED terminology catalogs (CID-10 today). No write
verbs. Unknown system → 404. The heavy lifting lives in ``apps.core.terminology``.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.terminology import DEFAULT_LIMIT, UnknownTerminologySystem, search


class TerminologySearchView(APIView):
    """Read-only ranked autocomplete over a terminology system."""

    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "head", "options"]

    def get(self, request, system: str):
        q = request.query_params.get("q", "")
        limit = request.query_params.get("limit", DEFAULT_LIMIT)
        try:
            results = search(system, q, limit)
        except UnknownTerminologySystem:
            return Response(
                {"detail": f"Unknown terminology system: {system!r}."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "system": system,
                "query": q,
                "count": len(results),
                "results": results,
            }
        )
