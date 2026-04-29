# Sprint 4 — Big files, real tenants, ship the SDKs

> Sprint 3 closed all 5 MUSTs + GCS stretch. ClawFS now runs on 4 backends, has 2 SDKs, and 3 deploy modes. North-star next: actually get bytes through it at production scale, and let > 1 customer share an instance.

## Theme
**"Small file in, big file in, real tenants, public SDKs."**

## Priorities (CEO-locked)
| # | Item | Why now |
|---|---|---|
| P1 | **Multipart upload (chunking)** | Today the API holds the entire blob in memory. Anything > a few hundred MB OOMs. This is the #1 blocker for any real workload. |
| P2 | **Multi-tenancy** | Token → tenant_id; refs / shares / GC scoped per tenant; quotas. Lets > 1 customer share a deployment. |
| P3 | **SaaS scaffolding** | Hosted plane: signup, auto-provision tenant, billing-ready (Stripe interface, no real charge yet). |
| P4 | **Admin UI** | Browse refs, see quotas, rotate tokens. Nice-to-have, Sprint 5 if needed. |
| Always | **Publish SDKs** (PyPI + npm) | Tokens are useless on a laptop; real consumers need `pip install clawfs` / `npm i @clawfs/sdk`. Sets up the north-star metric (3 external users, 1k calls). |

## Scope decisions
- **Chunking wire format:** S3-style multipart — `POST /uploads` → id, `PUT /uploads/{id}/parts/{n}`, `POST /uploads/{id}/complete` returning the final sha256. Familiar, retry-friendly, partial-upload-friendly.
- **Chunk size default:** 8 MiB. Configurable per call. Each part also content-addressed for resumability.
- **Tenant model:** token → `tenant_id`. Storage keys prefixed `tenants/<tid>/objects/...` and `tenants/<tid>/refs/...`. Old single-tenant deployments transparently mapped to `tenant_id="default"`.
- **Quotas:** soft (warning header) + hard (413). Stored as `(max_bytes, max_objects)` per tenant.
- **SaaS:** thin — FastAPI signup endpoint, magic-link email, provision a tenant + write token. Stripe webhook stubbed but **no real charging this sprint**.
- **Admin UI:** if we get there, plain server-side HTML (no SPA framework). Read-only first.

## Out of scope
- Encryption at rest (Sprint 5)
- ACLs beyond tenant boundary (per-ref permissions) (Sprint 5)
- Streaming GET for huge files (the multipart PUT side is the bigger pain right now)

## Exit criteria
- A 1 GiB file uploads + roundtrips via the Python SDK without OOM
- Two tenants on one instance can't see each other's blobs/refs
- `clawfs-py` installable via `pip install clawfs` from PyPI
- `@clawfs/sdk` installable via `npm i @clawfs/sdk` from npm
- All of the above demoable on the existing dogfood VM

## Risks / unknowns
- **PyPI / npm credentials** — need user to one-click trust the GitHub Actions OIDC publisher, or hand a token.
- Backend-native multipart (s3 multipart, azure block blob) is much better than buffering. MVP = local buffer; cloud-native paths are stretch.
