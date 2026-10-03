import { describe, expect, it } from "vitest";

import { isUserAllowed } from "@/lib/auth/gate";

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
