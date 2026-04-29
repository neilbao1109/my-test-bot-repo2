# ClawFS — Design Notes

Content-addressed filesystem. Blobs keyed by SHA-256, refs are cheap pointers, storage is deduplicated by construction. Used by humans (Web UI) and agents (REST + CLI) against the same store.

---

## Design Philosophy

**Humans need orientation; agents need precision.**

The Web UI hides the hash. People think in folders, names, thumbnails, and recency — so we surface those, and treat dedup as a quiet superpower (a small "deduplicated" badge, a savings counter at the bottom). The hash is *available* on demand, never *required*.

The CLI and REST surface invert that. Agents think in identifiers and idempotent verbs. Hashes are first-class, every write returns a CID, every command is scriptable, output is machine-parseable (`--json`). No spinners, no confirmations, no surprises. The same operation from a human ("share this photo") and an agent (`clawfs ref add`) hit the same primitives — only the wrapping differs.

One store. Two dialects. Same truth.

---

## CLI UX (git-flavored)

```bash
# Put a blob into the store. Prints CID. Idempotent — same content, same CID.
clawfs put ./report.pdf
# → sha256:9f86d0…  (12.4 MB, deduplicated: matched 2 existing refs)

# Fetch by CID or by human path.
clawfs get sha256:9f86d0… -o ./report.pdf
clawfs get /neil/docs/report.pdf

# Attach a human-readable ref (path or tag) to a CID. Cheap, no copy.
clawfs ref add sha256:9f86d0… /neil/docs/report.pdf
clawfs ref add sha256:9f86d0… --tag quarterly,finance

# List refs, with dedup info.
clawfs ls /neil/docs
clawfs ls --tag finance --json

# Inspect a blob: size, refcount, mime, first-seen, who uploaded.
clawfs stat sha256:9f86d0…

# Remove a ref. Blob stays until refcount hits zero (then GC'd).
clawfs rm /neil/docs/old-report.pdf
clawfs gc --dry-run

# Find by content hash, name, or tag.
clawfs find --name "*.pdf" --since 7d
clawfs find --hash sha256:9f86…   # partial-prefix match, like git

# Share: mint a signed URL for a CID.
clawfs share sha256:9f86d0… --expires 24h
# → https://clawfs.example/s/AbCxYz…

# Pipe-friendly. Stdin/stdout are first-class.
cat backup.tar.zst | clawfs put - --tag backup,nightly
clawfs get sha256:9f86d0… | tar -xz

# Storage stats.
clawfs df
# → 12,847 refs · 3,201 unique blobs · 18.4 GB stored · 71% saved
```

**Conventions**

- Every mutating command prints the resulting CID on stdout.
- `--json` everywhere. Exit codes are meaningful.
- CID prefixes resolve like git (`sha256:9f86` is enough if unambiguous).
- Refs are paths *or* tags — both are just typed pointers to the same blob.
