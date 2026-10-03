import { describe, expect, it } from "vitest";

import { eventTone } from "@/components/event-tone";

describe("eventTone", () => {
  it("colours events by severity", () => {
    expect(eventTone("ip.conflict")).toBe("bad");
    expect(eventTone("device.new")).toBe("warn");
    expect(eventTone("device.approved")).toBe("good");
    expect(eventTone("import.csv")).toBe("neutral");
    expect(eventTone("guest.added")).toBe("good");
    expect(eventTone("guest.expired")).toBe("neutral");
    expect(eventTone("guest.removed")).toBe("neutral");
  });
});
