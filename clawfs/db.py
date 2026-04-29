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


class Ref(SQLModel, table=True):
    path: str = Field(primary_key=True)
    hash: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Share(SQLModel, table=True):
    token: str = Field(primary_key=True)
    ref_path: str = Field(index=True)
    expires_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


def make_engine(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    SQLModel.metadata.create_all(engine)
    return engine
