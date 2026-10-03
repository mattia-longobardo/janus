import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthConfig } from "@/lib/auth/config";

const { betterAuth, genericOAuth, fetchAuthConfig } = vi.hoisted(() => ({
  betterAuth: vi.fn((options: unknown) => ({ options })),
  genericOAuth: vi.fn((options: { config: { providerId: string }[] }) => ({ id: "generic-oauth", options })),
  fetchAuthConfig: vi.fn<() => Promise<AuthConfig>>(),
}));

vi.mock("server-only", () => ({}));
vi.mock("pg", () => ({ Pool: class {} }));
vi.mock("better-auth", () => ({ betterAuth }));
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
