# Sprint 5 — Quota + Admin (CEO version)

**Hard deadline: 5 working days. At Day 5 EOD we ship what's done and write retro.**

## North star
3 external users + 1000 calls. Sprint 4 made install easy; this sprint makes onboarding + ops easy enough that you can hand a token to a friend and they can't accidentally fill our disk.

## P0 — must ship (Day 1-2)

### Tenant quota enforcement
- `Tenant.max_bytes` and `Tenant.max_objects` already exist (Sprint 4) — wire them.
- Increment `used_bytes` / `used_objects` on:
  - `put_blob` / `put_ref` (only when blob is *newly created* for that tenant)
  - `complete` of multipart upload
- Decrement on `delete_ref` if it caused the blob's tenant-refcount to hit 0.
- On exceed: HTTP `413 Payload Too Large` with JSON `{detail, used, limit}`.
- Default per-tenant: `max_bytes=10*GiB, max_objects=10_000`. Configurable per tenant via admin CLI.

### `GET /usage` endpoint
- Returns `{tenant_id, used_bytes, used_objects, max_bytes, max_objects}`.
- Authed; resolves tenant from bearer.

### Tests
- 4 new pytest cases: under-quota OK, over-bytes 413, over-objects 413, dedup doesn't double-count.

## P0 — must ship (Day 3)

### `clawfs admin` CLI
Subcommands (all hit the SQLite DB directly via `ClawFS.local()`):
- `clawfs admin tenant create --name <n> [--quota-bytes 10GiB] [--quota-objects 10000]` → prints generated token.
- `clawfs admin tenant list` → table.
- `clawfs admin tenant rotate-token <id>` → revokes old, issues new.
- `clawfs admin tenant set-quota <id> --bytes 50GiB`.
- `clawfs admin tenant delete <id>`.

Targets local `--root` (default `./clawfs-data`). For container deployments it's `docker exec clawfs clawfs admin ...`.

## P1 — must ship (Day 4)

### README rewrite
- Top of file: 30-second pitch + the 3-line install + the 1 paragraph "why not just S3".
- Move sprint-context stuff to `docs/`.

### 90-second asciinema demo
- `clawfs up` → `pip install clawfs` → put 1 GiB → `/usage` → done.

### Blog draft (don't publish)
- `docs/blog/0-launch.md` — first-person announcement, you can edit + publish on your own time.

## P2 — must ship (Day 4)

### Public demo tenant on the dogfood VM
- New tenant `demo`, `max_bytes=10MiB`, `max_objects=100`.
- Token printed in README so anyone can try without signup.
- IP-based rate limit (10 req/s per IP) via Caddy or in-process middleware.
- Daily reset (cron clears tenant data + resets counters).

## P3 — only if P0-P2 done (Day 5)

### Admin UI
- Single HTML page at `/admin/`, requires admin token (`CLAWFS_ADMIN_TOKEN` env).
- Lists tenants with usage bars, "rotate token" button, "delete" button.
- No build step — vanilla HTML + fetch().

## Out of scope (slip to Sprint 6)
- Self-serve signup / magic link / Stripe
- Cloud-native multipart on s3/azure/gcs
- Tenant-level audit log
- Usage charts / time series

## Day 5 retro must answer
1. Did P0 ship? If no, why?
2. How many users did Neil pull in? What did they say?
3. What's the next bottleneck — code, distribution, or pricing?
