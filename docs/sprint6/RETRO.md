# Sprint 6 Retro

**Status:** all 4 priorities (P0-P3) shipped in 1 work session. CI green. PR #9.

## Shipped

| Priority | Description | Lines | Tests added |
|---|---|---|---|
| P0 | `smoke-quickstart` daily CI workflow + README badge | 91 | (CI-level) |
| P1 | Admin REST + single-file admin UI + admin token auth | ~600 | +7 |
| P2 | Per-tenant + per-IP rate limit + daily reset + admin CLI extension | ~400 | +8 |
| P3 | Append-only audit log + `clawfs admin audit tail` | ~190 | +3 |

**Tests:** 44 → 62 (+18 net).
**Ruff:** clean.
**Version:** 0.4.0 → 0.5.0.

## What worked

1. **Sub-agent fanout for independent work.** Spawned P1 (admin UI) + P2 (rate limit) in parallel. Each ran ~10 min, no coordination overhead, single trivial conflict in `api.py` (both sides added a middleware block; resolution was 30 seconds).
2. **Sub-agents predicted their own conflict.** P2 sub explicitly noted "I avoided auth.py and admin_ui.html so the sibling branch should merge cleanly" — and P1 sub said the same in reverse. Made manual merge fast.
3. **Dogfood-driven scope.** P0 came directly from Neil's own 4 onboarding breakages in Sprint 5. Ranked it above features. Right call.
4. **TestClient end-to-end coverage.** Each new feature has an E2E test that boots `create_app` and curls it. Catches integration bugs the unit tests miss.

## What didn't / lessons

1. **Same workspace, two writers.** Both sub-agents and I shared `/home/azureuser/work/my-test-bot-repo2`. I committed P0 onto whatever branch was checked out at the moment (turned out to be sub A's branch, not the polish branch I intended). It worked out because everything funnels through merges, but next sprint **each sub-agent should get its own worktree** (`git worktree add`).
2. **README is a perpetual liability.** Even after writing P0 smoke, two of my own commands had broken substring assumptions. The smoke workflow scrapes for *real* endpoints. Lesson: don't write docs ahead of code; write code, then derive docs from the smoke test.
3. **Admin UI served unauthenticated** (the HTML, not the API behind it). This is fine — token-gated fetch is the actual auth — but worth flagging in security docs.
4. **P3 (audit log) was easy because P0/P1/P2 ate all the integration risk first.** When the foundation is clean, the leaf feature is 30 minutes. Build order mattered.

## Deferred to Sprint 7

- **Self-serve signup + Stripe** (only meaningful when there are 5+ users)
- **Cloud-native multipart** (S3 native parts, GCS resumable) — the in-process chunking is fine until someone uploads >100GB
- **Webhooks** (push notifications on uploads/deletes)
- **Audit log retention policy** (right now files live forever)
- **Per-tenant SSO** (OIDC bridge)
- **Worktree-per-subagent pattern** (already noted)

## What Neil should do now (the only thing that matters)

The codebase is ready. Sprint 5 + 6 shipped 7 features in 2 sessions. **Zero of those features have been touched by a real outside user.** Sprint 7 should not start until at least 1 friend has tried the system and told you something hurt — otherwise we're just architecting in a vacuum.

Specifically:
1. **Apply the two demo VM commands in PR #9** (admin token + demo tenant rate limit).
2. **Send `pip install clawfs` + a token to one person you trust.**
3. **Watch what happens. Don't help. Don't explain. Note where they get stuck.**
4. Whatever is in step 3 = Sprint 7's P0.

If after a week step 2 hasn't happened, the answer isn't "build more features", it's "Neil decides if this is actually a product or a portfolio piece." Both are valid; they imply different next sprints.
