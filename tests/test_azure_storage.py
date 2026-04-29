"""Azure storage tests — uses unittest.mock; skipped if SDK missing."""
from __future__ import annotations

import pytest

azure_blob = pytest.importorskip("azure.storage.blob")


def _patch_service(monkeypatch, container_client):
    """Make BlobServiceClient.from_connection_string return a fake."""
    class FakeService:
        def get_container_client(self, name):
            container_client._container_name = name
            return container_client

    monkeypatch.setattr(
        azure_blob.BlobServiceClient,
        "from_connection_string",
        classmethod(lambda cls, conn_str: FakeService()),
    )


class FakeBlobClient:
    def __init__(self, store, name):
        self._store = store
        self._name = name

    def exists(self):
        return self._name in self._store


class FakeContainerClient:
    def __init__(self):
        self.store: dict[str, bytes] = {}

    def create_container(self):
        pass

    def upload_blob(self, name, data, overwrite=False):
        if name in self.store and not overwrite:
            raise FileExistsError(name)
        self.store[name] = bytes(data)

    def download_blob(self, name):
        if name not in self.store:
            from azure.core.exceptions import ResourceNotFoundError
            raise ResourceNotFoundError(name)

        class _D:
            def __init__(self, b):
                self._b = b

            def readall(self):
                return self._b

        return _D(self.store[name])

    def get_blob_client(self, name):
        return FakeBlobClient(self.store, name)

    def delete_blob(self, name):
        self.store.pop(name, None)

    def list_blobs(self, name_starts_with=""):
        class _B:
            def __init__(self, n):
                self.name = n

        return [_B(n) for n in self.store if n.startswith(name_starts_with)]


def test_azure_storage_roundtrip(monkeypatch):
    fake = FakeContainerClient()
    _patch_service(monkeypatch, fake)
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "fake")
    monkeypatch.setenv("CLAWFS_AZURE_CONTAINER", "blobs")

    from clawfs.storage import AzureBlobStorage

    s = AzureBlobStorage()
    h = "abcd" + "0" * 60
    assert not s.exists(h)
    s.put(h, b"payload")
    assert s.exists(h)
    assert s.get(h) == b"payload"
    # idempotent put
    s.put(h, b"payload")
    # naming matches LocalStorage layout
    assert f"objects/{h[:2]}/{h[2:]}" in fake.store
    assert list(s.iter_hashes()) == [h]
    s.delete(h)
    assert not s.exists(h)


def test_azure_get_missing_raises_filenotfound(monkeypatch):
    fake = FakeContainerClient()
    _patch_service(monkeypatch, fake)
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "fake")
    monkeypatch.setenv("CLAWFS_AZURE_CONTAINER", "blobs")

    from clawfs.storage import AzureBlobStorage

    s = AzureBlobStorage()
    with pytest.raises(FileNotFoundError):
        s.get("deadbeef" + "0" * 56)


def test_factory_selects_azure(monkeypatch):
    fake = FakeContainerClient()
    _patch_service(monkeypatch, fake)
    monkeypatch.setenv("CLAWFS_BACKEND", "azure")
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "fake")
    monkeypatch.setenv("CLAWFS_AZURE_CONTAINER", "blobs")

    from clawfs.factory import make_storage
    from clawfs.storage import AzureBlobStorage

    s = make_storage()
    assert isinstance(s, AzureBlobStorage)
