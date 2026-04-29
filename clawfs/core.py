"""ClawFS core: glue between Storage backend and SQLModel metadata."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlmodel import Session, select

from .db import Blob, Ref, Share, make_engine
from .storage import LocalStorage, Storage


class ClawFS:
    def __init__(self, storage: Storage, db_url: str = "sqlite:///clawfs.db"):
        self.storage = storage
        self.engine = make_engine(db_url)

    @classmethod
    def local(cls, root: str) -> "ClawFS":
        import os
        os.makedirs(root, exist_ok=True)
        return cls(LocalStorage(root), db_url=f"sqlite:///{root}/clawfs.db")

    # ---------- blobs ----------
    def put_blob(self, data: bytes) -> str:
        h = hashlib.sha256(data).hexdigest()
        with Session(self.engine) as s:
            existing = s.get(Blob, h)
            if existing is None:
                self.storage.put(h, data)
                s.add(Blob(hash=h, size=len(data), refcount=0))
                s.commit()
            elif not self.storage.exists(h):
                # heal: blob row present but file missing
                self.storage.put(h, data)
        return h

    def get_blob(self, hash_hex: str) -> bytes:
        return self.storage.get(hash_hex)

    # ---------- refs (paths) ----------
    def put_ref(self, path: str, data: bytes) -> Tuple[str, bool]:
        """Bind path → sha256(data). Returns (hash, created_new_ref)."""
        h = self.put_blob(data)
        with Session(self.engine) as s:
            ref = s.get(Ref, path)
            created = False
            if ref is None:
                ref = Ref(path=path, hash=h)
                s.add(ref)
                self._bump(s, h, +1)
                created = True
            elif ref.hash != h:
                old = ref.hash
                ref.hash = h
                ref.updated_at = datetime.utcnow()
                self._bump(s, old, -1)
                self._bump(s, h, +1)
            s.commit()
        return h, created

    def resolve_ref(self, path: str) -> Optional[bytes]:
        with Session(self.engine) as s:
            ref = s.get(Ref, path)
            if ref is None:
                return None
            return self.storage.get(ref.hash)

    def list_refs(self, prefix: str = "") -> List[Ref]:
        with Session(self.engine) as s:
            stmt = select(Ref)
            if prefix:
                stmt = stmt.where(Ref.path.startswith(prefix))
            return list(s.exec(stmt))

    def delete_ref(self, path: str) -> bool:
        with Session(self.engine) as s:
            ref = s.get(Ref, path)
            if ref is None:
                return False
            self._bump(s, ref.hash, -1)
            s.delete(ref)
            # cascade: kill shares pointing at this ref
            for sh in s.exec(select(Share).where(Share.ref_path == path)):
                s.delete(sh)
            s.commit()
        return True

    def _bump(self, s: Session, h: str, delta: int) -> None:
        b = s.get(Blob, h)
        if b is None:
            return
        b.refcount = max(0, b.refcount + delta)
        s.add(b)

    # ---------- gc ----------
    def gc(self) -> int:
        """Drop blobs with refcount==0. Returns count removed."""
        removed = 0
        with Session(self.engine) as s:
            for b in list(s.exec(select(Blob).where(Blob.refcount == 0))):
                self.storage.delete(b.hash)
                s.delete(b)
                removed += 1
            s.commit()
        return removed

    # ---------- shares ----------
    def create_share(self, ref_path: str, ttl_seconds: Optional[int] = None) -> str:
        with Session(self.engine) as s:
            if s.get(Ref, ref_path) is None:
                raise KeyError(f"no such ref: {ref_path}")
            token = secrets.token_urlsafe(24)
            expires = datetime.utcnow() + timedelta(seconds=ttl_seconds) if ttl_seconds else None
            s.add(Share(token=token, ref_path=ref_path, expires_at=expires))
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
