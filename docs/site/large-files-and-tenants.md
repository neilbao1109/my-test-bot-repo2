# Multipart / chunked uploads

For anything bigger than a few hundred MB, use the multipart upload API. ClawFS streams parts directly to disk so the server never holds a full GiB-sized blob in memory.

## TypeScript

```ts
import { ClawFS } from "@neilbao/clawfs-sdk";

const fs = new ClawFS({ baseUrl: "https://clawfs.example.com", token });

// from a Uint8Array
const result = await fs.putLarge(bigBuffer, {
  partSize: 8 * 1024 * 1024, // default 8 MiB
  targetRef: "datasets/v1.parquet",
});
console.log(result.hash, result.size);

// from a Web ReadableStream (e.g. fetch().body, or a file in the browser)
const res = await fetch("/some/big/file");
await fs.putLarge(res.body!, { targetRef: "ingest/source.bin" });
```

## Python

```python
import hashlib, requests

URL, TOKEN = "https://clawfs.example.com", "..."
H = {"Authorization": f"Bearer {TOKEN}"}

# 1. open session
uid = requests.post(f"{URL}/uploads", headers=H,
                    data={"target_ref": "huge.bin"}).json()["id"]

# 2. push parts (any size, in any order, retry-safe)
with open("huge.bin", "rb") as f:
    n = 0
    while True:
        chunk = f.read(8 * 1024 * 1024)
        if not chunk: break
        n += 1
        requests.put(f"{URL}/uploads/{uid}/parts/{n}", headers=H, data=chunk).raise_for_status()

# 3. finalize → returns sha256 of the concatenated bytes
result = requests.post(f"{URL}/uploads/{uid}/complete", headers=H).json()
print(result["hash"], result["size"])
```

## Wire shape

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/uploads` | Open a session. Form: `target_ref` (optional). |
| `PUT` | `/uploads/{id}/parts/{n}` | Stream a part (raw body). Returns `{n, size, etag}` (etag = sha256 of part). |
| `POST` | `/uploads/{id}/complete` | Concat + hash + persist. Returns `{hash, size, blob_created}`. |
| `DELETE` | `/uploads/{id}` | Abort + clean scratch. |

Verified live against `http://20.198.122.69`: 1 GiB upload in ~28s with peak server RSS ~217 MiB.

# Multi-tenancy

ClawFS now scopes refs and shares per tenant. Blobs themselves are still content-addressed — two tenants who upload the same file dedup on disk — but each tenant has a private namespace of refs, can't list each other's refs, and can't free another tenant's blobs by deleting their own refs.

## Provisioning

```python
from clawfs.core import ClawFS
fs = ClawFS.local("/var/lib/clawfs")
fs.upsert_tenant("acme",   tokens=["sk_acme_…"],   max_bytes=50 * 1024**3)
fs.upsert_tenant("globex", tokens=["sk_globex_…"], max_bytes=10 * 1024**3)
```

After that, the bearer token on each request maps directly to the tenant. Existing single-tenant deployments using a flat `CLAWFS_API_TOKENS` CSV continue to work and are mapped to a synthetic tenant called `default`.

## Migration

Upgrading from 0.2.x to 0.3.x runs a tiny one-shot SQLite migration on first start: it adds the `tenant_id` columns and rewrites legacy ref paths into the `default/` namespace. No manual step required.
