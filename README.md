# ClawFS

Content-addressed file storage. SHA-256 dedup. Refcounted GC. Pluggable backend
(local disk in v1, Azure Blob in v2). FastAPI HTTP + Click CLI.

## Local install

```bash
pip install -e .
export CLAWFS_ROOT=./data

# CLI
echo "hello" > /tmp/hi
clawfs write notes/hi.txt /tmp/hi
clawfs ls
clawfs read notes/hi.txt
clawfs share notes/hi.txt --ttl 3600
clawfs rm notes/hi.txt
clawfs gc

# HTTP
uvicorn clawfs.api:app --reload
```

Endpoints: `PUT/GET /blobs[/{hash}]`, `PUT/GET/DELETE /refs/{path}`,
`GET /refs`, `POST /shares`, `GET /shares/{token}`, `POST /gc`.

## Docker

```bash
docker build -t clawfs .
docker run -p 8000:8000 -v $PWD/data:/data clawfs
```

## Azure

```bash
az group create -n clawfs-rg -l eastus
az deployment group create \
  -g clawfs-rg \
  -f azure/container-app.bicep \
  -p image=ghcr.io/you/clawfs:latest
```

Provisions a Container App + Blob Storage container. Switch the runtime
backend by setting `CLAWFS_BACKEND=azure` and wiring `AzureBlobStorage`
into `create_app` (the storage class is already implemented; just swap the
constructor in `api.py` when you cut v2).

## Architecture

- `clawfs/storage.py` — `Storage` ABC, `LocalStorage`, `AzureBlobStorage`.
- `clawfs/db.py` — SQLModel: `Blob(hash, size, refcount)`, `Ref(path→hash)`, `Share(token→ref)`.
- `clawfs/core.py` — `ClawFS` orchestrator. Dedup on put, refcount bump/drop on ref change, GC sweeps `refcount==0`.
- `clawfs/api.py` — FastAPI endpoints.
- `clawfs/cli.py` — Click CLI.

Same content under N paths = 1 blob on disk + N rows in `Ref`. Update a path
to new content: refcount on old hash decrements, new hash increments. `gc`
deletes orphan blobs.
