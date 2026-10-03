import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthConfig } from "@/lib/auth/config";

type Row = { id: string; role: string | null; banned?: boolean | null; banExpires?: Date | null };
type HookCtx = { path: string; body?: unknown };
type BuiltOptions = { hooks: { before: (ctx: HookCtx) => Promise<unknown> } };

const { betterAuth, genericOAuth, fetchAuthConfig, query } = vi.hoisted(() => ({
  betterAuth: vi.fn((options: unknown) => ({ options })),
  genericOAuth: vi.fn((options: { config: { providerId: string }[] }) => ({ id: "generic-oauth", options })),
  fetchAuthConfig: vi.fn<() => Promise<AuthConfig>>(),
  query: vi.fn<(sql: string, params?: unknown[]) => Promise<{ rows: Row[] }>>(),
}));

vi.mock("server-only", () => ({}));
vi.mock("pg", () => ({ Pool: class { query = query; } }));
vi.mock("better-auth", () => ({ betterAuth }));
// The middleware wrapper is better-auth's plumbing; the hook body is what is under test.
vi.mock("better-auth/api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  createAuthMiddleware: (fn: unknown) => fn,
}));
vi.mock("better-auth/next-js", () => ({ nextCookies: () => ({ id: "next-cookies" }) }));
vi.mock("better-auth/plugins", () => ({ admin: () => ({ id: "admin" }), username: () => ({ id: "username" }), genericOAuth }));
vi.mock("@/lib/auth/config", async (importOriginal) => ({ ...(await importOriginal<object>()), fetchAuthConfig }));

const provider = (id: string) => ({
  id,
  name: id,
  discovery_url: `https://${id}.example/.well-known/openid-configuration`,
  client_id: "c",
  client_secret: "s",
  scopes: ["openid"],
});
const CONFIG: AuthConfig = { allowed_emails: [], providers: [provider("good"), provider("hanging")], version: "v1" };
const DISCOVERY = { authorization_endpoint: "https://idp/authorize", token_endpoint: "https://idp/token" };

function providerIds(): string[] {
  return genericOAuth.mock.lastCall![0].config.map((c) => c.providerId);
}

describe("getAuth", () => {
  let hanging: boolean;

  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    betterAuth.mockClear();
    genericOAuth.mockClear();
    fetchAuthConfig.mockResolvedValue(CONFIG);
    hanging = true;
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "info").mockImplementation(() => {});
    // The hanging IdP never answers and ignores the abort signal.
    vi.stubGlobal("fetch", vi.fn((url: string) =>
      url.includes("hanging") && hanging ? new Promise(() => {}) : Promise.resolve(Response.json(DISCOVERY)),
    ));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("resolves within the discovery timeout and leaves the hanging provider out", async () => {
    const { getAuth } = await import("@/lib/auth/server");
    const pending = getAuth();
    await vi.advanceTimersByTimeAsync(3_000);
    await expect(pending).resolves.toBeDefined();
    expect(providerIds()).toEqual(["good"]);
    expect(console.warn).toHaveBeenCalledTimes(1);
  });

  it("re-probes a failed provider in the background and includes it once it answers", async () => {
    const { getAuth } = await import("@/lib/auth/server");
    const pending = getAuth();
    await vi.advanceTimersByTimeAsync(3_000);
    const first = await pending;

    // Within the retry interval the same instance is reused, without probing.
    expect(await getAuth()).toBe(first);
    expect(betterAuth).toHaveBeenCalledTimes(1);

    hanging = false;
    await vi.advanceTimersByTimeAsync(15_000);
    expect(await getAuth()).toBe(first); // the retry runs in the background
    await vi.advanceTimersByTimeAsync(0);
    const second = await getAuth();
    expect(second).not.toBe(first);
    expect(providerIds()).toEqual(["good", "hanging"]);
  });

  it("disables implicit account linking", async () => {
    hanging = false;
    const { getAuth } = await import("@/lib/auth/server");
    await getAuth();
    expect(betterAuth.mock.lastCall![0]).toMatchObject({ account: { accountLinking: { enabled: false } } });
  });
});

describe("last-admin guard", () => {
  beforeEach(() => {
    vi.resetModules();
    betterAuth.mockClear();
    query.mockReset();
    fetchAuthConfig.mockResolvedValue({ allowed_emails: [], providers: [], version: "v1" });
  });

  async function hook(): Promise<BuiltOptions["hooks"]["before"]> {
    const { getAuth } = await import("@/lib/auth/server");
    await getAuth();
    return (betterAuth.mock.lastCall![0] as BuiltOptions).hooks.before;
  }

  it.each([
    ["/admin/remove-user", { userId: "a" }],
    ["/admin/ban-user", { userId: "a" }],
    ["/admin/set-role", { userId: "a", role: "user" }],
    ["/admin/update-user", { userId: "a", data: { role: "user" } }],
  ])("refuses %s on the only admin", async (path, body) => {
    query.mockResolvedValue({ rows: [{ id: "a", role: "admin" }] });
    const before = await hook();
    await expect(before({ path, body })).rejects.toMatchObject({ statusCode: 400, message: "cannot remove the last admin" });
    expect(query.mock.lastCall![1]).toEqual(["a"]);
  });

  it("lets it through when another admin exists", async () => {
    query.mockResolvedValue({ rows: [{ id: "a", role: "admin" }, { id: "b", role: "admin" }] });
    const before = await hook();
    await expect(before({ path: "/admin/remove-user", body: { userId: "a" } })).resolves.toBeUndefined();
  });

  it("refuses when the only other admin is banned", async () => {
    query.mockResolvedValue({ rows: [{ id: "a", role: "admin" }, { id: "b", role: "admin", banned: true, banExpires: null }] });
    const before = await hook();
    await expect(before({ path: "/admin/set-role", body: { userId: "a", role: "user" } })).rejects.toMatchObject({ statusCode: 400 });
  });

  it("lets it through for plain users and unknown ids", async () => {
    const before = await hook();
    query.mockResolvedValue({ rows: [{ id: "a", role: "admin" }, { id: "u", role: "user" }] });
    await expect(before({ path: "/admin/remove-user", body: { userId: "u" } })).resolves.toBeUndefined();
    await expect(before({ path: "/admin/remove-user", body: { userId: "missing" } })).resolves.toBeUndefined();
  });

  it("does not query the database for unrelated endpoints", async () => {
    const before = await hook();
    await expect(before({ path: "/sign-in/username", body: { username: "x" } })).resolves.toBeUndefined();
    await expect(before({ path: "/admin/set-role", body: { userId: "a", role: "admin" } })).resolves.toBeUndefined();
    expect(query).not.toHaveBeenCalled();
  });
});
