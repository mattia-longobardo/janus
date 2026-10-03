import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import IpPlanPage from "@/app/(app)/ip-plan/page";
import { makeDevice, makeGroup } from "@/lib/test-data";

const GROUPS = [makeGroup({ id: 1, name: "People" })];
const DEVICES = [makeDevice({ id: "d1", group_id: 1, static_ip: "192.168.1.20" })];

vi.mock("@/lib/use-resource", () => ({
  useResource: (path: string | null) => ({
    data: path === "/groups" ? GROUPS : path === "/devices" ? DEVICES : [],
    error: null,
    loading: false,
    reload: async () => {},
  }),
}));

describe("IpPlanPage address grid", () => {
  it("uses 8 columns on phones and 16 from sm up, with every address in the grid", () => {
    render(<IpPlanPage />);
    const grid = screen.getByRole("grid", { name: "Addresses" });
    const classes = grid.className.split(" ");
    expect(classes).toContain("grid-cols-8");
    expect(classes).toContain("sm:grid-cols-16");
    expect(classes).not.toContain("grid-cols-16");
    expect(classes).toContain("w-full");
    expect(screen.getAllByRole("gridcell")).toHaveLength(256);
  });
});
