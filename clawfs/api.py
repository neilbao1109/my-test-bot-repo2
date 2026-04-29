"""FastAPI surface for ClawFS."""
from __future__ import annotations

import os
import time
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, Response

from .auth import maybe_require_auth, require_auth
from .core import ClawFS
from .factory import make_storage


def create_app(root: Optional[str] = None) -> FastAPI:
    root = root or os.environ.get("CLAWFS_ROOT", "./clawfs-data")
    os.makedirs(root, exist_ok=True)
    storage = make_storage(root)
    fs = ClawFS(storage, db_url=f"sqlite:///{root}/clawfs.db")
    app = FastAPI(title="ClawFS", version="0.2.0")

    started = time.time()
    counters: dict[str, int] = {
        "blob_put": 0, "blob_get": 0,
        "ref_put": 0, "ref_get": 0, "ref_del": 0, "ref_list": 0,
        "share_create": 0, "share_resolve": 0,
        "gc_run": 0,
    }

    # ---------- write endpoints (require auth) ----------
    @app.put("/blobs", dependencies=[Depends(require_auth)])
    async def put_blob(file: UploadFile = File(...)):
        counters["blob_put"] += 1
        h = fs.put_blob(await file.read())
        return {"hash": h}

    @app.put("/refs/{path:path}", dependencies=[Depends(require_auth)])
    async def put_ref(path: str, file: UploadFile = File(...)):
        counters["ref_put"] += 1
        h, created = fs.put_ref(path, await file.read())
        return {"path": path, "hash": h, "created": created}

    @app.delete("/refs/{path:path}", dependencies=[Depends(require_auth)])
    def delete_ref(path: str):
        counters["ref_del"] += 1
        if not fs.delete_ref(path):
            raise HTTPException(404, "ref not found")
        return {"deleted": path}

    @app.post("/shares", dependencies=[Depends(require_auth)])
    def create_share(ref_path: str = Form(...), ttl_seconds: Optional[int] = Form(None)):
        counters["share_create"] += 1
        try:
            token = fs.create_share(ref_path, ttl_seconds)
        except KeyError:
            raise HTTPException(404, "ref not found")
        return {"token": token, "url": f"/shares/{token}"}

    @app.post("/gc", dependencies=[Depends(require_auth)])
    def gc():
        counters["gc_run"] += 1
        return {"removed": fs.gc()}

    # ---------- read endpoints (optional auth) ----------
    @app.get("/blobs/{hash_hex}")
    def get_blob(hash_hex: str, _: object = Depends(maybe_require_auth)):
        counters["blob_get"] += 1
        try:
            return Response(fs.get_blob(hash_hex), media_type="application/octet-stream")
        except FileNotFoundError:
            raise HTTPException(404, "blob not found")

    @app.get("/refs/{path:path}")
    def get_ref(path: str, _: object = Depends(maybe_require_auth)):
        counters["ref_get"] += 1
        data = fs.resolve_ref(path)
        if data is None:
            raise HTTPException(404, "ref not found")
        return Response(data, media_type="application/octet-stream")

    @app.get("/refs")
    def list_refs(prefix: str = "", _: object = Depends(maybe_require_auth)):
        counters["ref_list"] += 1
        return [
            {"path": r.path, "hash": r.hash, "updated_at": r.updated_at.isoformat()}
            for r in fs.list_refs(prefix)
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
