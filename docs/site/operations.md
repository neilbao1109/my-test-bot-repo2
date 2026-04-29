# Operations

## Backups

Pick the strategy that matches your backend:

- **`local`** — `tar czf clawfs-$(date +%F).tgz /var/lib/clawfs` on a cron, ship to wherever you keep backups. Nothing fancy: blobs are content-addressed, so dedup happens for free at restore time too.
- **`azure`** — turn on Azure Blob soft-delete + versioning at the storage account.
- **`s3`** — turn on bucket versioning (or use S3 Object Lock for compliance).

The SQLite metadata DB lives next to the blobs (`local`) or in the data volume mount (cloud). Back it up with the blobs.

## Garbage collection

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" $URL/gc
# → {"removed": 12}
```

Refs hold strong references. GC walks the ref table, marks live blobs, and deletes the rest. Safe to run any time; we'd suggest weekly via cron.

## Token rotation

API tokens are read from `CLAWFS_API_TOKENS` (CSV). To rotate:

1. Append the new token: `CLAWFS_API_TOKENS=oldtok,newtok`
2. Restart / `docker compose up -d`
3. Roll callers to the new token
4. Drop the old: `CLAWFS_API_TOKENS=newtok`
5. Restart

A first-class `/tokens` endpoint with rotation built in is on the Sprint 3 SHOULD list.

## Observability

`GET /healthz` — liveness probe.

`GET /metrics` — Prometheus scrape format. Counters per endpoint family (`clawfs_blob_put_total`, `clawfs_ref_get_total`, …) plus backend latency histograms.

For Azure Container Apps the `appLogsConfiguration` block in `azure/container-app.bicep` already wires structured stdout into a Log Analytics workspace.
