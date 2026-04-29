"""Tenant quota enforcement."""
from __future__ import annotations

import pytest

from clawfs.core import ClawFS, QuotaExceeded


@pytest.fixture
def fs(tmp_path):
    f = ClawFS.local(str(tmp_path))
    f.upsert_tenant("acme", tokens=["sk_acme"], max_bytes=1024, max_objects=3)
    return f


def test_under_quota_writes_succeed(fs):
    fs.put_ref("a.txt", b"x" * 100, tenant_id="acme")
    u = fs.get_usage("acme")
    assert u["used_bytes"] == 100
    assert u["used_objects"] == 1


def test_over_byte_quota_raises_413(fs):
    fs.put_ref("a.txt", b"x" * 1000, tenant_id="acme")
    with pytest.raises(QuotaExceeded) as ei:
        fs.put_ref("b.txt", b"y" * 200, tenant_id="acme")
    assert ei.value.kind == "bytes"
    assert ei.value.limit == 1024


def test_over_object_quota_raises_413(fs):
    fs.put_ref("1", b"a", tenant_id="acme")
    fs.put_ref("2", b"b", tenant_id="acme")
    fs.put_ref("3", b"c", tenant_id="acme")
    with pytest.raises(QuotaExceeded) as ei:
        fs.put_ref("4", b"d", tenant_id="acme")
    assert ei.value.kind == "objects"


def test_dedup_does_not_double_count(fs):
    fs.put_ref("first.txt", b"same content", tenant_id="acme")
    used_after_first = fs.get_usage("acme")["used_bytes"]
    # second ref to same content under same tenant: shouldn't bump bytes
    fs.put_ref("second.txt", b"same content", tenant_id="acme")
    used_after_second = fs.get_usage("acme")["used_bytes"]
    assert used_after_first == used_after_second
    # but object count goes up if we count refs, stays same if we count blobs.
    # We chose: object count = unique blobs per tenant.
    assert fs.get_usage("acme")["used_objects"] == 1


def test_delete_ref_frees_quota(fs):
    fs.put_ref("a.txt", b"x" * 500, tenant_id="acme")
    assert fs.get_usage("acme")["used_bytes"] == 500
    fs.delete_ref("a.txt", tenant_id="acme")
    u = fs.get_usage("acme")
    assert u["used_bytes"] == 0
    assert u["used_objects"] == 0


def test_default_tenant_is_unmanaged(fs):
    """Single-tenant deployments (no Tenant row) shouldn't be rate-limited."""
    fs.put_ref("a.txt", b"z" * 100_000, tenant_id="default")  # way over acme's quota
    u = fs.get_usage("default")
    assert u["unmanaged"] is True


def test_quota_via_api_returns_413(tmp_path, monkeypatch):
    """End-to-end: API maps QuotaExceeded → HTTP 413 with JSON body."""
    monkeypatch.setenv("CLAWFS_API_TOKENS", "sk_acme")
    monkeypatch.setenv("CLAWFS_ROOT", str(tmp_path))
    from fastapi.testclient import TestClient
    from clawfs.api import create_app
    app = create_app(str(tmp_path))
    fs = ClawFS.local(str(tmp_path))
    fs.upsert_tenant("acme", tokens=["sk_acme"], max_bytes=200)
    c = TestClient(app)
    H = {"Authorization": "Bearer sk_acme"}

    # under
    r = c.put("/refs/small.txt", headers=H, files={"file": ("small.txt", b"x" * 100)})
    assert r.status_code == 200
    # over
    r = c.put("/refs/big.txt", headers=H, files={"file": ("big.txt", b"y" * 500)})
    assert r.status_code == 413
    j = r.json()
    assert j["kind"] == "bytes"
    assert j["limit"] == 200

    # /usage
    r = c.get("/usage", headers=H)
    assert r.status_code == 200
    assert r.json()["used_bytes"] == 100
    assert r.json()["max_bytes"] == 200
