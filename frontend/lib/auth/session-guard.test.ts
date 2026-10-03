import { describe, expect, it } from "vitest";

import { decide } from "@/lib/auth/session-guard";

describe("decide", () => {
  it("sends everyone to /setup until the first user exists", () => {
    expect(decide("/devices", false, false)).toEqual({ kind: "redirect", to: "/setup" });
    expect(decide("/setup", false, false)).toEqual({ kind: "next" });
  });
  it("closes /setup once a user exists", () => {
    expect(decide("/setup", false, true)).toEqual({ kind: "redirect", to: "/login" });
  });
  it("answers 401 JSON for API calls and redirects pages with a callback", () => {
    expect(decide("/api/devices", false, true)).toEqual({ kind: "json401" });
    expect(decide("/groups?x=1", false, true)).toEqual({ kind: "redirect", to: "/login?callbackUrl=%2Fgroups%3Fx%3D1" });
  });
  it("lets signed-in users through", () => {
    expect(decide("/groups", true, true)).toEqual({ kind: "next" });
  });
});
