"""Unit tests for GCSStorage backend (mocked google-cloud-storage)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from clawfs.storage import GCSStorage, _name


def make_backend() -> tuple[GCSStorage, MagicMock, MagicMock]:
    fake_bucket = MagicMock()
    fake_client = MagicMock()
    fake_client.bucket.return_value = fake_bucket
    backend = GCSStorage(bucket="my-bucket", client=fake_client)
    return backend, fake_bucket, fake_client


def test_put_skips_when_exists():
    backend, bucket, _ = make_backend()
    blob = MagicMock()
    blob.exists.return_value = True
    bucket.blob.return_value = blob
    backend.put("a" * 64, b"data")
    blob.upload_from_string.assert_not_called()


def test_put_uploads_when_missing():
    backend, bucket, _ = make_backend()
    head_blob = MagicMock()
    head_blob.exists.return_value = False
    upload_blob = MagicMock()
    bucket.blob.side_effect = [head_blob, upload_blob]
    backend.put("b" * 64, b"hello")
    upload_blob.upload_from_string.assert_called_once_with(b"hello")


def test_get_returns_bytes():
    backend, bucket, _ = make_backend()
    blob = MagicMock()
    blob.download_as_bytes.return_value = b"payload"
    bucket.blob.return_value = blob
    assert backend.get("c" * 64) == b"payload"


def test_get_missing_raises_filenotfound():
    from google.cloud.exceptions import NotFound

    backend, bucket, _ = make_backend()
    blob = MagicMock()
    blob.download_as_bytes.side_effect = NotFound("nope")
    bucket.blob.return_value = blob
    with pytest.raises(FileNotFoundError):
        backend.get("d" * 64)


def test_iter_hashes():
    backend, bucket, _ = make_backend()
    b1 = MagicMock()
    b1.name = "objects/aa/" + "1" * 62
    b2 = MagicMock()
    b2.name = "objects/bb/" + "2" * 62
    bucket.list_blobs.return_value = [b1, b2]
    assert list(backend.iter_hashes()) == ["aa" + "1" * 62, "bb" + "2" * 62]


def test_requires_bucket(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CLAWFS_GCS_BUCKET", raising=False)
    with pytest.raises(ValueError):
        GCSStorage()


def test_uses_blob_path_naming():
    backend, bucket, _ = make_backend()
    blob = MagicMock()
    blob.exists.return_value = False
    bucket.blob.return_value = blob
    assert backend.exists("e" * 64) is False
    bucket.blob.assert_called_with(_name("e" * 64))
