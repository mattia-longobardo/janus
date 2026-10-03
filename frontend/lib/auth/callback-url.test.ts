import { describe, expect, it } from "vitest";

import { safeCallbackUrl } from "@/lib/auth/callback-url";

describe("safeCallbackUrl", () => {
  it("keeps same-origin relative paths", () => {
    expect(safeCallbackUrl("/groups")).toBe("/groups");
    expect(safeCallbackUrl("/devices?x=1#top")).toBe("/devices?x=1#top");
  });

  it("falls back to / for missing values", () => {
    expect(safeCallbackUrl(undefined)).toBe("/");
    expect(safeCallbackUrl("")).toBe("/");
  });

  it.each(["//evil.example", "/\\evil.example", "https://evil.example", "http://x", "javascript:alert(1)", "groups", "/\t/evil.example", "/\n/evil.example"])(
    "rejects %j",
    (value) => {
      expect(safeCallbackUrl(value)).toBe("/");
    },
  );
});
