/**
 * @neilbao/clawfs-sdk — TypeScript client for ClawFS.
 *
 * Pure HTTP, no cloud-vendor dependencies. Mirrors the Python SDK contract:
 *   fs.put / fs.get / fs.link / fs.share
 *
 * sha256 dedup + Idempotency-Key for safe retries.
 */

export interface ClawFSOptions {
  /** Base URL of the ClawFS deployment, e.g. "https://clawfs.example.com" */
  baseUrl: string;
  /** Bearer token for write endpoints. Read endpoints work without it if the server allows. */
  token?: string;
  /** Optional fetch override (for tests, undici, edge runtimes). */
  fetch?: typeof fetch;
  /** Per-request timeout ms (default 30s). */
  timeoutMs?: number;
}

export interface PutBlobResult {
  hash: string;
}

export interface PutRefResult {
  path: string;
  hash: string;
  created: boolean;
}

export interface RefEntry {
  path: string;
  hash: string;
  updated_at: string;
}

export interface ShareResult {
  token: string;
  url: string;
}

export class ClawFSError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status?: number,
    public readonly retryable: boolean = false,
  ) {
    super(message);
    this.name = "ClawFSError";
  }
}

const RETRYABLE_STATUS = new Set([408, 429, 500, 502, 503, 504]);

export class ClawFS {
  private readonly baseUrl: string;
  private readonly token?: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;

  constructor(opts: ClawFSOptions) {
    if (!opts.baseUrl) throw new ClawFSError("config", "baseUrl required");
    this.baseUrl = opts.baseUrl.replace(/\/+$/, "");
    this.token = opts.token;
    this.fetchImpl = opts.fetch ?? globalThis.fetch;
    this.timeoutMs = opts.timeoutMs ?? 30_000;
  }

  // ---------- public API ----------

  /** Put a raw blob. Returns its sha256 hash. */
  async put(data: Uint8Array | string): Promise<PutBlobResult> {
    const bytes = typeof data === "string" ? new TextEncoder().encode(data) : data;
    const idem = await sha256Hex(bytes);
    const form = new FormData();
    form.append("file", new Blob([bytes as unknown as ArrayBuffer]), "blob");
    return this.json<PutBlobResult>("PUT", "/blobs", {
      body: form,
      idempotencyKey: idem,
      auth: true,
    });
  }

  /** Get a blob by sha256 hash. */
  async get(hash: string): Promise<Uint8Array> {
    const res = await this.raw("GET", `/blobs/${hash}`, { auth: false });
    if (res.status === 404) throw new ClawFSError("not_found", `blob ${hash} not found`, 404);
    if (!res.ok) throw await toError(res);
    const buf = await res.arrayBuffer();
    return new Uint8Array(buf);
  }

  /**
   * Link a path to a blob (named ref).
   * Roundtrip equivalent of: PUT /refs/{path} + multipart file.
   */
  async link(path: string, data: Uint8Array | string): Promise<PutRefResult> {
    const bytes = typeof data === "string" ? new TextEncoder().encode(data) : data;
    const idem = await sha256Hex(bytes);
    const form = new FormData();
    form.append("file", new Blob([bytes as unknown as ArrayBuffer]), "ref");
    return this.json<PutRefResult>("PUT", `/refs/${encodePath(path)}`, {
      body: form,
      idempotencyKey: idem,
      auth: true,
    });
  }

  /** Resolve a ref to its bytes. */
  async readRef(path: string): Promise<Uint8Array> {
    const res = await this.raw("GET", `/refs/${encodePath(path)}`, { auth: false });
    if (res.status === 404) throw new ClawFSError("not_found", `ref ${path} not found`, 404);
    if (!res.ok) throw await toError(res);
    return new Uint8Array(await res.arrayBuffer());
  }

  /** List refs by prefix. */
  async listRefs(prefix = ""): Promise<RefEntry[]> {
    const q = prefix ? `?prefix=${encodeURIComponent(prefix)}` : "";
    return this.json<RefEntry[]>("GET", `/refs${q}`, { auth: false });
  }

  /** Delete a ref. */
  async unlink(path: string): Promise<void> {
    const res = await this.raw("DELETE", `/refs/${encodePath(path)}`, { auth: true });
    if (res.status === 404) throw new ClawFSError("not_found", `ref ${path} not found`, 404);
    if (!res.ok) throw await toError(res);
  }

  /** Create a share token for a ref. */
  async share(refPath: string, ttlSeconds?: number): Promise<ShareResult> {
    const form = new FormData();
    form.append("ref_path", refPath);
    if (ttlSeconds !== undefined) form.append("ttl_seconds", String(ttlSeconds));
    return this.json<ShareResult>("POST", "/shares", { body: form, auth: true });
  }

