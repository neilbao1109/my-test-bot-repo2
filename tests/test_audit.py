"""Audit log."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from clawfs.audit import AuditLog


def test_audit_write_and_tail(tmp_path):
    log = AuditLog(str(tmp_path))
    log.write("PUT refs", "alice", ref_path="/refs/a", bytes=10, ip="1.2.3.4")
    log.write("PUT refs", "bob", ref_path="/refs/b", bytes=20, ip="5.6.7.8")
    log.write("DELETE refs", "alice", ref_path="/refs/a", ip="1.2.3.4", status=204)

    all_entries = log.tail(limit=10)
    assert len(all_entries) == 3
    # newest first
    assert all_entries[0]["op"] == "DELETE refs"

    alice = log.tail(tenant_id="alice")
    assert len(alice) == 2
    assert all(e["tenant_id"] == "alice" for e in alice)


def test_audit_since_filter(tmp_path):
    log = AuditLog(str(tmp_path))
    log.write("PUT refs", "alice")
    out = log.tail(since=datetime.now(timezone.utc) - timedelta(seconds=10))
    assert len(out) == 1
    out = log.tail(since=datetime.now(timezone.utc) + timedelta(seconds=10))
    assert out == []


def test_audit_via_api(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWFS_API_TOKENS", "sk_test")
    from fastapi.testclient import TestClient
    from clawfs.api import create_app

    app = create_app(str(tmp_path))
    c = TestClient(app)
    H = {"Authorization": "Bearer sk_test"}
    c.put("/refs/x.txt", headers=H, files={"file": ("x.txt", b"hello")})
    log = AuditLog(str(tmp_path))
    entries = log.tail(limit=10)
    # should have at least one entry for the PUT
    puts = [e for e in entries if e.get("op", "").startswith("PUT")]
    assert len(puts) >= 1
    assert puts[0]["status"] == 200
