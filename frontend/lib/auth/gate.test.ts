import { describe, expect, it } from "vitest";

import { isUserAllowed, newUserData } from "@/lib/auth/gate";

describe("isUserAllowed", () => {
  it("lets local users in unless banned", () => {
    expect(isUserAllowed({ source: "local", email: "x@local.invalid" }, [])).toBe(true);
    expect(isUserAllowed({ source: "local", banned: true }, [])).toBe(false);
  });

  it("checks OIDC users against the allowlist on every call, case-insensitively", () => {
    expect(isUserAllowed({ source: "oidc", email: "Me@Example.org" }, ["me@example.org"])).toBe(true);
    expect(isUserAllowed({ source: "oidc", email: "me@example.org" }, [])).toBe(false);
    expect(isUserAllowed({ source: "oidc", email: null }, ["me@example.org"])).toBe(false);
  });

  it("treats an unknown source as OIDC (safer default)", () => {
    expect(isUserAllowed({ email: "me@example.org" }, [])).toBe(false);
  });

  it("ignores blank allowlist entries and whitespace around them", () => {
    expect(isUserAllowed({ source: "oidc", email: "" }, [" ", ""])).toBe(false);
    expect(isUserAllowed({ source: "oidc", email: "me@example.org" }, [" Me@Example.org "])).toBe(true);
  });

  it("refuses banned OIDC users even when allowlisted", () => {
    expect(isUserAllowed({ source: "oidc", email: "me@example.org", banned: true }, ["me@example.org"])).toBe(false);
  });
});

describe("newUserData", () => {
  const oidc = { source: "oidc", email: "me@example.org" };

  it("refuses OIDC users off the allowlist, even as the first user", () => {
    expect(newUserData(oidc, [], true)).toBe(false);
  });

  it("makes the first allowlisted OIDC user admin and keeps the oidc source", () => {
    expect(newUserData(oidc, ["me@example.org"], true)).toEqual({ data: { ...oidc, role: "admin" } });
  });

  it("leaves later OIDC users to the default role", () => {
    expect(newUserData(oidc, ["me@example.org"], false)).toEqual({ data: oidc });
  });

  it("keeps local users as created (the setup form sets the role itself)", () => {
    const local = { source: "local", email: "admin@local.invalid", role: "admin" };
    expect(newUserData(local, [], true)).toEqual({ data: local });
  });
});
