# Sprint 6 — Polish & Admin UI

> 5-day hard cutoff. Day 5 = retro doc regardless of completion state.

## Why this scope

Sprint 5 dogfood by Neil himself surfaced 4 distinct first-5-minute breakages:

1. README pointed Mac users at `clawfs-up.sh` (Linux-only)
2. `ghcr.io/neilbao1109/clawfs:latest` advertised but never pushed
3. After push, package was private by default → anonymous `docker pull` denied
4. Image was amd64-only → fails on Apple Silicon

Pattern: **every onboarding claim in README is a lie until proven by an integration test.** A random user lands, hits any one of those, leaves, never tells us. With 0 users today this is the highest-leverage problem to solve.

After that, two genuinely useful features that were deferred from Sprint 5: admin UI (so Neil doesn't have to SSH every time) and IP rate-limit on the public demo (so the demo tenant can't be DoS'd or filled by trolls).

## Priorities

### P0 — Onboarding bulletproofing (Neil)

- New CI job `smoke-quickstart` that runs the exact commands in README from a clean Ubuntu runner:
  - `pip install clawfs` from real PyPI → server starts → put + get
  - `npm i @neilbao/clawfs-sdk` from real npm → put a blob via SDK
  - `docker pull ghcr.io/neilbao1109/clawfs:latest` → run → put + get
  - `helm install` against kind → put + get
- Publishes a status badge to README. **Red badge = something a user would hit on day 1.**
- Bonus: scrape README for `bash`/`python`/`docker` code blocks and try to run them; fail CI if any block isn't actually runnable.

### P1 — Admin UI MVP (subagent A)

- Single static HTML at `GET /admin/` (vanilla HTML + fetch, no React)
- Behind `CLAWFS_ADMIN_TOKEN` env var (separate from per-tenant tokens)
- Features:
  - Table of tenants (id, name, used / quota, # tokens)
  - "Create tenant" form (name, quota bytes, quota objects → returns generated token, displayed once)
  - "Rotate token" button per row (confirms, displays new token once)
  - "Set quota" inline edit
  - "Delete" button (with confirm)
- API surface: `GET/POST/PATCH/DELETE /admin/tenants`, `POST /admin/tenants/{id}/rotate`
- Login = bearer token in a single login screen, stored in `sessionStorage` (NOT localStorage; gone on tab close)

### P2 — IP rate limit on demo tenant (subagent B)

- Middleware: per-(tenant, IP) leaky-bucket OR fixed window
- Configurable per tenant via new `Tenant.rate_limit_per_minute` column (default `null` = unlimited)
- Demo tenant: 30 req/min/IP
- 429 response with `Retry-After` header
- Daily reset of `Tenant.used_bytes` for tenants with `Tenant.daily_reset = True` flag

### P3 — Audit log (Neil, if time)

- New `audit_log.jsonl` per data root, append-only
- One line per write op: `{ts, tenant_id, op, ref_path, bytes, ip}`
- Rotated daily
- `clawfs admin audit tail --tenant alice --since 1h`

## Out of scope

- Stripe / billing / self-serve signup
- Cloud-native multipart (S3 native parts, GCS resumable uploads)
- Webhooks
- SSO

## Success criteria

- A friend with zero context can `pip install clawfs && uvicorn clawfs.api:app` and put a file in <60 seconds.
- Neil can manage tenants from a browser at `http://20.198.122.69/admin/` without SSH.
- Demo tenant can't be DoS'd by a script kiddie.
- 1 of the 3 promised users has actually been recruited and used the system.

## Day 5 deliverables (regardless)

- PR merged or open with status comment
- `docs/sprint6/RETRO.md` with: shipped, deferred, pain points, what to do in Sprint 7
