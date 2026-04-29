"""SQLModel schema for ClawFS metadata."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine


class QuotaExceeded(Exception):
    """Raised when a write would push a tenant past its quota."""
    def __init__(self, kind: str, used: int, limit: int):
        super().__init__(f"tenant quota exceeded ({kind}): used={used} limit={limit}")
        self.kind = kind
        self.used = used
        self.limit = limit


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
    # Sprint 6 P2: per-tenant rate limit (req/min). NULL = unlimited.
    rate_limit_per_minute: Optional[int] = None
    # Sprint 6 P2: if True, reset usage counters at UTC midnight (demo tenant).
    daily_reset: bool = False
    last_reset_at: Optional[datetime] = None


class TenantBlob(SQLModel, table=True):
    """(tenant_id, blob_hash) link with refcount, so quota accounting
    counts each blob once per tenant regardless of how many refs point at it.

    Without this we'd either over-count (sum of ref bytes) or under-count
    (just sum the global blob table). With this, deletes also know exactly
    when to decrement a tenant's used_bytes.
    """
    tenant_id: str = Field(primary_key=True)
    hash: str = Field(primary_key=True)
    refcount: int = 0
    size: int = 0  # cached for fast quota math when removing


def make_engine(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    SQLModel.metadata.create_all(engine)
    _migrate(engine)
    return engine


def _migrate(engine) -> None:
    """Tiny additive migration shim for SQLite.

    SQLModel/SQLAlchemy ``create_all`` only creates missing tables, never adds
    columns to existing ones. We use it because Sprint 4 added ``tenant_id``
    columns to ``blob`` and ``ref`` and a new ``upload``/``tenant`` table; an
    in-place upgrade from a 0.2.x DB would otherwise crash at first query.
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "blob" not in insp.get_table_names():
        return  # fresh DB, create_all already covers it

    def cols(table: str) -> set[str]:
        return {c["name"] for c in insp.get_columns(table)}

    additions: list[tuple[str, str]] = []
    if "tenant_id" not in cols("blob"):
        additions.append(("blob", "tenant_id VARCHAR DEFAULT 'default' NOT NULL"))
    if "tenant_id" not in cols("ref"):
        additions.append(("ref", "tenant_id VARCHAR DEFAULT 'default' NOT NULL"))
    # Sprint 6 P2: rate-limit + daily reset columns on tenant table.
    if "tenant" in insp.get_table_names():
        tcols = cols("tenant")
        if "rate_limit_per_minute" not in tcols:
            additions.append(("tenant", "rate_limit_per_minute INTEGER"))
        if "daily_reset" not in tcols:
            additions.append(("tenant", "daily_reset BOOLEAN DEFAULT 0 NOT NULL"))
        if "last_reset_at" not in tcols:
            additions.append(("tenant", "last_reset_at DATETIME"))

    if not additions:
        return
    with engine.begin() as conn:
        for table, ddl in additions:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
        # Existing refs were stored without a tenant prefix; rewrite their
        # path so the multi-tenant code path can resolve them as 'default/...'.
        # Only run if we just added the ref.tenant_id column (legacy upgrade).
        if any(t == "ref" and "tenant_id" in ddl for t, ddl in additions):
            conn.execute(
                text("UPDATE ref SET path = 'default/' || path WHERE path NOT LIKE 'default/%'")
            )
