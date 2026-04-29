# ClawFS

> A content-addressed file system for AI agents. Self-host in 30 seconds, or `pip install` and point at someone else's.

[![PyPI](https://img.shields.io/pypi/v/clawfs)](https://pypi.org/project/clawfs/) [![npm](https://img.shields.io/npm/v/@neilbao/clawfs-sdk)](https://www.npmjs.com/package/@neilbao/clawfs-sdk) [![CI](https://github.com/neilbao1109/my-test-bot-repo2/actions/workflows/ci.yml/badge.svg)](https://github.com/neilbao1109/my-test-bot-repo2/actions/workflows/ci.yml)

```python
from clawfs.sdk import ClawFS  # pip install clawfs
fs = ClawFS(base_url="http://localhost:8000", token="...")

fs.put("notes/today.md", b"# things I learned\n...")    # SHA-256 dedup
fs.list("notes/")                                        # list refs
url = fs.share("notes/today.md", ttl_seconds=3600)       # signed URL
```

## Why

Agents produce a lot of files: model outputs, intermediate artifacts, screenshots, traces. S3 is overkill, the local filesystem isn't shareable, and Dropbox doesn't speak HTTP.

ClawFS gives you:

- **One HTTP API** for blobs (by hash) + refs (by name) + signed shares (time-limited URLs)
- **SHA-256 dedup** out of the box — upload the same model checkpoint from 5 jobs, store it once
- **Multipart chunking** for multi-GB files without OOM
- **Multi-tenant** with per-tenant quotas, so you can hand a token to a friend without losing your laptop
- **Pluggable backends** — local disk, Azure Blob, S3, GCS — same API
- **Self-host first**: one `pip install` + one shell script, or use the Docker / Helm path

## Install

### As an SDK (talk to an existing deployment)

```bash
pip install clawfs                 # Python
npm i @neilbao/clawfs-sdk          # TypeScript
```

### As a server (self-host)

```bash
# laptop / VM (Docker required)
curl -fsSL https://raw.githubusercontent.com/neilbao1109/my-test-bot-repo2/main/scripts/clawfs-up.sh \
  | sudo bash -s -- --image ghcr.io/neilbao1109/clawfs:latest

# or kubernetes
helm install clawfs ./charts/clawfs
```

See [docs/site/quickstart-laptop.md](docs/site/quickstart-laptop.md), [quickstart-vm.md](docs/site/quickstart-vm.md), [quickstart-cloud.md](docs/site/quickstart-cloud.md).

## Multi-tenant in 30 seconds

```bash
# create a tenant with a 10 GiB quota
clawfs admin tenant create alice --quota-bytes 10GiB
# → ✅ created tenant 'alice'
# →    token: sk_xxx...
# →    quota: 10.00 GiB / ∞ objects

# hand them the token; if they exceed quota they get HTTP 413, not your problem
```

See [docs/site/large-files-and-tenants.md](docs/site/large-files-and-tenants.md) for the chunked-upload + tenant-isolation contract.

## Status

| Sprint | Highlights | Status |
|---|---|---|
| 1-2 | Local + Azure backends, FastAPI, Click CLI, Container Apps deploy | shipped |
| 3 | TS SDK + S3 + Helm + GCS + one-command VM deploy + docs | shipped |
| 4 | Chunked uploads (1 GiB verified), multi-tenancy, PyPI + npm | shipped |
| 5 | Tenant quotas, `clawfs admin` CLI, public demo, admin UI | in progress |

Live demo: `http://20.198.122.69` (single-tenant, no quota — for poking only).

## Docs

- [Quickstart — laptop](docs/site/quickstart-laptop.md)
- [Quickstart — VM](docs/site/quickstart-vm.md)
- [Quickstart — Azure Container Apps](docs/site/quickstart-cloud.md)
- [Large files & multi-tenancy](docs/site/large-files-and-tenants.md)
- [Operations](docs/site/operations.md)

## License

MIT.
