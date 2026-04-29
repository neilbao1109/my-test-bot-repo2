import { describe, it, expect, beforeAll } from "vitest";
import { ClawFS } from "../src/index.js";

const URL = process.env.CLAWFS_URL;
const TOKEN = process.env.CLAWFS_TOKEN;
const skip = process.env.CLAWFS_LIVE !== "1" || !URL || !TOKEN;

describe.skipIf(skip)("ClawFS live e2e", () => {
  let fs: ClawFS;
  beforeAll(() => {
    fs = new ClawFS({ baseUrl: URL!, token: TOKEN! });
  });

  it("healthz", async () => {
    const h = await fs.healthz();
    expect(h.status).toBe("ok");
  });

  it("put / get roundtrip", async () => {
    const payload = `ts-sdk hello ${Date.now()}`;
    const { hash } = await fs.put(payload);
    expect(hash).toMatch(/^[0-9a-f]{64}$/);
    const got = await fs.get(hash);
    expect(new TextDecoder().decode(got)).toBe(payload);
  });

  it("link / readRef / share / readShare", async () => {
    const payload = `ts-sdk ref ${Date.now()}`;
    const path = `tssdk/hello-${Date.now()}.txt`;
    const { hash, created } = await fs.link(path, payload);
    expect(created).toBe(true);
    expect(hash).toMatch(/^[0-9a-f]{64}$/);

    const refBytes = await fs.readRef(path);
    expect(new TextDecoder().decode(refBytes)).toBe(payload);

    const { token } = await fs.share(path, 600);
    const shareBytes = await fs.readShare(token);
    expect(new TextDecoder().decode(shareBytes)).toBe(payload);
  });
});
