"""SQLModel schema for ClawFS metadata."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine


class Blob(SQLModel, table=True):
    hash: str = Field(primary_key=True)
    size: int
    refcount: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    tenant_id: str = Field(default="default", index=True)


class Ref(SQLModel, table=True):
    # Composite key: tenant + path. We model it as path-with-tenant-prefix
    # to keep the existing single-PK shape; tenant_id is also indexed for
    # efficient list/filter.
    path: str = Field(primary_key=True)  # storage form: "<tenant>/<user-path>"
    hash: str = Field(index=True)
    tenant_id: str = Field(default="default", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Share(SQLModel, table=True):
    token: str = Field(primary_key=True)
    ref_path: str = Field(index=True)
    expires_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Upload(SQLModel, table=True):
    """In-progress multipart upload session.

    The actual part bytes are streamed to a tmp directory on disk
    (`<root>/uploads/<id>/<n>.part`) until ``complete`` is called, at which
    point they're concatenated, hashed, and handed to the storage backend.
    """
    id: str = Field(primary_key=True)
    tenant_id: str = Field(default="default", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed: bool = False
    final_hash: Optional[str] = None
    target_ref: Optional[str] = None  # if set, completing also binds the ref


class Tenant(SQLModel, table=True):
    """Tenant record. tokens (CSV) authenticate as this tenant."""
    id: str = Field(primary_key=True)
    name: str = ""
    tokens_csv: str = ""  # comma-separated bearer tokens
    max_bytes: Optional[int] = None
    max_objects: Optional[int] = None
    used_bytes: int = 0
    used_objects: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


def make_engine(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    SQLModel.metadata.create_all(engine)
    return engine
