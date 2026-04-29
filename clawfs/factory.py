"""Storage factory: pick backend from env."""
from __future__ import annotations

import os

from .storage import AzureBlobStorage, GCSStorage, LocalStorage, S3Storage, Storage


def make_storage(root: str | None = None) -> Storage:
    """Build a Storage based on `CLAWFS_BACKEND` env (default: local).

    - local: LocalStorage rooted at `root` or `CLAWFS_ROOT` or ./clawfs-data
    - azure: AzureBlobStorage from env (CLAWFS_AZURE_CONTAINER + creds)
    - s3:    S3Storage from env (CLAWFS_S3_BUCKET, CLAWFS_S3_ENDPOINT_URL?, region)
    - gcs:   GCSStorage from env (CLAWFS_GCS_BUCKET + ADC)
    """
    backend = os.environ.get("CLAWFS_BACKEND", "local").lower()
    if backend == "azure":
        return AzureBlobStorage()
    if backend == "s3":
        return S3Storage()
    if backend == "gcs":
        return GCSStorage()
    if backend == "local":
        r = root or os.environ.get("CLAWFS_ROOT", "./clawfs-data")
        os.makedirs(r, exist_ok=True)
        return LocalStorage(r)
    raise ValueError(f"unknown CLAWFS_BACKEND: {backend!r}")
