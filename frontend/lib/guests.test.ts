import { describe, expect, it } from "vitest";

import { describeExpiry, sortGuests } from "@/lib/guests";
import { makeDevice } from "@/lib/test-data";

const NOW = new Date("2026-10-03T10:00:00Z");
const guest = (over = {}) => ({ ...makeDevice({ access: "guest" }), guest_since: "2026-10-03T08:00:00Z",
  guest_expires_at: null, effective_expires_at: null, expiry_source: null, ...over });

describe("describeExpiry", () => {
  it("says never without any rule", () => expect(describeExpiry(guest(), NOW, "24h")).toBe("never"));
  it("uses relative hours under a day", () =>
    expect(describeExpiry(guest({ effective_expires_at: "2026-10-03T13:00:00Z", expiry_source: "device" }), NOW, "24h")).toBe("in 3 h"));
  it("flags overdue guests", () =>
    expect(describeExpiry(guest({ effective_expires_at: "2026-10-03T09:00:00Z", expiry_source: "global" }), NOW, "24h")).toBe("expired"));
  it("uses minutes in the last hour", () =>
    expect(describeExpiry(guest({ effective_expires_at: "2026-10-03T10:20:00Z", expiry_source: "inactive" }), NOW, "24h")).toBe("in 20 min"));
  it("names tomorrow in the given zone and time format", () => {
    const g = guest({ effective_expires_at: "2026-10-04T12:00:00Z", expiry_source: "device" });
    expect(describeExpiry(g, NOW, "24h", "UTC")).toBe("tomorrow 12:00");
    expect(describeExpiry(g, NOW, "12h", "UTC")).toBe("tomorrow 12:00 PM");
    expect(describeExpiry(g, NOW, "24h", "Europe/Rome")).toBe("tomorrow 14:00");
  });
  it("shows the date further out", () =>
    expect(describeExpiry(guest({ effective_expires_at: "2026-10-10T21:59:59Z", expiry_source: "device" }), NOW, "24h", "Europe/Rome")).toBe("10/10 23:59"));
});

describe("sortGuests", () => {
  it("puts the soonest first and never-expiring last", () => {
    const a = guest({ id: "a", effective_expires_at: "2026-10-05T00:00:00Z" });
    const b = guest({ id: "b" });
    const c = guest({ id: "c", effective_expires_at: "2026-10-04T00:00:00Z" });
    expect(sortGuests([a, b, c]).map((g) => g.id)).toEqual(["c", "a", "b"]);
  });
});
