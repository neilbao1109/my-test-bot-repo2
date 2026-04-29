"""FastAPI surface for ClawFS."""
from __future__ import annotations

import os
import time
from typing import AsyncIterator, Optional

import secrets
from pathlib import Path

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response

from .auth import load_tokens, require_admin, require_auth
from .core import DEFAULT_TENANT, ClawFS
from .db import QuotaExceeded
from .factory import make_storage
from .uploads import UploadManager


def _resolve_tenant(fs: ClawFS, authorization: Optional[str]) -> str:
    """Look at the bearer token and find the matching tenant.

    - If `authorization` is missing/invalid → "default" (read paths fall here).
    - If the token matches a Tenant record → that tenant.id.
    - Otherwise → "default" (back-compat with single-tenant deployments
      where CLAWFS_API_TOKENS holds a flat list and no Tenant rows exist).
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return DEFAULT_TENANT
    token = authorization.split(" ", 1)[1].strip()
    tid = fs.tenant_for_token(token)
    return tid or DEFAULT_TENANT


def _maybe_auth(authorization: Optional[str] = Header(default=None)) -> Optional[str]:
    if os.environ.get("CLAWFS_REQUIRE_AUTH_READ", "").lower() in ("1", "true", "yes"):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        if token not in load_tokens():
            raise HTTPException(401, "invalid token")
        return token
    return authorization


def create_app(root: Optional[str] = None) -> FastAPI:
    root = root or os.environ.get("CLAWFS_ROOT", "./clawfs-data")
    os.makedirs(root, exist_ok=True)
    storage = make_storage(root)
    fs = ClawFS(storage, db_url=f"sqlite:///{root}/clawfs.db")
    uploads = UploadManager(scratch_root=os.path.join(root, "uploads"), storage=storage, engine=fs.engine)

    # Let auth.py also accept tokens registered to Tenant rows.
    from . import auth as _auth
    _auth.tenant_token_check = fs.tenant_for_token
    app = FastAPI(title="ClawFS", version="0.5.0")

    @app.exception_handler(QuotaExceeded)
    async def _quota_handler(_req: Request, exc: QuotaExceeded):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=413,
            content={"detail": str(exc), "kind": exc.kind, "used": exc.used, "limit": exc.limit},
        )

    started = time.time()
    counters: dict[str, int] = {
        "blob_put": 0, "blob_get": 0,
        "ref_put": 0, "ref_get": 0, "ref_del": 0, "ref_list": 0,
        "share_create": 0, "share_resolve": 0,
        "gc_run": 0,
        "upload_create": 0, "upload_part": 0, "upload_complete": 0, "upload_abort": 0,
    }

    # ---------- write endpoints (require auth) ----------
    @app.put("/blobs", dependencies=[Depends(require_auth)])
    async def put_blob(file: UploadFile = File(...), authorization: Optional[str] = Header(default=None)):
        counters["blob_put"] += 1
        tid = _resolve_tenant(fs, authorization)
        h = fs.put_blob(await file.read(), tenant_id=tid)
        return {"hash": h}

    @app.put("/refs/{path:path}", dependencies=[Depends(require_auth)])
    async def put_ref(path: str, file: UploadFile = File(...), authorization: Optional[str] = Header(default=None)):
        counters["ref_put"] += 1
        tid = _resolve_tenant(fs, authorization)
        h, created = fs.put_ref(path, await file.read(), tenant_id=tid)
        return {"path": path, "hash": h, "created": created}

    @app.delete("/refs/{path:path}", dependencies=[Depends(require_auth)])
    def delete_ref(path: str, authorization: Optional[str] = Header(default=None)):
        counters["ref_del"] += 1
        tid = _resolve_tenant(fs, authorization)
        if not fs.delete_ref(path, tenant_id=tid):
            raise HTTPException(404, "ref not found")
        return {"deleted": path}

    @app.post("/shares", dependencies=[Depends(require_auth)])
    def create_share(ref_path: str = Form(...), ttl_seconds: Optional[int] = Form(None),
                     authorization: Optional[str] = Header(default=None)):
        counters["share_create"] += 1
        tid = _resolve_tenant(fs, authorization)
        try:
            token = fs.create_share(ref_path, ttl_seconds, tenant_id=tid)
        except KeyError:
            raise HTTPException(404, "ref not found")
        return {"token": token, "url": f"/shares/{token}"}

    @app.post("/gc", dependencies=[Depends(require_auth)])
    def gc(authorization: Optional[str] = Header(default=None)):
        counters["gc_run"] += 1
        tid = _resolve_tenant(fs, authorization)
        # If "default" tenant (no tenant configured) → GC everything.
        scope = None if tid == DEFAULT_TENANT else tid
        return {"removed": fs.gc(tenant_id=scope)}

    # ---------- multipart upload ----------
    @app.post("/uploads", dependencies=[Depends(require_auth)])
    def upload_create(target_ref: Optional[str] = Form(default=None),
                      authorization: Optional[str] = Header(default=None)):
        counters["upload_create"] += 1
        tid = _resolve_tenant(fs, authorization)
        upload_id = uploads.create(tenant_id=tid, target_ref=target_ref)
        return {"id": upload_id, "tenant_id": tid, "target_ref": target_ref}

    @app.put("/uploads/{upload_id}/parts/{part_number}", dependencies=[Depends(require_auth)])
    async def upload_part(upload_id: str, part_number: int, request: Request):
        counters["upload_part"] += 1

        async def _stream() -> AsyncIterator[bytes]:
            async for chunk in request.stream():
                yield chunk

        try:
            size, etag = await uploads.write_part(upload_id, part_number, _stream())
        except FileNotFoundError:
            raise HTTPException(404, "upload not found or completed")
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"n": part_number, "size": size, "etag": etag}

    @app.post("/uploads/{upload_id}/complete", dependencies=[Depends(require_auth)])
    def upload_complete(upload_id: str):
        counters["upload_complete"] += 1
        try:
            res = uploads.complete(upload_id)
        except FileNotFoundError:
            raise HTTPException(404, "upload not found")
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"hash": res.hash, "size": res.size, "blob_created": res.created}

    @app.delete("/uploads/{upload_id}", dependencies=[Depends(require_auth)])
    def upload_abort(upload_id: str):
        counters["upload_abort"] += 1
        if not uploads.abort(upload_id):
            raise HTTPException(404, "upload not found")
        return {"deleted": upload_id}

    # ---------- read endpoints (optional auth) ----------
    @app.get("/blobs/{hash_hex}")
    def get_blob(hash_hex: str, _: object = Depends(_maybe_auth)):
        counters["blob_get"] += 1
        try:
            return Response(fs.get_blob(hash_hex), media_type="application/octet-stream")
        except FileNotFoundError:
            raise HTTPException(404, "blob not found")

    @app.get("/refs/{path:path}")
    def get_ref(path: str, authorization: Optional[str] = Depends(_maybe_auth)):
        counters["ref_get"] += 1
        tid = _resolve_tenant(fs, authorization if isinstance(authorization, str) else None)
        data = fs.resolve_ref(path, tenant_id=tid)
        if data is None:
            raise HTTPException(404, "ref not found")
        return Response(data, media_type="application/octet-stream")

    @app.get("/refs")
    def list_refs(prefix: str = "", authorization: Optional[str] = Depends(_maybe_auth)):
        counters["ref_list"] += 1
        tid = _resolve_tenant(fs, authorization if isinstance(authorization, str) else None)
        return [
            {"path": r.path, "hash": r.hash, "updated_at": r.updated_at.isoformat()}
            for r in fs.list_refs(prefix, tenant_id=tid)
        ]

    @app.get("/shares/{token}")
    def resolve_share(token: str):
        counters["share_resolve"] += 1
        data = fs.resolve_share(token)
        if data is None:
            raise HTTPException(404, "share not found or expired")
        return Response(data, media_type="application/octet-stream")

    # ---------- ops ----------
    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "uptime_seconds": int(time.time() - started)}

    @app.get("/usage", dependencies=[Depends(require_auth)])
    def usage(authorization: Optional[str] = Header(default=None)):
        tid = _resolve_tenant(fs, authorization)
        return fs.get_usage(tid)

    # ---------- admin endpoints (require admin token) ----------
    def _serialize_tenant(t) -> dict:
        ntok = len([x for x in (t.tokens_csv or "").split(",") if x.strip()])
        return {
            "id": t.id,
            "name": t.name or "",
            "used_bytes": t.used_bytes,
            "used_objects": t.used_objects,
            "max_bytes": t.max_bytes,
            "max_objects": t.max_objects,
            "token_count": ntok,
        }

    @app.get("/admin/tenants", dependencies=[Depends(require_admin)])
    def admin_list_tenants():
        from sqlmodel import Session, select
        from .db import Tenant
        with Session(fs.engine) as s:
            rows = list(s.exec(select(Tenant)))
        return [_serialize_tenant(t) for t in rows]

    @app.post("/admin/tenants", dependencies=[Depends(require_admin)])
    def admin_create_tenant(payload: dict = Body(...)):
        tid = (payload.get("id") or "").strip()
        if not tid:
            raise HTTPException(400, "id is required")
        from sqlmodel import Session
        from .db import Tenant
        with Session(fs.engine) as s:
            if s.get(Tenant, tid) is not None:
                raise HTTPException(409, f"tenant {tid!r} already exists")
        token = f"sk_{secrets.token_urlsafe(24)}"
        t = fs.upsert_tenant(
            tid,
            name=payload.get("name") or tid,
            tokens=[token],
            max_bytes=payload.get("max_bytes"),
            max_objects=payload.get("max_objects"),
        )
        return {"tenant": _serialize_tenant(t), "token": token}

    @app.patch("/admin/tenants/{tenant_id}", dependencies=[Depends(require_admin)])
    def admin_update_tenant(tenant_id: str, payload: dict = Body(...)):
        from sqlmodel import Session
        from .db import Tenant
        with Session(fs.engine) as s:
            if s.get(Tenant, tenant_id) is None:
                raise HTTPException(404, "tenant not found")
        kwargs = {}
        if "max_bytes" in payload:
            kwargs["max_bytes"] = payload["max_bytes"]
        if "max_objects" in payload:
            kwargs["max_objects"] = payload["max_objects"]
        t = fs.upsert_tenant(tenant_id, **kwargs)
        return _serialize_tenant(t)

    @app.post("/admin/tenants/{tenant_id}/rotate", dependencies=[Depends(require_admin)])
    def admin_rotate_tenant(tenant_id: str):
        from sqlmodel import Session
        from .db import Tenant
        with Session(fs.engine) as s:
            if s.get(Tenant, tenant_id) is None:
                raise HTTPException(404, "tenant not found")
        new_token = f"sk_{secrets.token_urlsafe(24)}"
        fs.upsert_tenant(tenant_id, tokens=[new_token])
        return {"token": new_token}

    @app.delete("/admin/tenants/{tenant_id}", dependencies=[Depends(require_admin)])
    def admin_delete_tenant(tenant_id: str):
        from sqlmodel import Session
        from .db import Tenant
        with Session(fs.engine) as s:
            t = s.get(Tenant, tenant_id)
            if t is None:
                raise HTTPException(404, "tenant not found")
            s.delete(t)
            s.commit()
        return {"deleted": True}

    # ---------- admin UI (HTML, token-gated via fetch) ----------
    _admin_html_path = Path(__file__).with_name("admin_ui.html")

    @app.get("/admin/", include_in_schema=False)
    @app.get("/admin", include_in_schema=False)
    def admin_ui():
        if _admin_html_path.exists():
            return FileResponse(_admin_html_path, media_type="text/html")
        raise HTTPException(404, "admin UI not bundled")

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics():
        lines = [
            "# HELP clawfs_uptime_seconds Process uptime in seconds.",
            "# TYPE clawfs_uptime_seconds gauge",
            f"clawfs_uptime_seconds {int(time.time() - started)}",
            "# HELP clawfs_requests_total Request counters by operation.",
            "# TYPE clawfs_requests_total counter",
        ]
        for op, n in counters.items():
            lines.append(f'clawfs_requests_total{{op="{op}"}} {n}')
        return "\n".join(lines) + "\n"

    return app


app = create_app()
