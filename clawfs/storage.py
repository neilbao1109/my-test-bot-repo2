"""Storage backends: pluggable blob persistence layer.

v1: LocalStorage (git-style sharded objects/ tree on disk).
v2: AzureBlobStorage (stub interface; flip a flag, ship to cloud).
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class Storage(ABC):
    """Abstract content-addressed blob store keyed by sha256 hex."""

    @abstractmethod
    def put(self, hash_hex: str, data: bytes) -> None: ...

    @abstractmethod
    def get(self, hash_hex: str) -> bytes: ...

    @abstractmethod
    def exists(self, hash_hex: str) -> bool: ...

    @abstractmethod
    def delete(self, hash_hex: str) -> None: ...


class LocalStorage(Storage):
    """Disk-backed blob store. Layout: <root>/objects/<aa>/<rest>."""

    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)

    def _path(self, hash_hex: str) -> Path:
        return self.objects / hash_hex[:2] / hash_hex[2:]

    def put(self, hash_hex: str, data: bytes) -> None:
        p = self._path(hash_hex)
        if p.exists():
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)

    def get(self, hash_hex: str) -> bytes:
        p = self._path(hash_hex)
        if not p.exists():
            raise FileNotFoundError(f"blob {hash_hex} not found")
        return p.read_bytes()

    def exists(self, hash_hex: str) -> bool:
        return self._path(hash_hex).exists()

    def delete(self, hash_hex: str) -> None:
        p = self._path(hash_hex)
        if p.exists():
            p.unlink()
            # best-effort prune empty shard dir
            try:
                p.parent.rmdir()
            except OSError:
                pass


class AzureBlobStorage(Storage):
    """Stub: Azure Blob Storage backend for v2.

    Wire-up uses azure-storage-blob's BlobServiceClient. Container holds one
    blob per hash (flat namespace; sharding optional via blob name prefix).
    """

    def __init__(self, account_url: str, container: str, credential=None):
        self.account_url = account_url
        self.container = container
        self.credential = credential
        self._client = None  # lazy

    def _client_lazy(self):
        if self._client is None:
            from azure.storage.blob import BlobServiceClient  # type: ignore
            svc = BlobServiceClient(self.account_url, credential=self.credential)
            self._client = svc.get_container_client(self.container)
        return self._client

    def _name(self, hash_hex: str) -> str:
        return f"{hash_hex[:2]}/{hash_hex[2:]}"

    def put(self, hash_hex: str, data: bytes) -> None:
        c = self._client_lazy()
        if not self.exists(hash_hex):
            c.upload_blob(self._name(hash_hex), data, overwrite=False)

    def get(self, hash_hex: str) -> bytes:
        c = self._client_lazy()
        return c.download_blob(self._name(hash_hex)).readall()

    def exists(self, hash_hex: str) -> bool:
        c = self._client_lazy()
        return c.get_blob_client(self._name(hash_hex)).exists()

    def delete(self, hash_hex: str) -> None:
        c = self._client_lazy()
        try:
            c.delete_blob(self._name(hash_hex))
        except Exception:
            pass
