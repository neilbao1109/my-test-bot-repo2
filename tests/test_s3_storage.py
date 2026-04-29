"""Unit tests for S3Storage backend (mocked boto3)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from clawfs.storage import S3Storage, _name


def make_backend(monkeypatch: pytest.MonkeyPatch) -> tuple[S3Storage, MagicMock]:
    fake_client = MagicMock()
    backend = S3Storage(bucket="my-bucket", client=fake_client)
    return backend, fake_client


def test_put_skips_when_exists(monkeypatch: pytest.MonkeyPatch):
    backend, client = make_backend(monkeypatch)
    client.head_object.return_value = {}  # exists
    backend.put("a" * 64, b"data")
    client.put_object.assert_not_called()


def test_put_uploads_when_missing(monkeypatch: pytest.MonkeyPatch):
    from botocore.exceptions import ClientError

    backend, client = make_backend(monkeypatch)
    client.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")
    backend.put("b" * 64, b"hello")
    client.put_object.assert_called_once_with(
        Bucket="my-bucket", Key=_name("b" * 64), Body=b"hello"
    )


def test_get_returns_bytes(monkeypatch: pytest.MonkeyPatch):
    backend, client = make_backend(monkeypatch)
    body = MagicMock()
    body.read.return_value = b"payload"
    client.get_object.return_value = {"Body": body}
    assert backend.get("c" * 64) == b"payload"


def test_get_missing_raises_filenotfound(monkeypatch: pytest.MonkeyPatch):
    from botocore.exceptions import ClientError

    backend, client = make_backend(monkeypatch)
    client.get_object.side_effect = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
    with pytest.raises(FileNotFoundError):
        backend.get("d" * 64)


def test_iter_hashes_paginates(monkeypatch: pytest.MonkeyPatch):
    backend, client = make_backend(monkeypatch)
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "objects/aa/" + "1" * 62}, {"Key": "objects/bb/" + "2" * 62}]},
        {"Contents": [{"Key": "objects/cc/" + "3" * 62}]},
        {"Contents": []},
    ]
    client.get_paginator.return_value = paginator
    hashes = list(backend.iter_hashes())
    assert hashes == ["aa" + "1" * 62, "bb" + "2" * 62, "cc" + "3" * 62]


def test_requires_bucket(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CLAWFS_S3_BUCKET", raising=False)
    with pytest.raises(ValueError):
        S3Storage()
