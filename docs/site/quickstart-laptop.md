# Quickstart — Laptop

Run ClawFS in 60 seconds with Docker.

```bash
docker run --rm -p 8000:8000 \
  -v $PWD/clawfs-data:/data \
  -e CLAWFS_API_TOKENS=devtoken \
  ghcr.io/clawfs/clawfs:latest
```

Then in another shell:

```bash
echo "hello" > /tmp/h.txt
curl -H "Authorization: Bearer devtoken" \
  -X PUT -F file=@/tmp/h.txt http://localhost:8000/blobs
# → {"hash":"..."}

curl http://localhost:8000/blobs/<hash>
# → hello
```

That's it. Data persists in `./clawfs-data`. Backend is `local` (disk).

For HTTPS, a domain, and prod-style restart-on-reboot, jump to [Quickstart — VM](./quickstart-vm.md).
