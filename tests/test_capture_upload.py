"""Uploading a pcap recorded elsewhere: POST /api/captures/upload.

An upload is stored exactly as a capture is -- sealed with the vault key,
named by a server-generated uuid, read through the same source -- so these
tests hold it to that, plus the ways a body can be refused. The important
ones are the two that fail open if they regress: a chunked body with no
Content-Length must still be capped, and a locked vault must refuse rather
than write the pcap in the clear.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.auth import create_session_token
from backend.crypto import MAGIC
from backend.database import Database
from tests.packet_builders import dns_response_a, ethernet, ip4, ipv4, mac, pcap, udp

UPLOAD = "/api/captures/upload"


def _frame(i: int) -> bytes:
    payload = udp(ip4("10.0.0.53"), ip4("10.0.0.9"), 53, 40000 + i,
                  dns_response_a(f"host{i}.example.com", "10.0.0.9"))
    return ethernet(mac("00:00:00:00:00:02"), mac("00:00:00:00:00:01"), 0x0800,
                    ipv4(ip4("10.0.0.53"), ip4("10.0.0.9"), 17, payload))


PCAP = pcap([_frame(i) for i in range(3)])


@pytest.fixture()
def secure_client():
    with TestClient(main.app, base_url="https://testserver") as c:
        yield c


def _enroll(client: TestClient) -> str:
    user_id = str(uuid.uuid4())
    main.db.create_user(user_id, f"upload-{user_id[:8]}", "scrypt$1$1$1$00$00", is_admin=False)
    main.db.set_totp_secret(user_id, "A" * 32)
    main.db.confirm_totp(user_id)
    token, _ = create_session_token(main.db, user_id)
    client.cookies.set("session", token)
    return user_id


def _forget_uploads(user_id: str) -> None:
    for capture_id, info in list(main.capture_manager._captures.items()):
        if info.user_id == user_id:
            Path(info.local_path).unlink(missing_ok=True)
            main.capture_manager._captures.pop(capture_id, None)
            main.db.delete_capture(capture_id)
    main.upload_rate_limiter._hits.pop(user_id, None)


@pytest.fixture()
def enrolled(secure_client):
    user_id = _enroll(secure_client)
    try:
        yield user_id
    finally:
        _forget_uploads(user_id)
        main.db.delete_user(user_id)


@pytest.fixture()
def small_limit():
    """max_upload_mb at 1, so the oversize cases stay cheap."""
    before = main.db.get_setting_int("max_upload_mb")
    main.db.set_setting("max_upload_mb", "1")
    try:
        yield 1024 * 1024
    finally:
        main.db.set_setting("max_upload_mb", str(before))


def _upload(client, body, filename="trace.pcap"):
    return client.post(UPLOAD, params={"filename": filename}, content=body)


def _captures_dir() -> Path:
    return Path(main.capture_manager._captures_dir)


def _leftovers() -> set[str]:
    return {p.name for p in _captures_dir().glob("*.partial")}


# --- the stored file ----------------------------------------------------------


def test_an_upload_is_sealed_on_disk_not_stored_as_the_pcap(secure_client, enrolled):
    resp = _upload(secure_client, PCAP)
    assert resp.status_code == 200, resp.text
    path = Path(resp.json()["local_path"])

    on_disk = path.read_bytes()
    assert on_disk.startswith(MAGIC)
    assert PCAP[:4] not in on_disk[:64], "the pcap magic must not be readable at the head"
    assert PCAP not in on_disk


def test_the_stored_name_is_a_server_uuid_never_the_client_filename(secure_client, enrolled):
    resp = _upload(secure_client, PCAP, filename="my trace.pcap")
    body = resp.json()
    path = Path(body["local_path"])
    assert path.parent == _captures_dir()
    assert path.name.startswith(body["id"])
    assert "my trace" not in path.name
    assert body["name"] == "my trace.pcap"


def test_the_stored_file_is_owner_only(secure_client, enrolled):
    path = Path(_upload(secure_client, PCAP).json()["local_path"])
    assert path.stat().st_mode & 0o777 == 0o600


def test_a_download_returns_the_uploaded_bytes_exactly(secure_client, enrolled):
    capture_id = _upload(secure_client, PCAP).json()["id"]
    resp = secure_client.get(f"/api/captures/{capture_id}/download")
    assert resp.status_code == 200
    assert resp.content == PCAP


def test_the_viewer_reads_an_upload_through_the_packets_route(secure_client, enrolled):
    capture_id = _upload(secure_client, PCAP).json()["id"]
    resp = secure_client.get(f"/api/captures/{capture_id}/packets")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 3


# --- the record ---------------------------------------------------------------


def test_the_record_is_marked_as_an_upload_and_claims_nothing_else(secure_client, enrolled):
    body = _upload(secure_client, PCAP).json()
    assert body["origin"] == "upload"
    assert body["status"] == "completed"
    assert body["packet_count"] == 3
    for field in ("server_id", "server_label", "interface", "bpf_filter", "command", "remote_path"):
        assert body[field] == "", f"{field} must stay empty on an upload"


def test_the_upload_appears_in_its_owners_list(secure_client, enrolled):
    capture_id = _upload(secure_client, PCAP).json()["id"]
    listed = {c["id"]: c for c in secure_client.get("/api/captures").json()}
    assert listed[capture_id]["origin"] == "upload"


def test_the_origin_survives_a_reload_from_the_database(secure_client, enrolled):
    capture_id = _upload(secure_client, PCAP).json()["id"]
    row = [c for c in main.db.list_captures() if c["id"] == capture_id][0]
    assert row["origin"] == "upload"


@pytest.mark.parametrize("filename", ["../../etc/passwd", "a/b.pcap", "<script>.pcap", " "])
def test_an_odd_filename_is_dropped_as_a_label_not_rewritten(secure_client, enrolled, filename):
    body = _upload(secure_client, PCAP, filename=filename).json()
    assert body["name"] == ""
    assert Path(body["local_path"]).parent == _captures_dir()


def test_another_user_can_neither_see_nor_download_an_upload(secure_client, enrolled):
    capture_id = _upload(secure_client, PCAP).json()["id"]

    other = _enroll(secure_client)
    try:
        assert capture_id not in {c["id"] for c in secure_client.get("/api/captures").json()}
        assert secure_client.get(f"/api/captures/{capture_id}").status_code == 404
        assert secure_client.get(f"/api/captures/{capture_id}/download").status_code == 404
    finally:
        main.db.delete_user(other)


# --- refusals -----------------------------------------------------------------


@pytest.mark.parametrize("body, reason", [
    (b"", "empty"),
    (b"\xa1\xb2", "under four bytes"),
    (b"GIF89a" + b"\x00" * 64, "not a pcap or pcapng"),
    (PCAP[:24] + b"\xff" * 40, "could not be read"),
])
def test_a_body_that_is_not_a_readable_capture_is_refused(secure_client, enrolled, body, reason):
    before = set(_captures_dir().iterdir())
    resp = _upload(secure_client, body)
    assert resp.status_code == 400
    assert reason in resp.json()["detail"]
    assert set(_captures_dir().iterdir()) == before, "a refusal leaves nothing on disk"
    assert not [c for c in secure_client.get("/api/captures").json()]


def test_an_oversize_body_with_content_length_is_refused_early(secure_client, enrolled, small_limit):
    body = PCAP + b"\x00" * (small_limit + 128 * 1024)
    resp = _upload(secure_client, body)
    assert resp.status_code == 413
    assert not _leftovers()


def test_an_oversize_chunked_body_is_capped_off_the_stream(secure_client, enrolled, small_limit):
    """No Content-Length, so the middleware has nothing to refuse on. The
    route has to count the bytes itself -- this is the bypass the upload
    closed, and the case that fails open if that counting ever goes."""
    sent = {"bytes": 0}

    def chunks():
        yield PCAP
        for _ in range(small_limit // (64 * 1024) + 4):
            sent["bytes"] += 64 * 1024
            yield b"\x00" * (64 * 1024)

    before = set(_captures_dir().iterdir())
    resp = _upload(secure_client, chunks())
    assert resp.status_code == 400
    assert "MB limit" in resp.json()["detail"]
    assert set(_captures_dir().iterdir()) == before
    assert not _leftovers()


def test_a_chunked_body_under_the_limit_is_accepted(secure_client, enrolled, small_limit):
    def chunks():
        # One byte at a time for the header: the magic check must wait for
        # four bytes rather than judge a one-byte first chunk.
        for b in PCAP[:4]:
            yield bytes([b])
        yield PCAP[4:]

    resp = _upload(secure_client, chunks())
    assert resp.status_code == 200, resp.text
    assert resp.json()["packet_count"] == 3


def test_a_locked_vault_refuses_rather_than_writing_in_the_clear(secure_client, enrolled, monkeypatch):
    vault = main.capture_manager._vault
    assert vault is not None and vault.enabled, "the suite runs with encryption on"
    monkeypatch.setattr(vault, "_cryptor", None)
    assert vault.locked

    before = set(_captures_dir().iterdir())
    resp = _upload(secure_client, PCAP)
    assert resp.status_code == 503
    assert "locked" in resp.json()["detail"]
    assert set(_captures_dir().iterdir()) == before, "nothing may reach disk unsealed"


def test_uploads_over_plain_http_are_refused(enrolled):
    with TestClient(main.app, base_url="http://testserver") as plain:
        token, _ = create_session_token(main.db, enrolled)
        plain.cookies.set("session", token)
        resp = _upload(plain, PCAP)
    assert resp.status_code == 403


def test_uploads_are_rate_limited_per_user(secure_client, enrolled):
    allowed = main.upload_rate_limiter.max_per_minute
    for _ in range(allowed):
        assert _upload(secure_client, PCAP).status_code == 200
    assert _upload(secure_client, PCAP).status_code == 429


def test_an_upload_needs_a_session(secure_client):
    secure_client.cookies.clear()
    assert _upload(secure_client, PCAP).status_code == 401


# --- the origin migration -----------------------------------------------------


def test_the_origin_migration_backfills_existing_rows_as_captures(tmp_path):
    """Every row that predates uploads IS a capture this server took, so the
    backfill is 'capture' -- a fact, with no 'unknown' state to represent."""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE users (
            id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, totp_secret TEXT,
            totp_confirmed INTEGER DEFAULT 0, created_at TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0
        );
        CREATE TABLE captures (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            user_id TEXT NOT NULL,
            server_id TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT,
            stopped_at TEXT,
            command TEXT NOT NULL DEFAULT '',
            remote_path TEXT NOT NULL DEFAULT '',
            local_path TEXT NOT NULL DEFAULT '',
            packet_count INTEGER NOT NULL DEFAULT 0,
            file_size INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',
            server_label TEXT NOT NULL DEFAULT '',
            interface TEXT NOT NULL DEFAULT '',
            live_stream INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO users (id, username, password_hash, created_at)
            VALUES ('u1', 'alice', 'h', '2026-01-01T00:00:00');
        INSERT INTO captures (id, user_id, server_id, status)
            VALUES ('old', 'u1', 's1', 'completed');
    """)
    conn.commit()
    conn.close()

    old = [c for c in Database(path).list_captures() if c["id"] == "old"][0]
    assert old["origin"] == "capture"
    Database(path)  # and a second open does not trip over the column
