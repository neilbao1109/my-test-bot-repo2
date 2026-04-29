# ClawFS docs

> **Self-host first, cloud-optional.**
> Content-addressed file system for AI agents. One API. Three places to run it.

## Three quick-starts

Pick the one that matches your infra. All three have been verified end-to-end against the same SDKs.

| If you have… | Use | Time to first byte |
|---|---|---|
| A laptop | [`docker run`](./quickstart-laptop.md) | ~1 min |
| A Linux VM (anywhere) | [`clawfs up`](./quickstart-vm.md) | ~5 min |
| Azure (or AWS / GCP cluster) | [Container Apps / S3 / GCS](./quickstart-cloud.md) | ~10 min |

## SDKs

- Python — [`clawfs-py`](./sdk-python.md) (`pip install clawfs`)
- TypeScript — [`@clawfs/sdk`](./sdk-typescript.md) (`npm i @clawfs/sdk`)

Both speak the same wire protocol, with sha256 dedup + automatic `Idempotency-Key` so retries are safe.

## Backends

ClawFS is the API. Where the bytes live is your choice:

- **`local`** — disk on the same host. Default. Best for dev + single-VM prod.
- **`azure`** — Azure Blob Storage. Managed-identity friendly.
- **`s3`** — AWS S3 / MinIO / Cloudflare R2 / Backblaze B2 — anything S3-compatible.

Switching is one env var: `CLAWFS_BACKEND=local|azure|s3`. The wire API and SDKs are identical.

See [Operations](./operations.md) for backups, GC, token rotation, and observability.
