#!/usr/bin/env bash
# clawfs-up — one-command deploy of ClawFS on a fresh Linux box.
#
# Usage:
#   curl -fsSL https://get.clawfs.dev | bash
#   curl -fsSL https://get.clawfs.dev | bash -s -- --domain clawfs.example.com --email you@example.com
#
# Or download and run with flags:
#   ./clawfs-up.sh --domain clawfs.example.com --email you@example.com
#   ./clawfs-up.sh                              # plain HTTP on :80 (dev/local)
#
# Supported: Ubuntu 22.04 / 24.04, Debian 12.
# Backend: local disk at /var/lib/clawfs (no cloud-vendor lock-in).
set -euo pipefail

CLAWFS_IMAGE="${CLAWFS_IMAGE:-ghcr.io/clawfs/clawfs:latest}"
CLAWFS_DIR="${CLAWFS_DIR:-/opt/clawfs}"
CLAWFS_DATA="${CLAWFS_DATA:-/var/lib/clawfs}"
DOMAIN=""
EMAIL=""
SOURCE_REPO=""
SOURCE_REF="main"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --email)  EMAIL="$2";  shift 2 ;;
    --image)  CLAWFS_IMAGE="$2"; shift 2 ;;
    --source) SOURCE_REPO="$2"; shift 2 ;;
    --ref)    SOURCE_REF="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 1 ;;
  esac
done

log()  { printf "\033[1;36m[clawfs]\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m[clawfs:err]\033[0m %s\n" "$*" >&2; exit 1; }

# ---------- 0. require root ----------
if [[ $EUID -ne 0 ]]; then
  exec sudo -E bash "$0" "$@"
fi

# ---------- 1. detect OS ----------
. /etc/os-release
case "${ID:-}:${VERSION_ID:-}" in
  ubuntu:22.04|ubuntu:24.04|debian:12) log "OS ${PRETTY_NAME} ✓" ;;
  *) fail "Unsupported OS: ${PRETTY_NAME:-unknown}. Supported: Ubuntu 22.04/24.04, Debian 12." ;;
esac

# ---------- 2. install docker if missing ----------
if ! command -v docker >/dev/null 2>&1; then
  log "Installing Docker..."
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/${ID}/gpg" | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable --now docker
fi
log "Docker $(docker --version | awk '{print $3}' | tr -d ',') ✓"

# ---------- 2b. optional: build image from source ----------
if [[ -n "$SOURCE_REPO" ]]; then
  command -v git >/dev/null 2>&1 || apt-get install -y -qq git
  SRC_DIR="$CLAWFS_DIR/src"
  if [[ ! -d "$SRC_DIR/.git" ]]; then
    log "Cloning $SOURCE_REPO@$SOURCE_REF"
    git clone --depth 1 --branch "$SOURCE_REF" "$SOURCE_REPO" "$SRC_DIR"
  else
    (cd "$SRC_DIR" && git fetch --depth 1 origin "$SOURCE_REF" && git reset --hard FETCH_HEAD)
  fi
  CLAWFS_IMAGE="clawfs:source-$(cd "$SRC_DIR" && git rev-parse --short HEAD)"
  log "Building $CLAWFS_IMAGE from source..."
  docker build -q -t "$CLAWFS_IMAGE" "$SRC_DIR" >/dev/null
fi

# ---------- 3. token + dirs ----------
mkdir -p "$CLAWFS_DIR" "$CLAWFS_DATA"
TOKEN_FILE="$CLAWFS_DIR/api-token"
if [[ ! -s "$TOKEN_FILE" ]]; then
  TOKEN=$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 32)
  echo "$TOKEN" > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE"
fi
TOKEN=$(cat "$TOKEN_FILE")

# ---------- 4. write compose + Caddyfile ----------
if [[ -n "$DOMAIN" ]]; then
  [[ -n "$EMAIL" ]] || fail "--domain requires --email (for Let's Encrypt)"
  log "TLS mode: Caddy + Let's Encrypt for $DOMAIN"
  cat > "$CLAWFS_DIR/Caddyfile" <<EOF
{
  email $EMAIL
}
$DOMAIN {
  reverse_proxy clawfs:8000
  encode gzip
}
EOF
  cat > "$CLAWFS_DIR/docker-compose.yml" <<EOF
services:
  clawfs:
    image: $CLAWFS_IMAGE
    restart: unless-stopped
    environment:
      CLAWFS_BACKEND: local
      CLAWFS_ROOT: /data
      CLAWFS_API_TOKENS: "$TOKEN"
    volumes:
      - $CLAWFS_DATA:/data
    expose: ["8000"]
  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - $CLAWFS_DIR/Caddyfile:/etc/caddy/Caddyfile:ro
      - $CLAWFS_DIR/caddy_data:/data
      - $CLAWFS_DIR/caddy_config:/config
    depends_on: [clawfs]
EOF
  PUBLIC_URL="https://$DOMAIN"
else
  log "TLS mode: plain HTTP on :80 (no --domain). Use --domain for HTTPS in prod."
  cat > "$CLAWFS_DIR/docker-compose.yml" <<EOF
services:
  clawfs:
    image: $CLAWFS_IMAGE
    restart: unless-stopped
    environment:
      CLAWFS_BACKEND: local
      CLAWFS_ROOT: /data
      CLAWFS_API_TOKENS: "$TOKEN"
    volumes:
      - $CLAWFS_DATA:/data
    ports: ["80:8000"]
EOF
  PUBLIC_URL="http://$(hostname -I | awk '{print $1}')"
fi

# ---------- 5. up ----------
if [[ -z "$SOURCE_REPO" ]]; then
  log "Pulling image $CLAWFS_IMAGE ..."
  docker compose -f "$CLAWFS_DIR/docker-compose.yml" pull -q clawfs
fi
log "Starting ClawFS..."
docker compose -f "$CLAWFS_DIR/docker-compose.yml" up -d

# ---------- 6. wait for healthz ----------
log "Waiting for /healthz ..."
for i in {1..30}; do
  CID=$(docker compose -f "$CLAWFS_DIR/docker-compose.yml" ps -q clawfs 2>/dev/null)
  if [[ -n "$CID" ]] && docker exec "$CID" python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2).status==200 else 1)" 2>/dev/null; then
    log "healthz ✓"
    break
  fi
  sleep 2
done

# ---------- 7. summary ----------
cat <<EOF

\033[1;32m✔ ClawFS is running.\033[0m

  URL:    $PUBLIC_URL
  Token:  $TOKEN
  Data:   $CLAWFS_DATA
  Config: $CLAWFS_DIR

Try it:
  curl -H "Authorization: Bearer $TOKEN" \\
    -X PUT -F file=@/etc/hostname $PUBLIC_URL/blobs

Logs:    docker compose -f $CLAWFS_DIR/docker-compose.yml logs -f
Stop:    docker compose -f $CLAWFS_DIR/docker-compose.yml down
Update:  docker compose -f $CLAWFS_DIR/docker-compose.yml pull && \\
         docker compose -f $CLAWFS_DIR/docker-compose.yml up -d

EOF
