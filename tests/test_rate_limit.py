"""Sprint 6 P2: per-tenant + per-IP rate limiting and daily reset."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from clawfs.api import create_app
from clawfs.core import ClawFS
from clawfs.ratelimit import RateLimiter


@pytest.fixture
def app_factory(tmp_path, monkeypatch):
    """Build an app + fs pair sharing the tmp_path data root.

    We monkey-set CLAWFS_API_TOKENS for the global token check so write
    routes pass auth, and rely on Tenant rows for the rate-limit lookup.
    """
    monkeypatch.setenv("CLAWFS_ROOT", str(tmp_path))

    def _build(tokens: list[str]):
        monkeypatch.setenv("CLAWFS_API_TOKENS", ",".join(tokens))
        app = create_app(str(tmp_path))
        # Always reset shared limiter between scenarios.
        app.state.rate_limiter.reset()
        fs = ClawFS.local(str(tmp_path))
        return app, fs

    return _build


def _put(client: TestClient, path: str, token: str, ip: str = "1.2.3.4", body: bytes = b"hi"):
    return client.put(
        f"/refs/{path}",
        headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": ip},
        files={"file": (path, body)},
    )


# ---------- middleware ----------

def test_no_rate_limit_when_unset(app_factory):
    app, fs = app_factory(["sk_free"])
    fs.upsert_tenant("free", tokens=["sk_free"])  # rate_limit_per_minute = None
    c = TestClient(app)
    for i in range(10):
        r = _put(c, f"f{i}.txt", "sk_free")
        assert r.status_code == 200, r.text


def test_rate_limit_blocks_after_threshold(app_factory):
    app, fs = app_factory(["sk_lim"])
    fs.upsert_tenant("lim", tokens=["sk_lim"], rate_limit_per_minute=5)
    c = TestClient(app)
    for i in range(5):
        assert _put(c, f"a{i}.txt", "sk_lim").status_code == 200
    r = _put(c, "a5.txt", "sk_lim")
    assert r.status_code == 429
    body = r.json()
    assert body["kind"] == "rate_limit"
    assert body["tenant_id"] == "lim"
    assert body["retry_after_seconds"] >= 1
    assert "Retry-After" in r.headers
    assert int(r.headers["Retry-After"]) >= 1


def test_rate_limit_per_ip_buckets(app_factory):
    app, fs = app_factory(["sk_lim"])
    fs.upsert_tenant("lim", tokens=["sk_lim"], rate_limit_per_minute=5)
    c = TestClient(app)
    # 5 from each of two IPs, all should pass.
    for i in range(5):
        assert _put(c, f"x{i}.txt", "sk_lim", ip="10.0.0.1").status_code == 200
    for i in range(5):
        assert _put(c, f"y{i}.txt", "sk_lim", ip="10.0.0.2").status_code == 200
    # 6th from either IP gets blocked.
    assert _put(c, "x5.txt", "sk_lim", ip="10.0.0.1").status_code == 429
    assert _put(c, "y5.txt", "sk_lim", ip="10.0.0.2").status_code == 429


def test_admin_and_health_not_rate_limited(app_factory):
    app, fs = app_factory(["sk_lim"])
    fs.upsert_tenant("lim", tokens=["sk_lim"], rate_limit_per_minute=1)
    c = TestClient(app)
    # /healthz never blocked.
    for _ in range(20):
        assert c.get("/healthz").status_code == 200
    # Burn the limit on a real endpoint.
    assert _put(c, "a.txt", "sk_lim").status_code == 200
    assert _put(c, "b.txt", "sk_lim").status_code == 429


# ---------- daily reset ----------

def test_daily_reset_wipes_usage(tmp_path):
    fs = ClawFS.local(str(tmp_path))
    fs.upsert_tenant("demo", tokens=["sk_demo"], max_bytes=1024, daily_reset=True)
    fs.put_ref("a.txt", b"x" * 200, tenant_id="demo")
    assert fs.get_usage("demo")["used_bytes"] == 200

    # Pretend last reset was yesterday.
    from sqlmodel import Session
    from clawfs.db import Tenant
    with Session(fs.engine) as s:
        t = s.get(Tenant, "demo")
        t.last_reset_at = datetime.utcnow() - timedelta(days=1)
        s.add(t)
        s.commit()

    # Next write triggers reset → used_bytes resets to 0 then accounts new write.
    fs.put_ref("b.txt", b"y" * 50, tenant_id="demo")
    u = fs.get_usage("demo")
    assert u["used_bytes"] == 50
    assert u["used_objects"] == 1


def test_daily_reset_off_by_default(tmp_path):
    fs = ClawFS.local(str(tmp_path))
    fs.upsert_tenant("plain", tokens=["sk_p"], max_bytes=1024)
    fs.put_ref("a.txt", b"x" * 100, tenant_id="plain")
    # Even forcing maybe_reset_daily shouldn't do anything.
    assert fs.maybe_reset_daily("plain") is False
    assert fs.get_usage("plain")["used_bytes"] == 100


# ---------- raw RateLimiter unit tests ----------

def test_ratelimiter_unlimited():
    r = RateLimiter()
    for _ in range(100):
        ok, _ = r.check("t", "ip", 0)
        assert ok


def test_ratelimiter_blocks_and_reports_retry():
    r = RateLimiter()
    for _ in range(3):
        assert r.check("t", "ip", 3)[0] is True
    ok, retry = r.check("t", "ip", 3)
    assert ok is False
    assert retry >= 1
