import { afterEach, describe, expect, it, vi } from "vitest";

import { probeDiscovery } from "@/lib/auth/discovery";

const URL = "https://idp.example/.well-known/openid-configuration";

describe("probeDiscovery", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("accepts a document with authorization and token endpoints", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ authorization_endpoint: "a", token_endpoint: "t" })));
    expect(await probeDiscovery(URL)).toBeNull();
  });

  it("reports HTTP errors, unusable documents and network failures", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("nope", { status: 404 })));
    expect(await probeDiscovery(URL)).toBe("HTTP 404");
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ issuer: "x" })));
    expect(await probeDiscovery(URL)).toMatch(/no authorization or token endpoint/);
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }));
    expect(await probeDiscovery(URL)).toBe("fetch failed");
  });
});
