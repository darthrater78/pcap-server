"""The two routes behind the filter box: is this a filter, and what is that field called.

Neither reads a capture, so neither needs one here. What they do need is a
session, a budget, and to pass nothing to argv that is not a filter or the
start of a field name -- and the packets route beside them has to say how many
packets matched, not only how many it returned.
"""

from __future__ import annotations

import pytest

from backend import main, packet_parser
from tests.test_packet_parser import needs_tshark
from tests.test_capture_upload import PCAP, _upload
from tests.test_custom_filters import _enrol, enrolled, secure_client  # noqa: F401  (fixtures)


def test_both_routes_need_a_session(secure_client):
    assert secure_client.get("/api/display-filter/check", params={"display_filter": "tcp"}).status_code == 401
    assert secure_client.get("/api/display-filter/fields", params={"prefix": "tcp"}).status_code == 401


@needs_tshark
def test_a_filter_that_compiles_is_ok(secure_client, enrolled):
    body = secure_client.get("/api/display-filter/check", params={"display_filter": "tcp.port == 443"}).json()
    assert body == {"ok": True, "reason": ""}


@needs_tshark
def test_a_filter_that_does_not_compile_is_a_verdict_not_an_error(secure_client, enrolled):
    """A half-typed filter is the normal state of the box, so it is a 200."""
    resp = secure_client.get("/api/display-filter/check", params={"display_filter": "tcp.porrt == 80"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False and "tcp.porrt" in resp.json()["reason"]


def test_an_unfilled_field_reference_is_not_ok(secure_client, enrolled):
    body = secure_client.get("/api/display-filter/check", params={"display_filter": "ip.src == ${ip.dst}"}).json()
    assert body["ok"] is False and "selected packet" in body["reason"]


def test_an_empty_box_is_ok_without_asking_tshark(secure_client, enrolled, monkeypatch):
    async def boom(*_a, **_k):
        raise AssertionError("nothing to compile")
    monkeypatch.setattr(packet_parser, "_run_tool", boom)
    assert secure_client.get("/api/display-filter/check").json()["ok"] is True


@needs_tshark
def test_field_names_are_completed_from_the_registry(secure_client, enrolled):
    body = secure_client.get("/api/display-filter/fields", params={"prefix": "tcp.analysis.byt"}).json()
    assert [f["name"] for f in body["fields"]] == ["tcp.analysis.bytes_in_flight"]


@pytest.mark.parametrize("prefix", ["-G", "fields,x", "tcp port", ".tcp", "tcp;id"])
def test_a_prefix_that_is_not_a_field_name_is_a_400(secure_client, enrolled, prefix):
    assert secure_client.get("/api/display-filter/fields", params={"prefix": prefix}).status_code == 400


def test_typing_has_a_budget_of_its_own(secure_client, enrolled, monkeypatch):
    """Larger than the packet list's, and not shared with it."""
    monkeypatch.setattr(main, "filter_assist_rate_limiter", main.SlidingWindowLimiter(max_per_minute=2))
    url = "/api/display-filter/fields"
    codes = [secure_client.get(url, params={"prefix": "-bad"}).status_code for _ in range(3)]
    assert codes == [400, 400, 429]
    assert secure_client.get("/api/display-filter/check").status_code == 429


@needs_tshark
def test_the_packets_route_says_how_many_matched(secure_client, enrolled):
    capture_id = _upload(secure_client, PCAP).json()["id"]
    url = f"/api/captures/{capture_id}/packets"
    page = secure_client.get(url, params={"limit": 2}).json()
    assert len(page["packets"]) == 2 and page["matched"] == 3 and page["total"] == 3
    rest = secure_client.get(url, params={"limit": 2, "offset": page["packets"][-1]["number"]}).json()
    assert [p["number"] for p in rest["packets"]] == [3] and rest["matched"] == 3
    one = secure_client.get(url, params={"display_filter": "udp.dstport == 40001"}).json()
    assert one["matched"] == 1 and one["total"] == 3
