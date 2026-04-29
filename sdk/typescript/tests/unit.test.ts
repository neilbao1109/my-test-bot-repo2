import { describe, it, expect, vi } from "vitest";
import { ClawFS, ClawFSError } from "../src/index.js";

function mockResponse(body: unknown, init: { status?: number; headers?: Record<string, string> } = {}): Response {
  const status = init.status ?? 200;
  const isJson = typeof body !== "string" && !(body instanceof Uint8Array);
  const payload =
    body instanceof Uint8Array
      ? body
      : isJson
      ? JSON.stringify(body)
      : (body as string);
  return new Response(payload as BodyInit, {
    status,
    headers: { "content-type": isJson ? "application/json" : "application/octet-stream", ...(init.headers ?? {}) },
  });
}

describe("ClawFS unit", () => {
  it("put sends auth + Idempotency-Key + multipart", async () => {
    const captured: { url?: string; init?: RequestInit } = {};
    const fakeFetch = vi.fn(async (url: string, init: RequestInit) => {
      captured.url = url;
      captured.init = init;
      return mockResponse({ hash: "abc123" });
    });
    const fs = new ClawFS({
      baseUrl: "https://example.com",
      token: "tok",
      fetch: fakeFetch as unknown as typeof fetch,
    });
    const r = await fs.put("hello world");
    expect(r.hash).toBe("abc123");
    expect(captured.url).toBe("https://example.com/blobs");
    const headers = captured.init?.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer tok");
    expect(headers["Idempotency-Key"]).toMatch(/^[0-9a-f]{64}$/);
    expect(captured.init?.method).toBe("PUT");
    expect(captured.init?.body).toBeInstanceOf(FormData);
  });

  it("404 throws not_found", async () => {
    const fakeFetch = vi.fn(async () =>
      mockResponse({ detail: "blob not found" }, { status: 404 }),
    );
    const fs = new ClawFS({ baseUrl: "https://x", fetch: fakeFetch as unknown as typeof fetch });
    await expect(fs.get("deadbeef")).rejects.toMatchObject({ code: "not_found", status: 404 });
  });

  it("503 marks retryable", async () => {
    const fakeFetch = vi.fn(async () =>
      mockResponse({ detail: "down" }, { status: 503 }),
    );
    const fs = new ClawFS({
      baseUrl: "https://x",
      token: "t",
      fetch: fakeFetch as unknown as typeof fetch,
    });
    try {
      await fs.put("x");
      throw new Error("should have thrown");
    } catch (e) {
      const err = e as ClawFSError;
      expect(err.retryable).toBe(true);
      expect(err.status).toBe(503);
    }
  });

  it("trims trailing slash on baseUrl", async () => {
    const captured: { url?: string } = {};
    const fakeFetch = vi.fn(async (url: string) => {
      captured.url = url;
      return mockResponse({ status: "ok", uptime_seconds: 1 });
    });
    const fs = new ClawFS({ baseUrl: "https://x///", fetch: fakeFetch as unknown as typeof fetch });
    await fs.healthz();
    expect(captured.url).toBe("https://x/healthz");
  });
});
