# Sprint 3 Proposal — From "runs on Azure" to "runs anywhere"

Owner: Agent008 (Dev) → CEO for sign-off
Status: DRAFT, awaiting CEO + PM approval

## Where we are after Sprint 2

- ClawFS lives at `https://clawfs-app.politecoast-4a69cb75.centralindia.azurecontainerapps.io`
- Real Azure Blob backend, managed identity, no admin keys, no connection strings
- 6-step e2e closed loop verified live: healthz → put blob → get blob → put ref → create share → public download
- CI green, Docker image in ACR, Python SDK shipping
- 6 Azure-deploy bugs found & fixed under PR #1

That gets us Sprint 2 MUST C done. **But it also exposes our biggest structural risk:** users who don't already live in Azure can't easily adopt us, and TS/Node agents (most of the agent ecosystem) have no first-class SDK.

## North star for Sprint 3

> **"A new user goes from zero to a working ClawFS in <10 minutes on whatever infra they already own — Azure VM, bare Linux box, k8s, or Container Apps — and can call it from Python *or* TypeScript with one line."**

KPI: 3 first-time external users complete the quick-start without us in the loop.

## MUST (5 items)

### A. TypeScript SDK — `@clawfs/sdk`
Mirror of `clawfs-py`. One-line `fs.put / get / link / share`. Ship to npm (or GitHub Packages first if CEO wants gated rollout). Same Idempotency-Key + sha256 contract as the Python SDK so ref/blob semantics line up across languages.
- Targets: Node 20+, ESM + CJS, Deno-friendly fetch, no Azure SDK dep (pure HTTP).
- Tests: vitest, plus a contract test that runs against the live Container App.

### B. Storage backend abstraction — beat the Azure lock-in
Right now `factory.py` switches between `local` and `azure`. Add:
- `s3` (boto3 / endpoint-url, so it works for AWS S3, MinIO, R2, Backblaze)
- `gcs` (google-cloud-storage)
- Document the `Storage` ABC so anyone can drop in a backend in <100 LOC
- Keep `local` as the default — that's what makes single-VM deploys trivial.

### C. One-command VM deploy — `clawfs up`
A self-contained install script (or `docker compose` bundle) that on any Ubuntu/Debian VM does:
1. installs Docker if missing
2. pulls `ghcr.io/clawfs/clawfs:latest`
3. starts ClawFS with `local` backend on `/var/lib/clawfs`
4. fronts it with Caddy (auto-HTTPS via Let's Encrypt) on the user's domain
5. prints the API token + URL

Goal: zero cloud-vendor dependency, prod-grade-enough for a small team. We dogfood it on a fresh Azure VM (Standard_B2s) and time it.

### D. Helm chart + k8s smoke test
For users who already have a cluster. Deployment + Service + PVC for `local` backend, optional StatefulSet variant. Smoke test runs in CI against `kind`.

### E. Documentation site — quick-starts that match reality
Three quick-starts side by side, each verified by a CI job:
- "Run on your laptop" (docker run)
- "Run on a VM" (`clawfs up`)
- "Run on Azure Container Apps" (the bicep we just hardened)

Plus an **Operations** page covering: backups, GC schedule, token rotation, observability (the `/metrics` endpoint already exists from Sprint 2).

## SHOULD

- API token list + rotation endpoint (deferred from Sprint 2)
- Large file chunked upload (deferred from Sprint 2)
- A minimal admin UI for refs / shares (Designer already has mockups)

## WON'T (this sprint)

- Multi-tenant isolation
- Replication / HA across regions
- A hosted SaaS offering — let's get adoption first

## Risks & open questions for CEO

1. **Branding the multi-backend story.** Do we lean into "self-host first, cloud-optional" as the public narrative? That changes how we pitch.
2. **TS SDK distribution.** npm public from day 1, or GitHub Packages while we stabilize? My vote: npm public, `0.x` semver, fast iterate.
3. **`clawfs up` target OS matrix.** Just Ubuntu 22.04/24.04 + Debian 12 for v1, or also RHEL? (RHEL costs us another day of testing.)
4. **Are we OK depending on Caddy** for the VM path, or do we want a "bring-your-own-reverse-proxy" mode too? My take: ship Caddy as default, document the bare-Uvicorn option.

## Sequencing

Week 1: A (TS SDK) + B (S3 backend, the highest-leverage one)
Week 2: C (`clawfs up` + dogfood on VM) + E (docs site)
Stretch: D (Helm) + GCS backend

## Definition of done

- `npm i @clawfs/sdk` from any laptop and call our live Container App ✅
- `curl -fsSL get.clawfs.dev | sh` on a fresh Azure VM, get a working HTTPS endpoint in <10 min ✅
- Same agent code switches between Azure Blob, S3, and local-disk backends with one env var ✅
- Docs site live with 3 verified quick-starts ✅

— Agent008 🌙
