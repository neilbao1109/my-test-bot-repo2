"""Storage backends: pluggable blob persistence layer.

- LocalStorage: git-style sharded objects/ tree on disk.
- AzureBlobStorage: Azure Blob backed (requires the `[azure]` extra).
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator, Optional


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

    @abstractmethod
    def iter_hashes(self) -> Iterator[str]: ...


def _name(hash_hex: str) -> str:
    """Shared blob naming: objects/<aa>/<rest>."""
    return f"objects/{hash_hex[:2]}/{hash_hex[2:]}"


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
            try:
                p.parent.rmdir()
            except OSError:
                pass

    def iter_hashes(self) -> Iterator[str]:
        if not self.objects.exists():
            return
        for shard in self.objects.iterdir():
            if not shard.is_dir() or len(shard.name) != 2:
                continue
            for blob in shard.iterdir():
                if blob.is_file() and not blob.name.endswith(".tmp"):
                    yield shard.name + blob.name


class AzureBlobStorage(Storage):
    """Azure Blob Storage backend.

    Reads connection string from `AZURE_STORAGE_CONNECTION_STRING` and
    container name from `CLAWFS_AZURE_CONTAINER` by default. Either may be
    overridden via constructor args. The container is auto-created on first
    use if the credential allows it.

    Blob naming matches LocalStorage: `objects/<aa>/<rest>`.
    """

    def __init__(
        self,
        container: Optional[str] = None,
        connection_string: Optional[str] = None,
        account_url: Optional[str] = None,
        credential=None,
    ):
        self.container = container or os.environ.get("CLAWFS_AZURE_CONTAINER")
        if not self.container:
            raise ValueError(
                "AzureBlobStorage requires container (arg or CLAWFS_AZURE_CONTAINER env)"
            )
        self.connection_string = connection_string or os.environ.get(
            "AZURE_STORAGE_CONNECTION_STRING"
        )
        self.account_url = account_url or os.environ.get("CLAWFS_AZURE_ACCOUNT_URL")
        self.credential = credential
        if not self.connection_string and not self.account_url:
            raise ValueError(
                "AzureBlobStorage requires AZURE_STORAGE_CONNECTION_STRING or account_url"
            )
        self._client = None  # lazy ContainerClient

    def _client_lazy(self):
        if self._client is None:
            try:
                from azure.storage.blob import BlobServiceClient  # type: ignore
            except ImportError as e:  # pragma: no cover
                raise ImportError(
                    "azure-storage-blob not installed; pip install 'clawfs[azure]'"
                ) from e
            if self.connection_string:
                svc = BlobServiceClient.from_connection_string(self.connection_string)
            else:
                cred = self.credential
                if cred is None:
                    try:
                        from azure.identity import DefaultAzureCredential  # type: ignore
                        cred = DefaultAzureCredential()
                    except ImportError as e:  # pragma: no cover
                        raise ImportError(
                            "azure-identity not installed; pip install 'clawfs[azure]'"
                        ) from e
                svc = BlobServiceClient(self.account_url, credential=cred)
            cc = svc.get_container_client(self.container)
            try:
                cc.create_container()
            except Exception:
                pass  # already exists / no perms — fine
            self._client = cc
        return self._client

    def put(self, hash_hex: str, data: bytes) -> None:
        c = self._client_lazy()
        if self.exists(hash_hex):
            return
        c.upload_blob(_name(hash_hex), data, overwrite=False)

    def get(self, hash_hex: str) -> bytes:
        c = self._client_lazy()
        try:
            return c.download_blob(_name(hash_hex)).readall()
        except Exception as e:
            try:
                from azure.core.exceptions import ResourceNotFoundError  # type: ignore
                if isinstance(e, ResourceNotFoundError):
                    raise FileNotFoundError(f"blob {hash_hex} not found") from e
            except ImportError:
                pass
            raise

    def exists(self, hash_hex: str) -> bool:
        c = self._client_lazy()
        return c.get_blob_client(_name(hash_hex)).exists()

    def delete(self, hash_hex: str) -> None:
        c = self._client_lazy()
        try:
            c.delete_blob(_name(hash_hex))
        except Exception:
            pass

    def iter_hashes(self) -> Iterator[str]:
        c = self._client_lazy()
        prefix = "objects/"
        for blob in c.list_blobs(name_starts_with=prefix):
            name = blob.name[len(prefix):]
            # name is "<aa>/<rest>"
            parts = name.split("/", 1)
            if len(parts) == 2 and len(parts[0]) == 2:
                yield parts[0] + parts[1]


class S3Storage(Storage):
    """S3-compatible blob backend (AWS S3, MinIO, R2, Backblaze B2, ...).

    Reads bucket from `CLAWFS_S3_BUCKET`, optional endpoint from
    `CLAWFS_S3_ENDPOINT_URL` (set this for MinIO/R2/B2), region from
    `CLAWFS_S3_REGION` or `AWS_REGION`. Credentials follow the standard boto3
    chain (env vars, ~/.aws, IAM role, IRSA, etc.).

    Blob naming matches LocalStorage / AzureBlobStorage: ``objects/<aa>/<rest>``.
    """

    def __init__(
        self,
        bucket: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        region: Optional[str] = None,
        client=None,
    ):
        self.bucket = bucket or os.environ.get("CLAWFS_S3_BUCKET")
        if not self.bucket:
            raise ValueError(
                "S3Storage requires bucket (arg or CLAWFS_S3_BUCKET env)"
            )
        self.endpoint_url = endpoint_url or os.environ.get("CLAWFS_S3_ENDPOINT_URL")
        self.region = region or os.environ.get("CLAWFS_S3_REGION") or os.environ.get("AWS_REGION")
        self._client = client

    def _client_lazy(self):
        if self._client is None:
            try:
                import boto3  # type: ignore
            except ImportError as e:  # pragma: no cover
                raise ImportError(
                    "boto3 not installed; pip install 'clawfs[s3]'"
                ) from e
            kwargs = {}
            if self.endpoint_url:
                kwargs["endpoint_url"] = self.endpoint_url
            if self.region:
                kwargs["region_name"] = self.region
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def put(self, hash_hex: str, data: bytes) -> None:
        if self.exists(hash_hex):
            return
        self._client_lazy().put_object(Bucket=self.bucket, Key=_name(hash_hex), Body=data)

    def get(self, hash_hex: str) -> bytes:
        try:
            obj = self._client_lazy().get_object(Bucket=self.bucket, Key=_name(hash_hex))
            return obj["Body"].read()
        except Exception as e:
            try:
                from botocore.exceptions import ClientError  # type: ignore
                if isinstance(e, ClientError) and e.response.get("Error", {}).get("Code") in (
                    "NoSuchKey",
                    "404",
                    "NotFound",
                ):
                    raise FileNotFoundError(f"blob {hash_hex} not found") from e
            except ImportError:
                pass
            raise

    def exists(self, hash_hex: str) -> bool:
        try:
            self._client_lazy().head_object(Bucket=self.bucket, Key=_name(hash_hex))
            return True
        except Exception as e:
            try:
                from botocore.exceptions import ClientError  # type: ignore
                if isinstance(e, ClientError) and e.response.get("Error", {}).get("Code") in (
                    "404",
                    "NoSuchKey",
                    "NotFound",
                ):
                    return False
            except ImportError:
                pass
            raise

    def delete(self, hash_hex: str) -> None:
        try:
            self._client_lazy().delete_object(Bucket=self.bucket, Key=_name(hash_hex))
        except Exception:
            pass

    def iter_hashes(self) -> Iterator[str]:
        c = self._client_lazy()
        paginator = c.get_paginator("list_objects_v2")
        prefix = "objects/"
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []) or []:
                name = obj["Key"][len(prefix):]
                parts = name.split("/", 1)
                if len(parts) == 2 and len(parts[0]) == 2:
                    yield parts[0] + parts[1]
