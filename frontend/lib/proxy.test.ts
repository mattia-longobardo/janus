import { describe, expect, it, vi } from "vitest";

import { forward, isCrossSite } from "@/lib/proxy";

const ORIGINS = ["https://janus.example"];

function request(method: string, headers: Record<string, string> = {}, body?: string) {
  return new Request("https://janus.example/api/devices?access=pending", { method, headers, body });
}

describe("isCrossSite", () => {
  it("never blocks reads", () => {
    expect(isCrossSite(request("GET", { origin: "https://evil.example" }), ORIGINS)).toBe(false);
  });

  it("blocks writes from other sites", () => {
    expect(isCrossSite(request("POST", { "sec-fetch-site": "cross-site" }), ORIGINS)).toBe(true);
    expect(isCrossSite(request("DELETE", { origin: "https://evil.example" }), ORIGINS)).toBe(true);
    expect(isCrossSite(request("POST", { origin: "https://janus.example", "sec-fetch-site": "same-origin" }), ORIGINS)).toBe(false);
  });
});

describe("forward", () => {
  it("refuses signed-out requests without calling the backend", async () => {
    const fetcher = vi.fn();
    const response = await forward(request("GET"), ["devices"], { signedIn: false, backend: "http://b", allowedOrigins: ORIGINS, fetcher });
    expect(response.status).toBe(401);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("refuses cross-site writes", async () => {
    const fetcher = vi.fn();
    const response = await forward(request("POST", { origin: "https://evil.example" }, "{}"), ["devices", "x", "block"],
      { signedIn: true, backend: "http://b", allowedOrigins: ORIGINS, fetcher });
    expect(response.status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("adds the internal token and keeps path and query", async () => {
    process.env.JANUS_INTERNAL_TOKEN = "secret-token";
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify([{ id: 1 }]), {
      status: 200, headers: { "content-type": "application/json", "set-cookie": "x=y" },
    }));
    const response = await forward(request("GET", { accept: "application/json", cookie: "session=1" }), ["devices"],
      { signedIn: true, backend: "http://backend:8000", allowedOrigins: ORIGINS, fetcher });
    const [url, init] = fetcher.mock.calls[0];
    expect(String(url)).toBe("http://backend:8000/api/devices?access=pending");
    const headers = init.headers as Headers;
    expect(headers.get("x-janus-internal-token")).toBe("secret-token");
    expect(headers.get("cookie")).toBeNull();
    expect(response.status).toBe(200);
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(await response.json()).toEqual([{ id: 1 }]);
  });

  it("encodes path segments and passes the body of writes", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    await forward(request("POST", { "content-type": "application/json", origin: "https://janus.example" }, '{"a":1}'),
      ["devices", "a b", "approve"], { signedIn: true, backend: "http://b", allowedOrigins: ORIGINS, fetcher });
    const [url, init] = fetcher.mock.calls[0];
    expect(String(url)).toBe("http://b/api/devices/a%20b/approve?access=pending");
    expect(new TextDecoder().decode(init.body as ArrayBuffer)).toBe('{"a":1}');
    expect((init.headers as Headers).get("content-type")).toBe("application/json");
  });

  it("rejects oversized bodies", async () => {
    const fetcher = vi.fn();
    const response = await forward(request("PUT", { origin: "https://janus.example" }, "x".repeat(1_000_001)), ["map", "positions"],
      { signedIn: true, backend: "http://b", allowedOrigins: ORIGINS, fetcher });
    expect(response.status).toBe(413);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("never forwards internal routes from the browser", async () => {
    const fetcher = vi.fn();
    for (const path of [["internal", "auth-config"], ["Internal", "x"], ["internal%2Fauth-config"], ["x", "..", "internal", "a"], ["", "internal", "x"]]) {
      const response = await forward(request("GET"), path, { signedIn: true, backend: "http://b", allowedOrigins: ORIGINS, fetcher });
      expect(response.status).toBe(404);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("never forwards a path that climbs out of /api/", async () => {
    const fetcher = vi.fn();
    for (const path of [["..", "metrics"], ["devices", "..", "..", "healthz"], [".", "..", "x"]]) {
      const response = await forward(request("GET"), path, { signedIn: true, backend: "http://b", allowedOrigins: ORIGINS, fetcher });
      expect(response.status).toBe(404);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rejects malformed percent-encoding without forwarding", async () => {
    const fetcher = vi.fn();
    const response = await forward(request("GET"), ["%E0%A4%A"], { signedIn: true, backend: "http://b", allowedOrigins: ORIGINS, fetcher });
    expect(response.status).toBe(400);
    expect(fetcher).not.toHaveBeenCalled();
  });
});
