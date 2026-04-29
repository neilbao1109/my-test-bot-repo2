"""FastAPI surface for ClawFS — 8 endpoints."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import Response

from .core import ClawFS


def create_app(root: Optional[str] = None) -> FastAPI:
    root = root or os.environ.get("CLAWFS_ROOT", "./clawfs-data")
    fs = ClawFS.local(root)
    app = FastAPI(title="ClawFS", version="0.1.0")

    # 1. PUT blob (raw)
    @app.put("/blobs")
    async def put_blob(file: UploadFile = File(...)):
        h = fs.put_blob(await file.read())
        return {"hash": h}

    # 2. GET blob by hash
    @app.get("/blobs/{hash_hex}")
    def get_blob(hash_hex: str):
        try:
            return Response(fs.get_blob(hash_hex), media_type="application/octet-stream")
        except FileNotFoundError:
            raise HTTPException(404, "blob not found")

    # 3. PUT ref (path → content)
    @app.put("/refs/{path:path}")
    async def put_ref(path: str, file: UploadFile = File(...)):
        h, created = fs.put_ref(path, await file.read())
        return {"path": path, "hash": h, "created": created}

    # 4. GET ref content
    @app.get("/refs/{path:path}")
    def get_ref(path: str):
        data = fs.resolve_ref(path)
        if data is None:
            raise HTTPException(404, "ref not found")
        return Response(data, media_type="application/octet-stream")

    # 5. LIST refs
    @app.get("/refs")
    def list_refs(prefix: str = ""):
        return [{"path": r.path, "hash": r.hash, "updated_at": r.updated_at.isoformat()} for r in fs.list_refs(prefix)]

    # 6. DELETE ref
    @app.delete("/refs/{path:path}")
    def delete_ref(path: str):
        ok = fs.delete_ref(path)
        if not ok:
            raise HTTPException(404, "ref not found")
        return {"deleted": path}

    # 7. CREATE share
    @app.post("/shares")
    def create_share(ref_path: str = Form(...), ttl_seconds: Optional[int] = Form(None)):
        try:
            token = fs.create_share(ref_path, ttl_seconds)
        except KeyError:
            raise HTTPException(404, "ref not found")
        return {"token": token, "url": f"/shares/{token}"}

    # 8. RESOLVE share
    @app.get("/shares/{token}")
    def resolve_share(token: str):
        data = fs.resolve_share(token)
        if data is None:
            raise HTTPException(404, "share not found or expired")
        return Response(data, media_type="application/octet-stream")

    # bonus: GC trigger (admin)
    @app.post("/gc")
    def gc():
        return {"removed": fs.gc()}

    return app


app = create_app()
