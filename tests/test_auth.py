"""Auth tests: 401 vs 200 on write/read endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWFS_ROOT", str(tmp_path))
    monkeypatch.setenv("CLAWFS_API_TOKENS", "secret-a,secret-b")
    monkeypatch.delenv("CLAWFS_REQUIRE_AUTH_READ", raising=False)
    # rebuild app fresh under env
    from importlib import reload
    import clawfs.api as api_mod
    reload(api_mod)
    return TestClient(api_mod.app)


def test_put_blob_requires_auth(client):
    r = client.put("/blobs", files={"file": ("x.txt", b"hi")})
    assert r.status_code == 401

    r = client.put(
        "/blobs",
        files={"file": ("x.txt", b"hi")},
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401

    r = client.put(
        "/blobs",
        files={"file": ("x.txt", b"hi")},
        headers={"Authorization": "Bearer secret-a"},
    )
    assert r.status_code == 200
    assert "hash" in r.json()


def test_read_endpoint_open_by_default(client):
    # seed data
    r = client.put(
        "/refs/readme",
        files={"file": ("r", b"hello")},
        headers={"Authorization": "Bearer secret-a"},
    )
    assert r.status_code == 200

    # unauthenticated GET works (read auth not required)
    r = client.get("/refs/readme")
    assert r.status_code == 200
    assert r.content == b"hello"


def test_healthz_and_metrics(client):
    assert client.get("/healthz").status_code == 200
    m = client.get("/metrics")
    assert m.status_code == 200
    assert "clawfs_uptime_seconds" in m.text
    assert "clawfs_requests_total" in m.text


def test_read_auth_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWFS_ROOT", str(tmp_path))
    monkeypatch.setenv("CLAWFS_API_TOKENS", "tok")
    monkeypatch.setenv("CLAWFS_REQUIRE_AUTH_READ", "1")
    from importlib import reload
    import clawfs.api as api_mod
    reload(api_mod)
    c = TestClient(api_mod.app)

    c.put("/refs/x", files={"file": ("r", b"data")}, headers={"Authorization": "Bearer tok"})
    assert c.get("/refs/x").status_code == 401
    assert c.get("/refs/x", headers={"Authorization": "Bearer tok"}).status_code == 200
