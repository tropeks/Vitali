"""
FHIR R4 ``searchset`` Bundle assembly with paging.

Every FHIR search interaction returns a Bundle (``type=searchset``). This module
centralises three concerns that were previously copy-pasted across every search
view:

- ``_count`` / ``_offset`` parsing (FHIR's standard page-size and page-offset
  search-result parameters), with safe clamping.
- ``Bundle.link`` assembly — the FHIR-native paging mechanism. Per FHIR R4
  §3.1.1.4 a searchset SHOULD carry ``self`` plus, when more pages exist,
  ``first`` / ``previous`` / ``next`` / ``last`` relation links so a compliant
  client can walk the result set without constructing URLs itself.
- An RFC 5988 ``Link`` HTTP response header mirroring those relations, which some
  HTTP-level clients consume instead of reading ``Bundle.link``.

Paging is offset-based (``_offset``). FHIR does not mandate a cursor scheme; an
opaque offset keeps the URLs self-describing and stable for these read-only,
modestly-sized interop result sets.
"""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

DEFAULT_COUNT = 20
MAX_COUNT = 100


def parse_count(request: Request, *, default: int = DEFAULT_COUNT, maximum: int = MAX_COUNT) -> int:
    """Parse and clamp the FHIR ``_count`` (page size) search parameter."""
    try:
        count = int(request.query_params.get("_count", default))
    except (TypeError, ValueError):
        return default
    if count < 1:
        return default
    return min(count, maximum)


def parse_offset(request: Request) -> int:
    """Parse the FHIR ``_offset`` (page start) search parameter; never negative."""
    try:
        offset = int(request.query_params.get("_offset", 0))
    except (TypeError, ValueError):
        return 0
    return max(offset, 0)


def _page_url(request: Request, *, count: int, offset: int) -> str:
    """Absolute URL for this search with ``_count``/``_offset`` overridden."""
    params = request.query_params.copy()
    params["_count"] = str(count)
    params["_offset"] = str(offset)
    return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")


def build_links(request: Request, *, total: int, count: int, offset: int) -> list[dict[str, str]]:
    """Build the ``Bundle.link`` relation array (self/first/previous/next/last)."""
    links: list[dict[str, str]] = [
        {"relation": "self", "url": _page_url(request, count=count, offset=offset)}
    ]
    if total <= 0 or count <= 0:
        return links

    last_offset = ((total - 1) // count) * count
    links.append({"relation": "first", "url": _page_url(request, count=count, offset=0)})
    if offset > 0:
        prev_offset = max(offset - count, 0)
        links.append(
            {"relation": "previous", "url": _page_url(request, count=count, offset=prev_offset)}
        )
    if offset + count < total:
        links.append(
            {"relation": "next", "url": _page_url(request, count=count, offset=offset + count)}
        )
    links.append({"relation": "last", "url": _page_url(request, count=count, offset=last_offset)})
    return links


def _link_header(links: list[dict[str, str]]) -> str:
    """Render ``Bundle.link`` relations as an RFC 5988 ``Link`` header value."""
    return ", ".join(f'<{link["url"]}>; rel="{link["relation"]}"' for link in links)


def searchset_response(
    request: Request,
    *,
    entries: list[dict[str, Any]],
    total: int,
    count: int,
    offset: int,
) -> Response:
    """Wrap ``entries`` in a paged FHIR ``searchset`` Bundle Response.

    ``entries`` must already be the current page (caller slices the result set);
    ``total`` is the full match count across all pages. Emits ``Bundle.link`` and
    a mirrored RFC 5988 ``Link`` header.
    """
    links = build_links(request, total=total, count=count, offset=offset)
    bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": total,
        "link": links,
        "entry": entries,
    }
    response = Response(bundle, status=status.HTTP_200_OK)
    response["Link"] = _link_header(links)
    return response
