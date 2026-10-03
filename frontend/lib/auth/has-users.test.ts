import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { query } = vi.hoisted(() => ({ query: vi.fn() }));

vi.mock("server-only", () => ({}));
vi.mock("pg", () => ({ Pool: class { query = query; } }));
vi.mock("better-auth", () => ({ betterAuth: vi.fn() }));
vi.mock("better-auth/next-js", () => ({ nextCookies: vi.fn() }));
vi.mock("better-auth/plugins", () => ({ admin: vi.fn(), username: vi.fn(), genericOAuth: vi.fn() }));

describe("getHasUsers", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    query.mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it("does not cache false, so the first sign-up is seen at once", async () => {
    const { getHasUsers } = await import("@/lib/auth/server");
    query.mockResolvedValue({ rows: [{ exists: false }] });
    expect(await getHasUsers()).toBe(false);
    query.mockResolvedValue({ rows: [{ exists: true }] });
    expect(await getHasUsers()).toBe(true);
    expect(query).toHaveBeenCalledTimes(2);
  });

  it("caches true for 10 s", async () => {
    const { getHasUsers } = await import("@/lib/auth/server");
    query.mockResolvedValue({ rows: [{ exists: true }] });
    expect(await getHasUsers()).toBe(true);
    vi.advanceTimersByTime(9_000);
    expect(await getHasUsers()).toBe(true);
    expect(query).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(2_000);
    await getHasUsers();
    expect(query).toHaveBeenCalledTimes(2);
  });
});
