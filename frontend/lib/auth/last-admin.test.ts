import { describe, expect, it } from "vitest";

import { canRemoveOrDemote } from "@/lib/auth/last-admin";

describe("canRemoveOrDemote", () => {
  const a = { id: "a", role: "admin" }, b = { id: "b", role: "admin" }, u = { id: "u", role: "user" };
  it("refuses to remove the only admin", () => expect(canRemoveOrDemote(a, [a, u])).toBe(false));
  it("allows it when another admin exists", () => expect(canRemoveOrDemote(a, [a, b, u])).toBe(true));
  it("always allows plain users", () => expect(canRemoveOrDemote(u, [a, u])).toBe(true));
});