  /** Resolve a share token to bytes (no auth needed). */
  async readShare(token: string): Promise<Uint8Array> {
    const res = await this.raw("GET", `/shares/${token}`, { auth: false });
    if (res.status === 404) throw new ClawFSError("not_found", `share ${token} not found`, 404);
    if (!res.ok) throw await toError(res);
    return new Uint8Array(await res.arrayBuffer());
  }

  /** Server liveness. */
  async healthz(): Promise<{ status: string; uptime_seconds: number }> {
    return this.json<{ status: string; uptime_seconds: number }>("GET", "/healthz", { auth: false });
  }

  // ---------- chunked / multipart upload (Sprint 4) ----------

  /**
   * Stream a large blob in fixed-size parts so we never buffer the whole
   * thing in memory on either side.
   *
   * `source` may be a Uint8Array (for tests / small things) or a
   * ReadableStream<Uint8Array>. `partSize` defaults to 8 MiB. If `targetRef`
   * is set, the upload is bound to that ref on completion.
   */
  async putLarge(
    source: Uint8Array | ReadableStream<Uint8Array>,
    opts: { partSize?: number; targetRef?: string } = {},
  ): Promise<{ hash: string; size: number; created: boolean }> {
    const partSize = opts.partSize ?? 8 * 1024 * 1024;

    // 1. create session
    const create = new FormData();
    if (opts.targetRef) create.append("target_ref", opts.targetRef);
    const sess = await this.json<{ id: string }>("POST", "/uploads", { body: create, auth: true });
    const id = sess.id;

    // 2. stream parts
    const reader = toReader(source, partSize);
    let n = 0;
    try {
      for await (const chunk of reader) {
        n += 1;
        const res = await this.raw("PUT", `/uploads/${id}/parts/${n}`, {
          body: chunk as unknown as BodyInit,
          auth: true,
        });
        if (!res.ok) throw await toError(res);
      }
    } catch (e) {
      try { await this.raw("DELETE", `/uploads/${id}`, { auth: true }); } catch { /* best-effort */ }
      throw e;
    }
    if (n === 0) throw new ClawFSError("empty", "no data to upload");

    // 3. complete
    const done = await this.json<{ hash: string; size: number; blob_created: boolean }>(
      "POST", `/uploads/${id}/complete`, { auth: true },
    );
    return { hash: done.hash, size: done.size, created: done.blob_created };
  }

  // ---------- internals ----------

  private async json<T>(
    method: string,
    path: string,
    opts: { body?: BodyInit; idempotencyKey?: string; auth: boolean },
  ): Promise<T> {
    const res = await this.raw(method, path, opts);
    if (!res.ok) throw await toError(res);
    return (await res.json()) as T;
  }

  private async raw(
    method: string,
    path: string,
    opts: { body?: BodyInit; idempotencyKey?: string; auth: boolean },
  ): Promise<Response> {
    const headers: Record<string, string> = {};
    if (opts.auth && this.token) headers["Authorization"] = `Bearer ${this.token}`;
    if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.timeoutMs);
    try {
      return await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers,
        body: opts.body,
        signal: ctrl.signal,
      });
    } finally {
      clearTimeout(timer);
    }
  }
}

// ---------- helpers ----------

async function* toReader(
  source: Uint8Array | ReadableStream<Uint8Array>,
  partSize: number,
): AsyncIterable<Uint8Array> {
  if (source instanceof Uint8Array) {
    for (let off = 0; off < source.length; off += partSize) {
      yield source.subarray(off, Math.min(off + partSize, source.length));
    }
    return;
  }
  // Re-chunk an arbitrary ReadableStream into exactly partSize buckets.
  const reader = source.getReader();
  let buf = new Uint8Array(0);
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    if (!value || value.length === 0) continue;
    const merged = new Uint8Array(buf.length + value.length);
    merged.set(buf, 0); merged.set(value, buf.length);
    buf = merged;
    while (buf.length >= partSize) {
      yield buf.subarray(0, partSize);
      buf = buf.subarray(partSize);
    }
  }
  if (buf.length > 0) yield buf;
}

function encodePath(p: string): string {
  return p.split("/").map(encodeURIComponent).join("/");
}

async function sha256Hex(data: Uint8Array): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", data as unknown as ArrayBuffer);
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function toError(res: Response): Promise<ClawFSError> {
  let detail = res.statusText;
  try {
    const j = (await res.json()) as { detail?: string };
    if (j?.detail) detail = j.detail;
  } catch {
    /* not json, ignore */
  }
  const code =
    res.status === 401 ? "unauthorized" : res.status === 404 ? "not_found" : `http_${res.status}`;
  return new ClawFSError(code, detail, res.status, RETRYABLE_STATUS.has(res.status));
}

export default ClawFS;
