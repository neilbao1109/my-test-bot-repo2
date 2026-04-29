import hashlib
import time

import pytest
from sqlmodel import Session, select

from clawfs.core import ClawFS
from clawfs.db import Blob


@pytest.fixture
def fs(tmp_path):
    return ClawFS.local(str(tmp_path))


def test_dedup_same_content_one_blob(fs):
    data = b"hello world"
    h1, _ = fs.put_ref("a/x.txt", data)
    h2, _ = fs.put_ref("b/y.txt", data)
    assert h1 == h2 == hashlib.sha256(data).hexdigest()

    with Session(fs.engine) as s:
        blobs = list(s.exec(select(Blob)))
        assert len(blobs) == 1
        assert blobs[0].refcount == 2

    # delete one ref → refcount drops, blob still there
    fs.delete_ref("a/x.txt")
    with Session(fs.engine) as s:
        b = s.get(Blob, h1)
        assert b.refcount == 1
    assert fs.storage.exists(h1)

    # delete last ref + gc → blob gone
    fs.delete_ref("b/y.txt")
    assert fs.gc() == 1
    assert not fs.storage.exists(h1)


def test_resolve_ref_roundtrip(fs):
    data = b"\x00\x01\x02 binary payload"
    fs.put_ref("bin/data", data)
    assert fs.resolve_ref("bin/data") == data
    assert fs.resolve_ref("missing") is None

    # update path to new content; old hash should drop to 0
    fs.put_ref("bin/data", b"old")
    new_hash, _ = fs.put_ref("bin/data", b"new")
    assert fs.resolve_ref("bin/data") == b"new"
    fs.gc()
    # only "new" blob should survive
    with Session(fs.engine) as s:
        hashes = {b.hash for b in s.exec(select(Blob))}
        assert new_hash in hashes


def test_share_token_works_and_expires(fs):
    fs.put_ref("doc/readme", b"shared content")
    token = fs.create_share("doc/readme")
    assert fs.resolve_share(token) == b"shared content"
    assert fs.resolve_share("garbage-token") is None

    # short TTL → expires
    short = fs.create_share("doc/readme", ttl_seconds=1)
    assert fs.resolve_share(short) == b"shared content"
    time.sleep(1.2)
    assert fs.resolve_share(short) is None

    # share to nonexistent ref raises
    with pytest.raises(KeyError):
        fs.create_share("does/not/exist")
