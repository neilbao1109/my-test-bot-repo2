# Launching ClawFS — content-addressed storage for AI agents

*Draft 1. Not yet published — review before posting.*

---

I built ClawFS over the past few weeks. It's a content-addressed file system you can self-host in 30 seconds:

```bash
curl -fsSL https://raw.githubusercontent.com/neilbao1109/my-test-bot-repo2/main/scripts/clawfs-up.sh | sudo bash
```

…and now you have an HTTP API for putting bytes (by hash), naming them (refs), and sharing them (signed URLs), with SHA-256 dedup baked in.

## Why I built it

I run a bunch of LLM agents. They generate a *lot* of files — model outputs, screenshots, traces, intermediate Parquet files. None of the existing options fit:

- **S3** is great until you want to give a friend a token. Then you're in IAM hell.
- **The local filesystem** doesn't have an HTTP API.
- **Dropbox** doesn't dedup, doesn't have a sane API, and isn't self-hostable.
- **Sshfs / NFS** — let's not.

What I actually want is something I can `pip install`, point my agents at, and let them dump bytes. Same content uploaded from 5 jobs → stored once. A friend wants to use it → I give them a token with a 10 GiB quota and they can't fill my disk.

So: ClawFS.

## What it does

```python
from clawfs.sdk import ClawFS
fs = ClawFS(base_url="https://my.clawfs.example", token="sk_...")

fs.put("checkpoints/v1.bin", open("v1.bin","rb").read())  # 8 GiB → chunked automatically
fs.list("checkpoints/")                                    # → [{path, hash, updated_at}]
url = fs.share("checkpoints/v1.bin", ttl_seconds=3600)     # → signed URL
```

Under the hood:

- **Content-addressed**: blob path is `objects/<aa>/<sha256-rest>`. Identical bytes → one disk copy. Refcounted, so deletes don't strand data.
- **Per-tenant namespaces**: refs scoped per token. Tenant A's `model.bin` ≠ Tenant B's `model.bin`. But blobs still dedup across tenants when content matches.
- **Chunked uploads** for multi-GB files: streamed to disk, never buffered. I tested with 1 GiB — server peak RSS stays at ~217 MiB.
- **Pluggable backends**: local disk, S3, Azure Blob, GCS. Same API.
- **Quotas + admin CLI**: `clawfs admin tenant create alice --quota-bytes 10GiB` and you're done.

## Self-host paths

Three ways:

**Laptop** (Docker, 30 seconds):
```bash
docker run -p 8000:8000 -v ./data:/data \
  -e CLAWFS_API_TOKENS=devtoken ghcr.io/neilbao1109/clawfs:latest
```

**VM** (one shell script, supports Ubuntu 22/24 + Debian 12):
```bash
curl -fsSL .../clawfs-up.sh | sudo bash -s -- --domain clawfs.you.dev --email you@you.dev
```
Caddy + auto-HTTPS included.

**Kubernetes** (Helm):
```bash
helm install clawfs ./charts/clawfs --set backend=s3 \
  --set s3.bucket=my-clawfs --set s3.existingSecret=clawfs-creds
```

## What I won't pretend it has

- No web UI yet (admin UI is on the roadmap, this week).
- No self-serve signup. You give people tokens manually. (For 3 users this is *faster* than building Stripe.)
- No s3-style server-side copy / cross-region replication. If you need this you're at a scale where ClawFS isn't your bottleneck.

## Try it

```bash
pip install clawfs
```

Or poke the live demo at `http://20.198.122.69` (read-only, single-tenant, treat it like a public toilet — it'll be wiped daily once I finish the rate-limit work).

GitHub: <https://github.com/neilbao1109/my-test-bot-repo2>

If it solves something for you, ⭐ the repo and tell me what you'd add. If it doesn't, tell me what's missing — that's worth more.

— Neil
