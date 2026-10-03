import { describe, expect, it } from "vitest";

import { adminLossTarget, canRemoveOrDemote } from "@/lib/auth/last-admin";

describe("canRemoveOrDemote", () => {
  const a = { id: "a", role: "admin" }, b = { id: "b", role: "admin" }, u = { id: "u", role: "user" };
  it("refuses to remove the only admin", () => expect(canRemoveOrDemote(a, [a, u])).toBe(false));
  it("allows it when another admin exists", () => expect(canRemoveOrDemote(a, [a, b, u])).toBe(true));
  it("always allows plain users", () => expect(canRemoveOrDemote(u, [a, u])).toBe(true));
  it("counts multi-role admins", () => {
    const multi = { id: "m", role: "user,admin" };
    expect(canRemoveOrDemote(a, [a, multi])).toBe(true);
    expect(canRemoveOrDemote(multi, [multi, u])).toBe(false);
  });
});

describe("adminLossTarget", () => {
  it("targets the user being removed or banned", () => {
    expect(adminLossTarget("/admin/remove-user", { userId: "x" })).toBe("x");
    expect(adminLossTarget("/admin/ban-user", { userId: "x", banReason: "r" })).toBe("x");
  });
  it("targets a role change only when it drops admin", () => {
    expect(adminLossTarget("/admin/set-role", { userId: "x", role: "user" })).toBe("x");
    expect(adminLossTarget("/admin/set-role", { userId: "x", role: ["user"] })).toBe("x");
    expect(adminLossTarget("/admin/set-role", { userId: "x", role: "admin" })).toBeNull();
    expect(adminLossTarget("/admin/set-role", { userId: "x", role: ["user", "admin"] })).toBeNull();
  });
  it("targets an admin update that changes the role or bans", () => {
    expect(adminLossTarget("/admin/update-user", { userId: "x", data: { role: "user" } })).toBe("x");
    expect(adminLossTarget("/admin/update-user", { userId: "x", data: { banned: true } })).toBe("x");
    expect(adminLossTarget("/admin/update-user", { userId: "x", data: { role: "admin" } })).toBeNull();
    expect(adminLossTarget("/admin/update-user", { userId: "x", data: { name: "n" } })).toBeNull();
  });
  it("ignores other endpoints and malformed bodies", () => {
    expect(adminLossTarget("/admin/unban-user", { userId: "x" })).toBeNull();
    expect(adminLossTarget("/sign-in/username", { username: "x" })).toBeNull();
    expect(adminLossTarget("/admin/remove-user", undefined)).toBeNull();
    expect(adminLossTarget("/admin/remove-user", { userId: 42 })).toBeNull();
  });
});
