import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EventList } from "@/components/event-list";

describe("EventList", () => {
  it("puts the timestamp on its own line on phones and in a column from sm up", () => {
    render(<EventList events={[{ id: 1, ts: "2026-10-03T17:11:00Z", type: "maintenance.end", mac: "AA:BB:CC:DD:EE:FF", payload: {} }]} />);
    const item = screen.getByRole("listitem");
    const classes = item.className.split(" ");
    expect(classes).toContain("grid-cols-1");
    expect(classes).toContain("sm:grid-cols-[96px_1fr]");
    expect((item.firstElementChild as HTMLElement).className).toContain("font-mono");
    expect(screen.getByText("AA:BB:CC:DD:EE:FF")).toBeTruthy();
  });
});
