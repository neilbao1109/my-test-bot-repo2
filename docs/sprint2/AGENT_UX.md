# Agent UX — what a "good" ClawFS API looks like to an agent

Agents aren't humans. They don't browse, they don't retry on hunches, and they
hate ambiguity. The API should treat them like an exhausted ops engineer with
no patience.

## Errors must be machine-readable

Every error returns the same envelope: `{error: {code, message, retryable, hint}}`.
`code` is a stable string (`REF_NOT_FOUND`, `BLOB_MISSING`, `TOKEN_EXPIRED`,
`QUOTA_EXCEEDED`). `retryable: true` means "back off and try again", `false`
means "stop, this won't fix itself". Never overload HTTP 500 for "user typo".

## Idempotency by default

Uploading the same bytes twice → same `sha256` → same response, no duplicate
work, no duplicate ref unless asked. Mutations (create-ref, create-share)
accept an `Idempotency-Key`; replays within 24h return the original result.
Agents crash mid-loop; the API should make that boring.

## Cacheable reads

Blobs are immutable, so `GET /blob/{sha256}` returns
`Cache-Control: immutable, max-age=31536000` and a strong `ETag`. Refs are
mutable but cheap: include `ETag` + support `If-None-Match` so agents can
poll without paying for bytes.

## Batch over loops

Expose `POST /refs:batchGet`, `POST /blobs:batchStat`, `POST /shares:batchCreate`.
Anything an agent might do in a `for` loop should have a batch form that takes
up to ~100 items and returns per-item status. Saves round trips, saves rate
limit budget, and lets the server parallelise.

## Bonus: predictable pagination (`cursor`, not `page`), ISO-8601 everywhere,
and a `dry_run: true` flag on every mutation so agents can plan before acting.
