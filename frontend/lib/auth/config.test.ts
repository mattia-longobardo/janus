import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const GOOD = {
  allowed_emails: ["me@example.org"],
  providers: [{ id: "authentik", name: "Authentik", discovery_url: "https://idp/.well-known/openid-configuration", client_id: "c", client_secret: "s", scopes: ["openid"] }],
  version: "v1",
};

async function load() {
  vi.resetModules();
  return import("@/lib/auth/config");
}

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("fetchAuthConfig", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-03T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("reads the internal endpoint with the internal token and caches it for 15 s", async () => {
    const fetcher = vi.fn(async () => respond(GOOD));
    vi.stubGlobal("fetch", fetcher);
    const { fetchAuthConfig } = await load();

    expect(await fetchAuthConfig()).toEqual(GOOD);
    expect(await fetchAuthConfig()).toEqual(GOOD);
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/internal\/auth-config$/);
    expect(new Headers(init.headers).has("x-janus-internal-token")).toBe(true);

    vi.advanceTimersByTime(15_001);
    await fetchAuthConfig();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("falls back to an empty offline config when the backend never answered", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("ECONNREFUSED"); }));
    const { fetchAuthConfig } = await load();
    expect(await fetchAuthConfig()).toEqual({ allowed_emails: [], providers: [], version: "offline" });
  });

  it("keeps the last good config when the backend fails or answers garbage", async () => {
    const fetcher = vi.fn(async () => respond(GOOD));
    vi.stubGlobal("fetch", fetcher);
    const { fetchAuthConfig } = await load();
    await fetchAuthConfig();

    fetcher.mockImplementation(async () => respond({ detail: "boom" }, 500));
    vi.advanceTimersByTime(15_001);
    expect(await fetchAuthConfig()).toEqual(GOOD);

    fetcher.mockImplementation(async () => respond({ providers: "nope" }));
    vi.advanceTimersByTime(15_001);
    expect(await fetchAuthConfig()).toEqual(GOOD);
  });
});

describe("authDatabaseUrl", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("prefers AUTH_DATABASE_URL and otherwise strips the driver from JANUS_DATABASE_URL", async () => {
    const { authDatabaseUrl } = await load();
    vi.stubEnv("AUTH_DATABASE_URL", "postgresql://a@h/db");
    vi.stubEnv("JANUS_DATABASE_URL", "postgresql+psycopg://j@h/janus");
    expect(authDatabaseUrl()).toBe("postgresql://a@h/db");
    vi.stubEnv("AUTH_DATABASE_URL", "");
    expect(authDatabaseUrl()).toBe("postgresql://j@h/janus");
  });
});
