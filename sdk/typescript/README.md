# @neilbao/clawfs-sdk

TypeScript SDK for [ClawFS](../..) — content-addressed file system for agents.

```ts
import { ClawFS } from "@neilbao/clawfs-sdk";

const fs = new ClawFS({
  baseUrl: "https://clawfs.example.com",
  token: process.env.CLAWFS_TOKEN!,
});

const { hash } = await fs.put("hello agents");
const bytes = await fs.get(hash);

await fs.link("notes/today.md", "# Today\n- ship sprint 3");
const { token } = await fs.share("notes/today.md", 3600);
// → anyone with `${baseUrl}/shares/${token}` can download for 1h
```

## Why

- **Pure HTTP** — no cloud-vendor SDK dependency. Works in Node 20+, Deno, Bun, edge runtimes.
- **Same contract as `clawfs-py`** — sha256 content-addressing, automatic `Idempotency-Key`, structured errors with `code` + `retryable`.
- **Tiny** — single file, no runtime deps.

## Errors

```ts
import { ClawFSError } from "@neilbao/clawfs-sdk";

try { await fs.get("deadbeef"); }
catch (e) {
  if (e instanceof ClawFSError) {
    console.log(e.code, e.status, e.retryable);
    // not_found 404 false
  }
}
```

## Live testing

```bash
CLAWFS_LIVE=1 \
CLAWFS_URL=https://your-clawfs CLAWFS_TOKEN=… \
npm run test:live
```
