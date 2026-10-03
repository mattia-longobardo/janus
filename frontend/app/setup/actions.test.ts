import { beforeEach, expect, it, vi } from "vitest";

const { getHasUsers, createUser, signInUsername, redirect } = vi.hoisted(() => ({
  getHasUsers: vi.fn(),
  createUser: vi.fn(),
  signInUsername: vi.fn(),
  redirect: vi.fn((to: string) => {
    throw new Error(`redirect:${to}`);
  }),
}));
vi.mock("next/headers", () => ({ headers: async () => new Headers() }));
vi.mock("next/navigation", () => ({ redirect }));
vi.mock("@/lib/auth/server", () => ({ getHasUsers, getAuth: async () => ({ api: { createUser, signInUsername } }) }));

import { createFirstAdmin } from "./actions";

function form(username: string, password: string, confirm = password) {
  const data = new FormData();
  data.set("username", username);
  data.set("password", password);
  data.set("confirm", confirm);
  return data;
}

beforeEach(() => {
  vi.clearAllMocks();
  getHasUsers.mockResolvedValue(false);
  vi.spyOn(console, "error").mockImplementation(() => {});
});

it("keeps the specific validation messages", async () => {
  expect((await createFirstAdmin({ error: null }, form("A!", "correct horse battery"))).error).toMatch(/Username must be/);
  expect((await createFirstAdmin({ error: null }, form("admin", "short"))).error).toMatch(/at least 12/);
  expect((await createFirstAdmin({ error: null }, form("admin", "correct horse battery", "other one here"))).error).toMatch(/do not match/);
  expect(createUser).not.toHaveBeenCalled();
});

it("returns a generic message for unexpected errors", async () => {
  createUser.mockRejectedValue(new Error('relation "auth.user" does not exist'));
  const state = await createFirstAdmin({ error: null }, form("admin", "correct horse battery"));
  expect(state.error).toBe("Could not create the administrator. Check the server log and try again.");
  expect(state.error).not.toContain("relation");
});
