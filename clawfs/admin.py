"""`clawfs admin` — operator CLI for tenant + token management.

Talks directly to the local SQLite metadata DB. Designed to be run as either:

  $ clawfs admin tenant create --name acme --quota-bytes 10GiB
  $ docker exec clawfs clawfs admin tenant list
"""
from __future__ import annotations

import argparse
import re
import secrets
import sys
from typing import Optional

from .core import ClawFS

_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMGTP]?I?B?)\s*$", re.IGNORECASE)
_UNITS = {
    "": 1, "B": 1,
    "KB": 1_000, "KIB": 1024,
    "MB": 1_000_000, "MIB": 1024**2,
    "GB": 1_000_000_000, "GIB": 1024**3,
    "TB": 1_000_000_000_000, "TIB": 1024**4,
}


def parse_size(s: str) -> int:
    """Parse '10GiB' / '500MB' / '1024' → bytes."""
    m = _SIZE_RE.match(s)
    if not m:
        raise ValueError(f"can't parse size: {s!r}")
    n, unit = m.groups()
    unit = unit.upper().rstrip("B") + ("IB" if unit.upper().endswith("IB") else "B" if unit else "")
    # Easier: just normalize via the table directly.
    key = (unit or "B")
    if key not in _UNITS:
        # try exact match
        key = m.group(2).upper()
        if key not in _UNITS:
            raise ValueError(f"unknown unit in {s!r}")
    return int(float(n) * _UNITS[key])


def fmt_size(n: Optional[int]) -> str:
    if n is None:
        return "∞"
    for unit, div in [("TiB", 1024**4), ("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)]:
        if n >= div:
            return f"{n/div:.2f} {unit}"
    return f"{n} B"


def _fs(root: str) -> ClawFS:
    return ClawFS.local(root)


# ---------- commands ----------

def cmd_tenant_create(args) -> int:
    fs = _fs(args.root)
    token = args.token or f"sk_{secrets.token_urlsafe(24)}"
    max_b = parse_size(args.quota_bytes) if args.quota_bytes else None
    t = fs.upsert_tenant(
        args.id,
        name=args.name or args.id,
        tokens=[token],
        max_bytes=max_b,
        max_objects=args.quota_objects,
        rate_limit_per_minute=args.rate_limit,
        daily_reset=args.daily_reset,
    )
    print(f"✅ created tenant {t.id!r} ({t.name})")
    print(f"   token: {token}")
    print(f"   quota: {fmt_size(t.max_bytes)} / {t.max_objects or '∞'} objects")
    print(f"   rate_limit: {t.rate_limit_per_minute or '∞'}/min   daily_reset: {t.daily_reset}")
    return 0


def cmd_tenant_list(args) -> int:
    fs = _fs(args.root)
    from sqlmodel import Session, select
    from .db import Tenant
    with Session(fs.engine) as s:
        rows = list(s.exec(select(Tenant)))
    if not rows:
        print("(no tenants)")
        return 0
    print(f"{'ID':<20} {'NAME':<20} {'USED':<14} {'QUOTA':<14} {'OBJECTS':<10} {'TOKENS':<6} {'RATE':<8} {'DAILY':<6}")
    for t in rows:
        ntok = len([x for x in (t.tokens_csv or '').split(',') if x.strip()])
        rate = f"{t.rate_limit_per_minute}/m" if t.rate_limit_per_minute else "∞"
        daily = "yes" if t.daily_reset else "no"
        print(f"{t.id:<20} {t.name:<20} {fmt_size(t.used_bytes):<14} {fmt_size(t.max_bytes):<14} "
              f"{t.used_objects}/{t.max_objects or '∞':<6} {ntok:<6} {rate:<8} {daily:<6}")
    return 0


def cmd_tenant_rotate(args) -> int:
    fs = _fs(args.root)
    new_token = f"sk_{secrets.token_urlsafe(24)}"
    fs.upsert_tenant(args.id, tokens=[new_token])
    print(f"✅ rotated tenant {args.id!r}")
    print(f"   new token: {new_token}")
    return 0


def cmd_tenant_set_quota(args) -> int:
    fs = _fs(args.root)
    max_b = parse_size(args.bytes) if args.bytes else None
    fs.upsert_tenant(
        args.id,
        max_bytes=max_b,
        max_objects=args.objects,
        rate_limit_per_minute=args.rate_limit,
        daily_reset=args.daily_reset,
    )
    u = fs.get_usage(args.id)
    print(f"✅ updated quota for {args.id!r}: bytes={fmt_size(u['max_bytes'])} objects={u['max_objects'] or '∞'}")
    if args.rate_limit is not None:
        print(f"   rate_limit: {args.rate_limit or '∞'}/min")
    if args.daily_reset is not None:
        print(f"   daily_reset: {args.daily_reset}")
    return 0


def cmd_tenant_delete(args) -> int:
    fs = _fs(args.root)
    from sqlmodel import Session
    from .db import Tenant
    with Session(fs.engine) as s:
        t = s.get(Tenant, args.id)
        if t is None:
            print(f"❌ no such tenant: {args.id}", file=sys.stderr)
            return 1
        s.delete(t)
        s.commit()
    print(f"✅ deleted tenant {args.id!r} (refs/blobs left intact; run 'clawfs admin gc' to reclaim)")
    return 0


def cmd_usage(args) -> int:
    fs = _fs(args.root)
    print(fs.get_usage(args.id))
    return 0


# ---------- entrypoint ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clawfs admin", description="ClawFS operator CLI")
    p.add_argument("--root", default="./clawfs-data", help="data root (default: ./clawfs-data)")

    sub = p.add_subparsers(dest="cmd", required=True)
    tn = sub.add_parser("tenant", help="tenant management")
    tnsub = tn.add_subparsers(dest="tcmd", required=True)

    c = tnsub.add_parser("create")
    c.add_argument("id")
    c.add_argument("--name", help="display name (default = id)")
    c.add_argument("--token", help="explicit token (default: auto-generated)")
    c.add_argument("--quota-bytes", help="max bytes (e.g. 10GiB, 500MB)")
    c.add_argument("--quota-objects", type=int, help="max distinct blobs")
    c.add_argument("--rate-limit", type=int, default=None,
                   help="requests per minute (per tenant+IP); 0 or omit = unlimited")
    c.add_argument("--daily-reset", dest="daily_reset", action="store_true", default=None,
                   help="reset usage at UTC midnight (demo tenants)")
    c.add_argument("--no-daily-reset", dest="daily_reset", action="store_false")
    c.set_defaults(func=cmd_tenant_create)

    lst = tnsub.add_parser("list")
    lst.set_defaults(func=cmd_tenant_list)

    r = tnsub.add_parser("rotate-token")
    r.add_argument("id")
    r.set_defaults(func=cmd_tenant_rotate)

    sq = tnsub.add_parser("set-quota")
    sq.add_argument("id")
    sq.add_argument("--bytes", help="max bytes (e.g. 10GiB)")
    sq.add_argument("--objects", type=int)
    sq.add_argument("--rate-limit", type=int, default=None,
                    help="requests per minute (per tenant+IP); 0 = unlimited")
    sq.add_argument("--daily-reset", dest="daily_reset", action="store_true", default=None,
                    help="reset usage at UTC midnight")
    sq.add_argument("--no-daily-reset", dest="daily_reset", action="store_false")
    sq.set_defaults(func=cmd_tenant_set_quota)

    d = tnsub.add_parser("delete")
    d.add_argument("id")
    d.set_defaults(func=cmd_tenant_delete)

    u = sub.add_parser("usage")
    u.add_argument("id")
    u.set_defaults(func=cmd_usage)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
