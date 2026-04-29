# Quickstart — VM

Take any fresh Ubuntu 22/24 or Debian 12 VM and turn it into a production-ready ClawFS deployment with HTTPS in under 10 minutes.

## With your own domain (recommended)

Point an A record from `clawfs.example.com` to the VM's public IP, then on the VM:

```bash
curl -fsSL https://get.clawfs.dev | sudo bash -s -- \
  --domain clawfs.example.com \
  --email you@example.com
```

The script:
1. installs Docker if missing
2. pulls `ghcr.io/clawfs/clawfs:latest`
3. starts ClawFS with `local` backend on `/var/lib/clawfs`
4. fronts it with [Caddy](https://caddyserver.com/) (auto-HTTPS via Let's Encrypt)
5. generates a 32-char API token
6. prints the URL + token + a curl example

```
✔ ClawFS is running.

  URL:    https://clawfs.example.com
  Token:  fVl6FquBaZxy3xQtJpVLudlf4kgZXHx
  Data:   /var/lib/clawfs
  Config: /opt/clawfs
```

## Without a domain (local / private)

```bash
curl -fsSL https://get.clawfs.dev | sudo bash
```

Plain HTTP on port 80, useful for VPN-only or LAN deployments.

## Bring-your-own reverse proxy

Don't want Caddy? Run the container directly and front it with whatever you already use:

```bash
docker run -d --restart=unless-stopped \
  -v /var/lib/clawfs:/data \
  -e CLAWFS_API_TOKENS="$(cat /etc/clawfs/token)" \
  -p 127.0.0.1:8000:8000 \
  ghcr.io/clawfs/clawfs:latest
```

Then proxy `https://yourdomain → 127.0.0.1:8000` from nginx / Traefik / Cloudflare Tunnel / whatever.

## Verified

We dogfood this on a fresh `Standard_B2s` Ubuntu 24.04 VM in Azure central India on every release. Time-to-healthz on the second run (Docker already installed): **~36 seconds.**
