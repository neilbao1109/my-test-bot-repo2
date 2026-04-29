#!/usr/bin/env bash
# Scripted demo for asciinema — runs entirely against a fresh local clawfs.
set -e

clear

type_out() {
  # type each char with a small delay
  local s="$1"
  for ((i=0; i<${#s}; i++)); do
    printf '%s' "${s:$i:1}"
    sleep 0.02
  done
  printf '\n'
}

cmt() { printf '\033[2m# %s\033[0m\n' "$1"; }

cmt "ClawFS in 90 seconds — install, run, multi-tenant, big-file upload"
sleep 1

cmt "1) install"
type_out "pip install -q clawfs"
pip install -q clawfs >/dev/null 2>&1 || true
sleep 1

cmt "2) start it on a fresh root with one token"
export CLAWFS_API_TOKENS=devtoken
export CLAWFS_ROOT=/tmp/clawfs-demo
rm -rf "$CLAWFS_ROOT"
type_out "uvicorn clawfs.api:app --port 8765 --log-level warning &"
uvicorn clawfs.api:app --port 8765 --log-level warning >/dev/null 2>&1 &
PID=$!
trap "kill $PID 2>/dev/null || true" EXIT
sleep 2

cmt "3) put a file → it gives back the sha256 hash"
type_out "echo 'hello clawfs' | curl -s -H 'Authorization: Bearer devtoken' -F file=@- http://localhost:8765/blobs"
echo 'hello clawfs' | curl -s -H 'Authorization: Bearer devtoken' -F file=@- http://localhost:8765/blobs
echo
sleep 1

cmt "4) name a blob (ref) → idempotent, sha256 dedup is automatic"
type_out "echo 'first version' | curl -s -H 'Authorization: Bearer devtoken' -F file=@- -X PUT http://localhost:8765/refs/notes/today.md"
echo 'first version' | curl -s -H 'Authorization: Bearer devtoken' -F file=@- -X PUT http://localhost:8765/refs/notes/today.md
echo
sleep 1

cmt "5) multi-tenant: create a tenant with quota, hand out a token"
type_out "clawfs --root \$CLAWFS_ROOT admin tenant create alice --quota-bytes 100MiB"
clawfs --root "$CLAWFS_ROOT" admin tenant create alice --quota-bytes 100MiB
sleep 2

cmt "6) check usage"
type_out "clawfs --root \$CLAWFS_ROOT admin tenant list"
clawfs --root "$CLAWFS_ROOT" admin tenant list
sleep 2

cmt "Done. self-host: 'curl …/clawfs-up.sh | bash'  •  pip: 'pip install clawfs'  •  npm: '@neilbao/clawfs-sdk'"
sleep 2
