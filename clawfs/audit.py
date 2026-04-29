"""Append-only audit log for write operations.

One JSONL file per data root, rotated daily (filename = YYYY-MM-DD.jsonl).
Cheap, greppable, no extra deps. Designed for "what did tenant X do today"
post-hoc debugging.

Schema: {ts, tenant_id, op, ref_path?, hash?, bytes?, ip?, status}
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class AuditLog:
    def __init__(self, root: str):
        self.dir = Path(root) / "audit"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path_for(self, ts: datetime) -> Path:
        return self.dir / f"{ts.strftime('%Y-%m-%d')}.jsonl"

    def write(
        self,
        op: str,
        tenant_id: str,
        *,
        ref_path: Optional[str] = None,
        hash: Optional[str] = None,
        bytes: Optional[int] = None,
        ip: Optional[str] = None,
        status: int = 200,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        ts = datetime.now(timezone.utc)
        entry: dict[str, Any] = {
            "ts": ts.isoformat(),
            "tenant_id": tenant_id,
            "op": op,
            "status": status,
        }
        if ref_path is not None:
            entry["ref_path"] = ref_path
        if hash is not None:
            entry["hash"] = hash
        if bytes is not None:
            entry["bytes"] = bytes
        if ip is not None:
            entry["ip"] = ip
        if extra:
            entry.update(extra)
        line = json.dumps(entry, separators=(",", ":")) + "\n"
        with self._lock:
            with open(self._path_for(ts), "a") as f:
                f.write(line)

    def tail(
        self,
        tenant_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return up to `limit` most-recent entries, newest first."""
        files = sorted(self.dir.glob("*.jsonl"), reverse=True)
        out: list[dict[str, Any]] = []
        for f in files:
            with open(f) as fh:
                lines = fh.readlines()
            for line in reversed(lines):
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if tenant_id and e.get("tenant_id") != tenant_id:
                    continue
                if since:
                    try:
                        ets = datetime.fromisoformat(e["ts"])
                    except (KeyError, ValueError):
                        continue
                    if ets < since:
                        return out
                out.append(e)
                if len(out) >= limit:
                    return out
        return out
