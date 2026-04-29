# Quickstart — Cloud

ClawFS is cloud-optional but cloud-friendly. Three patterns:

## Azure Container Apps + Azure Blob

```bash
RG=clawfs-rg
LOC=centralindia
az group create -g $RG -l $LOC

az deployment group create -g $RG \
  --template-file azure/container-app.bicep \
  --parameters image=ghcr.io/clawfs/clawfs:latest
```

The bicep template provisions a storage account, log analytics workspace, container apps environment, and the app itself with a system-assigned managed identity. RBAC for blob access (`Storage Blob Data Contributor`) and ACR pull (`AcrPull`) are wired automatically — **no admin keys, no connection strings**.

Set `CLAWFS_API_TOKENS` to your write token before exposing.

## AWS / S3-compatible

Point ClawFS at any S3 endpoint (AWS, MinIO, R2, B2):

```bash
docker run -d --restart=unless-stopped \
  -e CLAWFS_BACKEND=s3 \
  -e CLAWFS_S3_BUCKET=my-clawfs-bucket \
  -e CLAWFS_S3_REGION=us-west-2 \
  -e AWS_ACCESS_KEY_ID=… -e AWS_SECRET_ACCESS_KEY=… \
  -e CLAWFS_API_TOKENS=… \
  -p 8000:8000 \
  ghcr.io/clawfs/clawfs:latest
```

For MinIO / R2 / B2, also set `CLAWFS_S3_ENDPOINT_URL=https://your-endpoint`.

For IRSA on EKS, just omit the keys — boto3 will pick up the pod identity automatically.

## Kubernetes (Helm)

The [Helm chart](../../charts/clawfs/) ships a Deployment + Service + PVC for the local backend, with one toggle for s3/azure/gcs backends.

```bash
helm install clawfs ./charts/clawfs \
  --set apiTokens=$(openssl rand -hex 16) \
  --set local.persistence.size=20Gi
```

Verified end-to-end on a [kind](https://kind.sigs.k8s.io/) cluster: PVC bound, pod ready, healthz + put/get blob roundtrip OK.

For S3-backed multi-replica:

```bash
helm install clawfs ./charts/clawfs \
  --set backend=s3 \
  --set s3.bucket=my-clawfs-bucket --set s3.region=us-west-2 \
  --set s3.existingSecret=aws-creds \
  --set replicaCount=3 \
  --set apiTokens=…
```

## Google Cloud Storage

```bash
docker run -d --restart=unless-stopped \
  -e CLAWFS_BACKEND=gcs \
  -e CLAWFS_GCS_BUCKET=my-clawfs-bucket \
  -e GOOGLE_APPLICATION_CREDENTIALS=/etc/gcs/key.json \
  -v /etc/gcs:/etc/gcs:ro \
  -e CLAWFS_API_TOKENS=… \
  -p 8000:8000 \
  ghcr.io/clawfs/clawfs:latest
```

On GKE with Workload Identity, omit the key file — ADC will pick up the pod identity.
