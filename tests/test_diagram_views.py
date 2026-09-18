"""Saved Traffic Diagram views, and the Capture tab's saved presets.

A diagram view is the operator's arrangement of one capture's Traffic
Diagram -- host positions, picked chips, zoom -- and belongs to that capture:
deleting the capture deletes it (by foreign key). Everything in it is written
by the browser and replayed into the page later, so its shape is validated on
the way in. Presets are per-account, and hold catalog KEYS, never BPF text.
"""

from __future__ import annotations

import pytest

from backend import main
from tests.test_capture_views import _a_capture, capture, enrolled, secure_client  # noqa: F401

STATE = {
    "display_filter": "tcp",
    "positions": {"10.0.0.1": {"x": 12.5, "y": -40}, "fe80::1": {"x": 0, "y": 0}},
    "selected": ["DNS", "problem:reset"],
    "spacing": 1.5,
    "zoom": {"k": 0.8, "tx": 10, "ty": 20},
    "resolve_names": True,
}


def _save(client, capture_id, name="layout", state=STATE):
    return client.post(f"/api/captures/{capture_id}/diagram-views", json={"name": name, "state": state})


def test_a_saved_diagram_comes_back_with_its_positions(secure_client, capture):
    assert _save(secure_client, capture).status_code == 200
    listed = secure_client.get(f"/api/captures/{capture}/diagram-views").json()
    assert [v["name"] for v in listed] == ["layout"]
    state = listed[0]["state"]
    assert state["positions"]["10.0.0.1"] == {"x": 12.5, "y": -40.0}
    assert state["selected"] == STATE["selected"]
    assert state["zoom"]["k"] == 0.8


def test_a_saved_diagram_can_be_overwritten(secure_client, capture):
    view = _save(secure_client, capture).json()
    moved = {**STATE, "positions": {"10.0.0.1": {"x": 1, "y": 2}}}
    resp = secure_client.put(
        f"/api/captures/{capture}/diagram-views/{view['id']}", json={"name": "layout", "state": moved},
    )
    assert resp.status_code == 200
    assert resp.json()["state"]["positions"] == {"10.0.0.1": {"x": 1.0, "y": 2.0}}


def test_duplicate_diagram_names_are_a_conflict(secure_client, capture):
    _save(secure_client, capture)
    assert _save(secure_client, capture).status_code == 409


def test_deleting_a_capture_takes_its_diagrams_with_it(secure_client, enrolled):
    """By foreign key, like capture views -- the diagram goes with its capture."""
    capture_id = _a_capture(enrolled)
    _save(secure_client, capture_id)
    assert main.db.list_diagram_views(capture_id, enrolled)
    main.capture_manager._captures.pop(capture_id, None)
    main.db.delete_capture(capture_id)
    assert main.db.list_diagram_views(capture_id, enrolled) == []


def test_another_users_capture_is_not_found(secure_client, enrolled, capture):
    other_user = f"other-{enrolled[:8]}"
    main.db.create_user(other_user, other_user, "scrypt$1$1$1$00$00", is_admin=False)
    other = _a_capture(other_user)
    try:
        assert _save(secure_client, other).status_code == 404
        assert secure_client.get(f"/api/captures/{other}/diagram-views").status_code == 404
    finally:
        main.capture_manager._captures.pop(other, None)
        main.db.delete_capture(other)
        main.db.delete_user(other_user)


def test_a_view_id_from_another_capture_is_not_found(secure_client, enrolled, capture):
    view = _save(secure_client, capture).json()
    other = _a_capture(enrolled)
    try:
        resp = secure_client.delete(f"/api/captures/{other}/diagram-views/{view['id']}")
        assert resp.status_code == 404
    finally:
        main.capture_manager._captures.pop(other, None)
        main.db.delete_capture(other)


@pytest.mark.parametrize("bad", [
    {"display_filter": "tcp.port == 80; rm -rf /"},
    {"positions": {"10.0.0.1": {"x": 1e12, "y": 0}}},
    {"positions": {"has space": {"x": 0, "y": 0}}},
    {"positions": {f"10.0.{i // 256}.{i % 256}": {"x": 0, "y": 0} for i in range(501)}},
    {"selected": ["<script>alert(1)</script> x"]},
    {"selected": [f"P{i}" for i in range(101)]},
    {"spacing": 100},
    {"zoom": {"k": 0, "tx": 0, "ty": 0}},
])
def test_hostile_or_oversized_state_is_refused(secure_client, capture, bad):
    assert _save(secure_client, capture, state={**STATE, **bad}).status_code == 422


# --- capture presets -----------------------------------------------------------


def test_a_preset_round_trips_and_is_private(secure_client, enrolled):
    resp = secure_client.post("/api/capture-presets", json={
        "label": "quiet LAN",
        "settings": {"exclusions": ["arp", "mdns"], "snaplen": 256, "max_packets": 5000},
    })
    assert resp.status_code == 200
    listed = secure_client.get("/api/capture-presets").json()
    assert [p["label"] for p in listed] == ["quiet LAN"]
    assert listed[0]["settings"]["exclusions"] == ["arp", "mdns"]
    assert main.db.list_capture_presets("someone-else") == []
    assert secure_client.delete(f"/api/capture-presets/{listed[0]['id']}").status_code == 200
    assert secure_client.get("/api/capture-presets").json() == []


@pytest.mark.parametrize("settings", [
    {"exclusions": ["not arp or 1=1"]},
    {"exclusions": ["UPPER"]},
    {"snaplen": 10},
    {"max_packets": 0},
])
def test_a_preset_holds_catalog_keys_not_bpf(secure_client, enrolled, settings):
    resp = secure_client.post("/api/capture-presets", json={"label": "x", "settings": settings})
    assert resp.status_code == 422


def test_deleting_an_unknown_preset_is_not_found(secure_client, enrolled):
    assert secure_client.delete("/api/capture-presets/nope").status_code == 404


# --- subnet -> interface mapping on a capture -------------------------------


def test_a_subnet_map_is_stored_on_the_capture(secure_client, capture):
    resp = secure_client.put(f"/api/captures/{capture}/subnet-map", json={"mappings": [
        {"cidr": "10.42.0.5/16", "name": "cni0"}, {"cidr": "192.168.1.0/24", "name": "eth0"},
    ]})
    assert resp.status_code == 200
    assert resp.json()["subnet_map"] == [
        {"cidr": "10.42.0.0/16", "name": "cni0"}, {"cidr": "192.168.1.0/24", "name": "eth0"},
    ]
    stored = next(r for r in main.db.list_captures() if r["id"] == capture)
    assert stored["subnet_map"][0]["name"] == "cni0"


@pytest.mark.parametrize("bad", [
    {"cidr": "not-a-subnet", "name": "eth0"},
    {"cidr": "10.0.0.0/8", "name": "-rf"},
    {"cidr": "10.0.0.0/8", "name": "eth0; rm"},
    {"cidr": "10.0.0.0/8", "name": "x" * 40},
])
def test_a_bad_subnet_mapping_is_refused(secure_client, capture, bad):
    resp = secure_client.put(f"/api/captures/{capture}/subnet-map", json={"mappings": [bad]})
    assert resp.status_code == 422


def test_too_many_subnet_mappings_are_refused(secure_client, capture):
    rows = [{"cidr": f"10.{i}.0.0/16", "name": f"if{i}"} for i in range(33)]
    assert secure_client.put(f"/api/captures/{capture}/subnet-map", json={"mappings": rows}).status_code == 422
