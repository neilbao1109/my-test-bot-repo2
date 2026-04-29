"""Admin API + admin UI tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWFS_ROOT", str(tmp_path))
    monkeypatch.setenv("CLAWFS_API_TOKENS", "tenant-tok-from-env")
    monkeypatch.setenv("CLAWFS_ADMIN_TOKEN", "admin-secret")
    monkeypatch.delenv("CLAWFS_REQUIRE_AUTH_READ", raising=False)
    from importlib import reload
    import clawfs.api as api_mod
    reload(api_mod)
    return TestClient(api_mod.app)


def H(token):
    return {"Authorization": f"Bearer {token}"}


def test_admin_create_requires_admin_token(client):
    r = client.post("/admin/tenants", json={"id": "acme"})
    assert r.status_code == 401

    # tenant token (env CSV) must NOT pass admin check
    r = client.post("/admin/tenants", json={"id": "acme"}, headers=H("tenant-tok-from-env"))
    assert r.status_code == 401

    r = client.post("/admin/tenants", json={"id": "acme"}, headers=H("admin-secret"))
    assert r.status_code == 200
    body = r.json()
    assert body["tenant"]["id"] == "acme"
    assert body["token"].startswith("sk_")


def test_admin_list_shows_created_tenant(client):
    r = client.post(
        "/admin/tenants",
        json={"id": "acme", "name": "Acme", "max_bytes": 1024, "max_objects": 5},
        headers=H("admin-secret"),
    )
    assert r.status_code == 200
    tenant_token = r.json()["token"]

    r = client.get("/admin/tenants", headers=H("admin-secret"))
    assert r.status_code == 200
    rows = r.json()
    by_id = {t["id"]: t for t in rows}
    assert "acme" in by_id
    assert by_id["acme"]["max_bytes"] == 1024
    assert by_id["acme"]["max_objects"] == 5
    assert by_id["acme"]["token_count"] == 1

    # tenant token should work for /usage but NOT for admin endpoints
    assert client.get("/usage", headers=H(tenant_token)).status_code == 200
    assert client.get("/admin/tenants", headers=H(tenant_token)).status_code == 401


def test_admin_rotate_replaces_token(client):
    r = client.post("/admin/tenants", json={"id": "acme"}, headers=H("admin-secret"))
    old_token = r.json()["token"]
    # old token works against tenant-auth endpoint
    assert client.get("/usage", headers=H(old_token)).status_code == 200

    r = client.post("/admin/tenants/acme/rotate", headers=H("admin-secret"))
    assert r.status_code == 200
    new_token = r.json()["token"]
    assert new_token != old_token

    # old no longer authenticates, new one does
    assert client.get("/usage", headers=H(old_token)).status_code == 401
    assert client.get("/usage", headers=H(new_token)).status_code == 200


def test_admin_patch_updates_quota(client):
    client.post("/admin/tenants", json={"id": "acme"}, headers=H("admin-secret"))
    r = client.patch(
        "/admin/tenants/acme",
        json={"max_bytes": 2048, "max_objects": 99},
        headers=H("admin-secret"),
    )
    assert r.status_code == 200
    assert r.json()["max_bytes"] == 2048
    assert r.json()["max_objects"] == 99


def test_admin_delete_removes_tenant(client):
    client.post("/admin/tenants", json={"id": "acme"}, headers=H("admin-secret"))
    r = client.delete("/admin/tenants/acme", headers=H("admin-secret"))
    assert r.status_code == 200
    assert r.json() == {"deleted": True}

    rows = client.get("/admin/tenants", headers=H("admin-secret")).json()
    assert all(t["id"] != "acme" for t in rows)

    # deleting again → 404
    assert client.delete("/admin/tenants/acme", headers=H("admin-secret")).status_code == 404


def test_admin_ui_html_served(client):
    r = client.get("/admin/")
    assert r.status_code == 200
    assert "<title>ClawFS Admin</title>" in r.text
    # no external CDN references
    assert "cdn." not in r.text.lower()


def test_admin_token_unconfigured_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWFS_ROOT", str(tmp_path))
    monkeypatch.setenv("CLAWFS_API_TOKENS", "tk")
    monkeypatch.delenv("CLAWFS_ADMIN_TOKEN", raising=False)
    from importlib import reload
    import clawfs.api as api_mod
    reload(api_mod)
    c = TestClient(api_mod.app)
    # Even with a "correct-looking" bearer, no admin token configured → 401
    assert c.get("/admin/tenants", headers=H("anything")).status_code == 401
