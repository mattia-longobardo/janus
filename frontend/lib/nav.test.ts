import { Router } from "lucide-react";
import { describe, expect, it } from "vitest";

import { NAV, visibleNav, type NavItem } from "@/lib/nav";

const gated: NavItem = { href: "/gated", label: "Gated", icon: Router, requires: (f) => Boolean(f.guests?.enabled) };

describe("visibleNav", () => {
  it("keeps every ungated item and hides gated ones until features load", () => {
    const items = visibleNav(null, [gated]);
    expect(items.map((i) => i.href)).toEqual(NAV.filter((i) => !i.requires).map((i) => i.href));
  });

  it("shows a gated item once its feature is on", () => {
    expect(visibleNav({ guests: { enabled: true } }, [gated]).some((i) => i.href === "/gated")).toBe(true);
    expect(visibleNav({ guests: { enabled: false } }, [gated]).some((i) => i.href === "/gated")).toBe(false);
  });

  it("places extra items before Notifications and keeps Settings last", () => {
    const hrefs = visibleNav({ guests: { enabled: true } }, [gated]).map((i) => i.href);
    expect(hrefs.indexOf("/gated")).toBeLessThan(hrefs.indexOf("/notifications"));
    expect(hrefs.at(-1)).toBe("/settings");
  });
});
