"""
Unit tests for the FHIR ``searchset`` Bundle paging helpers
(``apps.fhir.services.bundle``).

These exercise the paging maths and link/header assembly directly, without
standing up a tenant or hitting the database.
"""

from __future__ import annotations

from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.fhir.services import bundle

_factory = APIRequestFactory()


def _request(query: str = "") -> Request:
    path = "/api/v1/fhir/Patient/"
    raw = _factory.get(f"{path}?{query}" if query else path)
    return Request(raw)


# ─── _count parsing/clamping ─────────────────────────────────────────────────


def test_parse_count_defaults_when_absent():
    assert bundle.parse_count(_request()) == bundle.DEFAULT_COUNT


def test_parse_count_honours_explicit_default():
    assert bundle.parse_count(_request(), default=50) == 50


def test_parse_count_clamped_to_max():
    assert bundle.parse_count(_request("_count=9999")) == bundle.MAX_COUNT


def test_parse_count_rejects_non_positive():
    assert bundle.parse_count(_request("_count=0")) == bundle.DEFAULT_COUNT
    assert bundle.parse_count(_request("_count=-5")) == bundle.DEFAULT_COUNT


def test_parse_count_rejects_garbage():
    assert bundle.parse_count(_request("_count=abc")) == bundle.DEFAULT_COUNT


# ─── _offset parsing ─────────────────────────────────────────────────────────


def test_parse_offset_default_zero():
    assert bundle.parse_offset(_request()) == 0


def test_parse_offset_never_negative():
    assert bundle.parse_offset(_request("_offset=-10")) == 0


def test_parse_offset_garbage_is_zero():
    assert bundle.parse_offset(_request("_offset=xyz")) == 0


# ─── Link relation assembly ──────────────────────────────────────────────────


def _relations(links):
    return [link["relation"] for link in links]


def test_links_single_page_has_no_next_or_previous():
    # A result set that fits on one page still advertises first/last (they equal
    # self) but must not advertise next/previous.
    links = bundle.build_links(_request("_count=20"), total=5, count=20, offset=0)
    rels = _relations(links)
    assert "next" not in rels
    assert "previous" not in rels
    assert "self" in rels


def test_links_empty_result_has_only_self():
    links = bundle.build_links(_request(), total=0, count=20, offset=0)
    assert _relations(links) == ["self"]


def test_links_first_page_of_many_has_next_and_last_but_no_previous():
    links = bundle.build_links(_request("_count=20"), total=55, count=20, offset=0)
    rels = _relations(links)
    assert "next" in rels
    assert "last" in rels
    assert "first" in rels
    assert "previous" not in rels


def test_links_middle_page_has_all_relations():
    links = bundle.build_links(_request("_count=20"), total=55, count=20, offset=20)
    rels = _relations(links)
    assert set(rels) == {"self", "first", "previous", "next", "last"}


def test_links_last_page_has_no_next():
    links = bundle.build_links(_request("_count=20"), total=55, count=20, offset=40)
    rels = _relations(links)
    assert "next" not in rels
    assert "previous" in rels


def test_links_last_offset_is_aligned_to_page_boundary():
    links = bundle.build_links(_request("_count=20"), total=55, count=20, offset=0)
    last = next(link for link in links if link["relation"] == "last")
    # 55 items, page size 20 → last page starts at offset 40.
    assert "_offset=40" in last["url"]


def test_links_previous_clamped_to_zero():
    # offset 10 with count 20 → previous offset should clamp to 0, not -10.
    links = bundle.build_links(_request("_count=20"), total=55, count=20, offset=10)
    prev = next(link for link in links if link["relation"] == "previous")
    assert "_offset=0" in prev["url"]


# ─── searchset_response wrapper ──────────────────────────────────────────────


def test_searchset_response_shape_and_link_header():
    entries = [{"resource": {"resourceType": "Patient", "id": "1"}}]
    resp = bundle.searchset_response(
        _request("_count=20"), entries=entries, total=55, count=20, offset=20
    )
    assert resp.data["resourceType"] == "Bundle"
    assert resp.data["type"] == "searchset"
    assert resp.data["total"] == 55
    assert resp.data["entry"] == entries
    # RFC 5988 Link header mirrors the Bundle.link relations.
    header = resp["Link"]
    for rel in ("self", "first", "previous", "next", "last"):
        assert f'rel="{rel}"' in header
