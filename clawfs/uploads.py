"""Multipart / chunked upload manager.

Streams parts directly to disk so very large files (multi-GB) don't OOM the
process. Each upload session has its own scratch dir under ``<root>/uploads/<id>``.
On ``complete`` we hash the concatenation streaming and hand the final file
to the storage backend via :meth:`Storage.put_path`.

Wire shape (S3-style multipart):

    POST   /uploads                 -> {id, expires_at}
    PUT    /uploads/{id}/parts/{n}  (raw body) -> {n, size, etag}
    POST   /uploads/{id}/complete   -> {hash, size, ref?}
    DELETE /uploads/{id}            -> {deleted: true}
"""
from __future__ import annotations

import hashlib
import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Iterable, Optional

from sqlmodel import Session

from .db import Blob, Ref, Upload, QuotaExceeded
from .storage import Storage

PART_FILE_RE = ("part",)


@dataclass
class CompletedUpload:
    hash: str
    size: int
    created: bool


class UploadManager:
    """Owns the on-disk scratch dirs for in-progress multipart uploads."""

    def __init__(self, scratch_root: str | os.PathLike, storage: Storage, engine):
        self.scratch_root = Path(scratch_root)
        self.scratch_root.mkdir(parents=True, exist_ok=True)
        self.storage = storage
        self.engine = engine

    # ---------- session lifecycle ----------
    def create(self, tenant_id: str = "default", target_ref: Optional[str] = None) -> str:
        upload_id = secrets.token_urlsafe(18)
        (self.scratch_root / upload_id).mkdir(parents=True, exist_ok=False)
        with Session(self.engine) as s:
            s.add(Upload(id=upload_id, tenant_id=tenant_id, target_ref=target_ref))
            s.commit()
        return upload_id

    def abort(self, upload_id: str) -> bool:
        with Session(self.engine) as s:
            up = s.get(Upload, upload_id)
            if up is None:
                return False
            s.delete(up)
            s.commit()
        shutil.rmtree(self.scratch_root / upload_id, ignore_errors=True)
        return True

    # ---------- parts ----------
    async def write_part(
        self,
        upload_id: str,
        part_number: int,
        chunks: AsyncIterator[bytes],
    ) -> tuple[int, str]:
        """Stream ``chunks`` into ``<scratch>/<upload_id>/<n>.part``.

        Returns (size, etag) where etag is sha256 of the part. Never reads
        the whole part into memory.
        """
        if part_number < 1:
            raise ValueError("part_number must be >= 1")
        with Session(self.engine) as s:
            up = s.get(Upload, upload_id)
            if up is None or up.completed:
                raise FileNotFoundError("upload not found or already completed")
        dst = self.scratch_root / upload_id / f"{part_number:08d}.part"
        dst.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        size = 0
        with open(dst, "wb") as f:
            async for chunk in chunks:
                if not chunk:
                    continue
                f.write(chunk)
                h.update(chunk)
                size += len(chunk)
        return size, h.hexdigest()

    def write_part_sync(self, upload_id: str, part_number: int, data: bytes) -> tuple[int, str]:
        """Synchronous helper for in-process / test usage."""
        dst = self.scratch_root / upload_id / f"{part_number:08d}.part"
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "wb") as f:
            f.write(data)
        return len(data), hashlib.sha256(data).hexdigest()

    # ---------- finalization ----------
    def complete(
        self,
        upload_id: str,
        expected_parts: Optional[Iterable[int]] = None,
    ) -> CompletedUpload:
        with Session(self.engine) as s:
            up = s.get(Upload, upload_id)
            if up is None:
                raise FileNotFoundError("upload not found")
            if up.completed:
                raise ValueError("upload already completed")

        scratch = self.scratch_root / upload_id
        parts = sorted(p for p in scratch.iterdir() if p.suffix == ".part")
        if not parts:
            raise ValueError("no parts uploaded")

        if expected_parts is not None:
            got = {int(p.stem) for p in parts}
            want = set(expected_parts)
            if got != want:
                raise ValueError(
                    f"part mismatch: got={sorted(got)} expected={sorted(want)}"
                )

        # Concat into a single tmp file while hashing streaming.
        merged = scratch / "merged.bin"
        h = hashlib.sha256()
        size = 0
        BUF = 1024 * 1024
        with open(merged, "wb") as out:
            for p in parts:
                with open(p, "rb") as f:
                    while True:
                        chunk = f.read(BUF)
                        if not chunk:
                            break
                        out.write(chunk)
                        h.update(chunk)
                        size += len(chunk)
        final_hash = h.hexdigest()

        with Session(self.engine) as s:
            up = s.get(Upload, upload_id)
            tenant_id = up.tenant_id if up else "default"
            target_ref = up.target_ref if up else None

            # quota check (mirrors ClawFS._enforce_quota)
            from .db import Tenant, TenantBlob
            t = s.get(Tenant, tenant_id)
            link = s.get(TenantBlob, (tenant_id, final_hash))

            def _cleanup_scratch():
                for p in parts:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
                try:
                    os.unlink(merged)
                except OSError:
                    pass
                try:
                    scratch.rmdir()
                except OSError:
                    pass

            if t is not None and link is None:
                if t.max_bytes is not None and t.used_bytes + size > t.max_bytes:
                    _cleanup_scratch()
                    raise QuotaExceeded("bytes", t.used_bytes + size, t.max_bytes)
                if t.max_objects is not None and t.used_objects + 1 > t.max_objects:
                    _cleanup_scratch()
                    raise QuotaExceeded("objects", t.used_objects + 1, t.max_objects)

            existing = s.get(Blob, final_hash)
            created = existing is None
            if created:
                self.storage.put_path(final_hash, str(merged))
                s.add(Blob(hash=final_hash, size=size, refcount=0, tenant_id=tenant_id))
            else:
                # already have it; drop the staged file
                try:
                    os.unlink(merged)
                except OSError:
                    pass

            # link tenant↔blob for quota accounting
            if link is None:
                s.add(TenantBlob(tenant_id=tenant_id, hash=final_hash, refcount=1, size=size))
                if t is not None:
                    t.used_bytes += size
                    t.used_objects += 1
                    s.add(t)
            else:
                link.refcount += 1
                s.add(link)

            if target_ref:
                tenanted_path = f"{tenant_id}/{target_ref}"
                ref = s.get(Ref, tenanted_path)
                if ref is None:
                    s.add(Ref(path=tenanted_path, hash=final_hash, tenant_id=tenant_id))
                    b = s.get(Blob, final_hash)
                    if b:
                        b.refcount += 1
                        s.add(b)
                elif ref.hash != final_hash:
                    old = ref.hash
                    ref.hash = final_hash
                    s.add(ref)
                    if (ob := s.get(Blob, old)) is not None:
                        ob.refcount = max(0, ob.refcount - 1)
                        s.add(ob)
                    if (nb := s.get(Blob, final_hash)) is not None:
                        nb.refcount += 1
                        s.add(nb)

            up = s.get(Upload, upload_id)
            if up:
                up.completed = True
                up.final_hash = final_hash
                s.add(up)
            s.commit()

        # cleanup parts but keep the Upload row as a receipt
        for p in parts:
            try:
                os.unlink(p)
            except OSError:
                pass
        try:
            os.unlink(merged)
        except OSError:
            pass
        try:
            scratch.rmdir()
        except OSError:
            pass

        return CompletedUpload(hash=final_hash, size=size, created=created)
