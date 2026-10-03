import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Shell } from "@/components/shell";

vi.mock("@/lib/use-resource", () => ({
  useResource: () => ({ data: undefined, error: null, loading: false, reload: async () => {} }),
}));
vi.mock("@/lib/auth-actions", () => ({ logout: vi.fn() }));
vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

const zIndex = (el: Element) => Number(/(?:^| )z-(\d+)/.exec(el.className)?.[1]);

describe("Shell mobile menu", () => {
  it("opens the drawer over the sticky header with a backdrop, and closes from the backdrop", async () => {
    render(<Shell user={{ id: "u1", name: "mattia", role: "admin", source: "local" }}>page</Shell>);
    const drawer = screen.getByRole("navigation", { name: "Main" });
    expect(drawer.className).toContain("-translate-x-full");
    expect(screen.getAllByRole("button", { name: "Close menu" })).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: "Open menu" }));
    expect(drawer.className).toContain("translate-x-0");
    expect(drawer.className).not.toContain("-translate-x-full");
    const [backdrop] = screen.getAllByRole("button", { name: "Close menu" });
    const header = screen.getByRole("button", { name: "Open menu" }).closest("header") as HTMLElement;
    // Drawer above backdrop above the sticky header.
    expect(zIndex(drawer)).toBeGreaterThan(zIndex(backdrop));
    expect(zIndex(backdrop)).toBeGreaterThan(zIndex(header));

    await userEvent.click(backdrop);
    expect(drawer.className).toContain("-translate-x-full");
  });
});
