import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InfoRow } from "@/components/device-info";

describe("InfoRow", () => {
  it("stacks the label above the value and source on phones, side by side from sm up", () => {
    render(<InfoRow label="Vendor" value="Murata Manufacturing Co., Ltd." source="OUI registry" />);
    const label = screen.getByText("Vendor");
    const row = label.parentElement as HTMLElement;
    expect(row.className).toContain("grid-cols-[1fr_auto]");
    expect(row.className).toContain("sm:grid-cols-[var(--label-w)_1fr_auto]");
    expect(row.style.getPropertyValue("--label-w")).toBe("150px");
    expect(label.className).toContain("col-span-2");
    expect(screen.getByText("Murata Manufacturing Co., Ltd.").className).toContain("break-words");
    expect(screen.getByText("OUI registry")).toBeTruthy();
  });

  it("keeps mono tokens such as addresses whole on phones", () => {
    render(<InfoRow label="MAC" mono value="10:32:2C:77:A0:D4" source="ARP" labelWidth={120} />);
    const value = screen.getByText("10:32:2C:77:A0:D4");
    expect(value.className.split(" ")).toContain("break-normal");
    expect(value.className.split(" ")).not.toContain("break-words");
    expect((value.parentElement as HTMLElement).style.getPropertyValue("--label-w")).toBe("120px");
  });

  it("uses a single column on phones when there is no source", () => {
    render(<InfoRow label="First seen" value="now" />);
    expect((screen.getByText("First seen").parentElement as HTMLElement).className).toContain("grid-cols-1");
  });
});
