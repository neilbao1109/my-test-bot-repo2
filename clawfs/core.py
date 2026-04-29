"""ClawFS core: glue between Storage backend and SQLModel metadata.

Multi-tenant since Sprint 4. Every public method accepts a ``tenant_id``
(default ``"default"`` for back-compat). Refs are scoped per tenant by
prefixing the storage path with ``<tenant_id>/``. Blobs themselves are
content-addressed and shared across tenants (sha256 of the *bytes* — two
tenants uploading the same file dedup on disk), but each tenant gets its own
ref + refcount semantics, so deleting one tenant's ref never frees a blob
another tenant still references.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlmodel import Session, select

from .db import Blob, Ref, Share, Tenant, TenantBlob, QuotaExceeded, make_engine
from .storage import LocalStorage, Storage

DEFAULT_TENANT = "default"


def _tpath(tenant_id: str, path: str) -> str:
    return f"{tenant_id}/{path}"


def _untpath(tenant_id: str, stored: str) -> str:
    prefix = f"{tenant_id}/"
    return stored[len(prefix):] if stored.startswith(prefix) else stored


class ClawFS:
    def __init__(self, storage: Storage, db_url: str = "sqlite:///clawfs.db"):
        self.storage = storage
        self.engine = make_engine(db_url)

    @classmethod
    def local(cls, root: str) -> "ClawFS":
        import os
        os.makedirs(root, exist_ok=True)
        return cls(LocalStorage(root), db_url=f"sqlite:///{root}/clawfs.db")

    # ---------- blobs (shared across tenants by content hash) ----------
    def put_blob(self, data: bytes, tenant_id: str = DEFAULT_TENANT) -> str:
        h = hashlib.sha256(data).hexdigest()
        size = len(data)
        with Session(self.engine) as s:
            self._enforce_quota(s, tenant_id, h, size)
            existing = s.get(Blob, h)
            if existing is None:
                self.storage.put(h, data)
                s.add(Blob(hash=h, size=size, refcount=0, tenant_id=tenant_id))
            elif not self.storage.exists(h):
                self.storage.put(h, data)
            self._link_inc(s, tenant_id, h, size)
            s.commit()
        return h

    def get_blob(self, hash_hex: str, tenant_id: str = DEFAULT_TENANT) -> bytes:
        # Blobs are content-addressed → any tenant can fetch by hash they know.
        # Privacy is enforced through refs (you can't list refs you don't own),
        # not through guessing 256-bit hashes.
        return self.storage.get(hash_hex)

    # ---------- refs (per-tenant namespace) ----------
    def put_ref(self, path: str, data: bytes, tenant_id: str = DEFAULT_TENANT) -> Tuple[str, bool]:
        h = self.put_blob(data, tenant_id=tenant_id)
        stored = _tpath(tenant_id, path)
        with Session(self.engine) as s:
            ref = s.get(Ref, stored)
            created = False
            if ref is None:
                ref = Ref(path=stored, hash=h, tenant_id=tenant_id)
                s.add(ref)
                self._bump(s, h, +1)
                created = True
            elif ref.hash != h:
                old = ref.hash
                ref.hash = h
                ref.updated_at = datetime.utcnow()
                self._bump(s, old, -1)
                self._bump(s, h, +1)
                # rebind link: dec old, inc new (size of new blob)
                self._link_dec(s, tenant_id, old)
                new_blob = s.get(Blob, h)
                if new_blob is not None:
                    self._link_inc(s, tenant_id, h, new_blob.size)
            s.commit()
        return h, created

    def resolve_ref(self, path: str, tenant_id: str = DEFAULT_TENANT) -> Optional[bytes]:
        with Session(self.engine) as s:
            ref = s.get(Ref, _tpath(tenant_id, path))
            if ref is None:
                return None
            return self.storage.get(ref.hash)

    def list_refs(self, prefix: str = "", tenant_id: str = DEFAULT_TENANT) -> List[Ref]:
        with Session(self.engine) as s:
            stmt = select(Ref).where(Ref.tenant_id == tenant_id)
            if prefix:
                stmt = stmt.where(Ref.path.startswith(_tpath(tenant_id, prefix)))
            rows = list(s.exec(stmt))
            # Strip the tenant prefix in the returned objects so callers see
            # the user-facing path.
            for r in rows:
                r.path = _untpath(tenant_id, r.path)
            return rows

    def delete_ref(self, path: str, tenant_id: str = DEFAULT_TENANT) -> bool:
        stored = _tpath(tenant_id, path)
        with Session(self.engine) as s:
            ref = s.get(Ref, stored)
            if ref is None:
                return False
            self._bump(s, ref.hash, -1)
            self._link_dec(s, tenant_id, ref.hash)
            s.delete(ref)
            for sh in s.exec(select(Share).where(Share.ref_path == stored)):
                s.delete(sh)
            s.commit()
        return True

    def _bump(self, s: Session, h: str, delta: int) -> None:
        b = s.get(Blob, h)
        if b is None:
            return
        b.refcount = max(0, b.refcount + delta)
        s.add(b)

    # ---------- per-tenant quota accounting ----------
    def _enforce_quota(self, s: Session, tenant_id: str, h: str, size: int) -> None:
        """Raise QuotaExceeded if a put_blob of (h, size) would push tenant
        past its limits. No-op for synthetic 'default' tenant (no Tenant row).
        """
        t = s.get(Tenant, tenant_id)
        if t is None:
            return  # legacy / single-tenant deployment, no quota enforced
        # If this exact (tenant, hash) link already exists we'd not consume
        # extra bytes, so it's always allowed.
        link = s.get(TenantBlob, (tenant_id, h))
        if link is not None:
            return
        if t.max_bytes is not None and t.used_bytes + size > t.max_bytes:
            raise QuotaExceeded("bytes", t.used_bytes + size, t.max_bytes)
        if t.max_objects is not None and t.used_objects + 1 > t.max_objects:
            raise QuotaExceeded("objects", t.used_objects + 1, t.max_objects)

    def _link_inc(self, s: Session, tenant_id: str, h: str, size: int) -> None:
        link = s.get(TenantBlob, (tenant_id, h))
        t = s.get(Tenant, tenant_id)
        if link is None:
            link = TenantBlob(tenant_id=tenant_id, hash=h, refcount=1, size=size)
            s.add(link)
            if t is not None:
                t.used_bytes += size
                t.used_objects += 1
                s.add(t)
        else:
            link.refcount += 1
            s.add(link)

    def _link_dec(self, s: Session, tenant_id: str, h: str) -> None:
        link = s.get(TenantBlob, (tenant_id, h))
        if link is None:
            return
        link.refcount -= 1
        if link.refcount <= 0:
            t = s.get(Tenant, tenant_id)
            if t is not None:
                t.used_bytes = max(0, t.used_bytes - link.size)
                t.used_objects = max(0, t.used_objects - 1)
                s.add(t)
            s.delete(link)
        else:
            s.add(link)

    def get_usage(self, tenant_id: str) -> dict:
        with Session(self.engine) as s:
            t = s.get(Tenant, tenant_id)
            if t is None:
                return {
                    "tenant_id": tenant_id,
                    "used_bytes": 0, "used_objects": 0,
                    "max_bytes": None, "max_objects": None,
                    "unmanaged": True,
                }
            return {
                "tenant_id": tenant_id,
                "used_bytes": t.used_bytes,
                "used_objects": t.used_objects,
                "max_bytes": t.max_bytes,
                "max_objects": t.max_objects,
                "unmanaged": False,
            }

    # ---------- gc ----------
    def gc(self, tenant_id: Optional[str] = None) -> int:
        """Drop blobs with refcount==0. ``tenant_id=None`` GCs everything
        (admin / single-tenant deployments). Pass a tenant id to scope GC to
        blobs originally created by that tenant only.
        """
        removed = 0
        with Session(self.engine) as s:
            stmt = select(Blob).where(Blob.refcount == 0)
            if tenant_id is not None:
                stmt = stmt.where(Blob.tenant_id == tenant_id)
            for b in list(s.exec(stmt)):
                self.storage.delete(b.hash)
                s.delete(b)
                removed += 1
            s.commit()
        return removed

    # ---------- shares ----------
    def create_share(
        self,
        ref_path: str,
        ttl_seconds: Optional[int] = None,
        tenant_id: str = DEFAULT_TENANT,
    ) -> str:
        stored = _tpath(tenant_id, ref_path)
        with Session(self.engine) as s:
            if s.get(Ref, stored) is None:
                raise KeyError(f"no such ref: {ref_path}")
            token = secrets.token_urlsafe(24)
            expires = datetime.utcnow() + timedelta(seconds=ttl_seconds) if ttl_seconds else None
            s.add(Share(token=token, ref_path=stored, expires_at=expires))
            s.commit()
            return token

    def resolve_share(self, token: str) -> Optional[bytes]:
        with Session(self.engine) as s:
            sh = s.get(Share, token)
            if sh is None:
                return None
            if sh.expires_at and sh.expires_at < datetime.utcnow():
                return None
            ref = s.get(Ref, sh.ref_path)
            if ref is None:
                return None
            return self.storage.get(ref.hash)

    # ---------- tenants ----------
    def upsert_tenant(
        self,
        tenant_id: str,
        name: str = "",
        tokens: Optional[List[str]] = None,
        max_bytes: Optional[int] = None,
        max_objects: Optional[int] = None,
    ) -> Tenant:
        with Session(self.engine) as s:
            t = s.get(Tenant, tenant_id)
            if t is None:
                t = Tenant(id=tenant_id, name=name)
            if name:
                t.name = name
            if tokens is not None:
                t.tokens_csv = ",".join(t.strip() for t in tokens if t.strip())
            if max_bytes is not None:
                t.max_bytes = max_bytes
            if max_objects is not None:
                t.max_objects = max_objects
            s.add(t)
            s.commit()
            s.refresh(t)
            return t

    def tenant_for_token(self, token: str) -> Optional[str]:
        with Session(self.engine) as s:
            for t in s.exec(select(Tenant)):
                if not t.tokens_csv:
                    continue
                if token in {x.strip() for x in t.tokens_csv.split(",") if x.strip()}:
                    return t.id
        return None
