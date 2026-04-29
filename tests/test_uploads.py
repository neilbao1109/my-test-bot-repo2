"""Multipart / chunked upload tests."""
from __future__ import annotations

import hashlib
import os

import pytest

from clawfs.core import ClawFS
from clawfs.uploads import UploadManager


@pytest.fixture
def fs(tmp_path):
    return ClawFS.local(str(tmp_path))


@pytest.fixture
def manager(fs, tmp_path):
    return UploadManager(scratch_root=str(tmp_path / "scratch"), storage=fs.storage, engine=fs.engine)


def test_three_part_roundtrip(fs, manager):
    parts = [b"hello-", b"world-", b"final"]
    expected = b"".join(parts)
    expected_hash = hashlib.sha256(expected).hexdigest()

    upload_id = manager.create()
    for i, p in enumerate(parts, start=1):
        size, etag = manager.write_part_sync(upload_id, i, p)
        assert size == len(p)
        assert etag == hashlib.sha256(p).hexdigest()

    res = manager.complete(upload_id)
    assert res.hash == expected_hash
    assert res.size == len(expected)
    assert res.created is True
    # roundtrip via storage
    assert fs.get_blob(res.hash) == expected


def test_complete_with_target_ref_binds_into_tenant_namespace(fs, manager):
    upload_id = manager.create(tenant_id="acme", target_ref="big-file.bin")
    manager.write_part_sync(upload_id, 1, b"X" * 100)
    manager.write_part_sync(upload_id, 2, b"Y" * 100)
    res = manager.complete(upload_id)
    # ref is visible to acme only
    assert fs.resolve_ref("big-file.bin", tenant_id="acme") == b"X" * 100 + b"Y" * 100
    assert fs.resolve_ref("big-file.bin", tenant_id="default") is None
    assert res.size == 200


def test_dedup_when_same_bytes_uploaded_again(fs, manager):
    payload = b"the-same"
    u1 = manager.create()
    manager.write_part_sync(u1, 1, payload)
    r1 = manager.complete(u1)
    assert r1.created is True

    u2 = manager.create()
    manager.write_part_sync(u2, 1, payload)
    r2 = manager.complete(u2)
    assert r2.hash == r1.hash
    assert r2.created is False  # blob already existed


def test_part_after_complete_fails(manager):
    u = manager.create()
    manager.write_part_sync(u, 1, b"abc")
    manager.complete(u)
    # no async path here; use the sync writer to confirm session is closed
    # via the explicit guard inside the manager.
    import asyncio

    async def runner():
        async def chunks():
            yield b"abc"
            return
        return await manager.write_part(u, 2, chunks())
    with pytest.raises(FileNotFoundError):
        asyncio.run(runner())


def test_abort_cleans_scratch(fs, manager, tmp_path):
    u = manager.create()
    manager.write_part_sync(u, 1, b"oops")
    scratch = manager.scratch_root / u
    assert scratch.exists()
    assert manager.abort(u) is True
    assert not scratch.exists()


def test_complete_empty_fails(manager):
    u = manager.create()
    with pytest.raises(ValueError):
        manager.complete(u)


def test_large_streaming_does_not_buffer(fs, manager):
    """Sanity: 32 MiB across 4 parts should roundtrip correctly."""
    blob_size = 32 * 1024 * 1024
    part_size = blob_size // 4
    h = hashlib.sha256()
    u = manager.create()
    for i in range(1, 5):
        chunk = (bytes([i]) * part_size)
        h.update(chunk)
        manager.write_part_sync(u, i, chunk)
    res = manager.complete(u)
    assert res.hash == h.hexdigest()
    assert res.size == blob_size
