import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import * as featuresModule from "@/lib/features";
import { makeDevice } from "@/lib/test-data";
import type { Features, Guest } from "@/lib/types";

import GuestsPage from "./page";

const soon = new Date(Date.now() + 3 * 3_600_000).toISOString();
const guest = (over: Partial<Guest>): Guest => ({
  ...makeDevice({ access: "guest", group_id: null, static_ip: null, last_ip: "192.168.1.201" }),
  guest_since: "2026-10-03T08:00:00Z", guest_expires_at: null, effective_expires_at: null, expiry_source: null, ...over,
});
const GUESTS = [
  guest({ id: "g1", name: "Anna phone", mac: "00:00:5E:00:53:21" }),
  guest({ id: "g2", name: "Bob laptop", mac: "00:00:5E:00:53:22", effective_expires_at: soon, expiry_source: "global" }),
  guest({ id: "g3", name: "Cleo tablet", mac: "00:00:5E:00:53:23", effective_expires_at: soon, expiry_source: "inactive" }),
];
const DHCP = { kind: "pihole", label: "Pi-hole", capabilities: ["quarantine"], policies: ["full", "guest"], down_since: null };

function setup(features: Features, guests = GUESTS) {
  vi.spyOn(featuresModule, "useFeatures").mockReturnValue({ features, reload: async () => {} });
  vi.spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === "/guests") return guests;
    if (path === "/guests/settings") return { auto_remove_hours: 24, inactive_remove_hours: 6 };
    throw new Error(`unexpected ${path}`);
  });
}

describe("GuestsPage", () => {
  it("lists guests soonest first with the source of their expiry", async () => {
    setup({ guests: { enabled: true, pool: true }, providers: { dhcp: DHCP, dns: null } });
    render(<GuestsPage />);
    await screen.findByText("Bob laptop");
    const rows = screen.getAllByRole("row");
    expect(rows.slice(1).map((r) => r.querySelector("td")?.textContent)).toEqual(["Bob laptop", "Cleo tablet", "Anna phone"]);
    expect(within(rows[1]).getByText("default")).toBeTruthy();
    expect(within(rows[2]).getByText("if idle")).toBeTruthy();
    expect(within(rows[3]).getByText("never")).toBeTruthy();
    expect(screen.queryByText(/Set a guest pool/)).toBeNull();
  });

  it("warns about quarantine addresses only when there is no pool and the provider quarantines", async () => {
    setup({ guests: { enabled: true, pool: false }, providers: { dhcp: DHCP, dns: null } });
    const { unmount } = render(<GuestsPage />);
    expect(await screen.findByText(/Set a guest pool in Groups → Guests, otherwise guests get quarantine addresses without internet/)).toBeTruthy();
    unmount();
    setup({ guests: { enabled: true, pool: false }, providers: { dhcp: { ...DHCP, capabilities: [] }, dns: null } });
    render(<GuestsPage />);
    await screen.findByText("Bob laptop");
    expect(screen.queryByText(/Set a guest pool/)).toBeNull();
  });

  it("removes a guest after confirming", async () => {
    setup({ guests: { enabled: true, pool: true } });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const del = vi.spyOn(api, "del").mockResolvedValue(undefined);
    render(<GuestsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Remove Anna phone" }));
    expect(confirm).toHaveBeenCalledWith("Remove Anna phone? If it is still connected it will show up again in Pending.");
    expect(del).toHaveBeenCalledWith("/guests/g1");
  });

  it("adds a guest by MAC and changes an expiry", async () => {
    setup({ guests: { enabled: true, pool: true } });
    const post = vi.spyOn(api, "post").mockResolvedValue(GUESTS[0]);
    const patch = vi.spyOn(api, "patch").mockResolvedValue(GUESTS[0]);
    render(<GuestsPage />);
    await userEvent.click(screen.getByRole("button", { name: "Add guest" }));
    await userEvent.type(screen.getByLabelText("MAC address"), "00:00:5E:00:53:30");
    await userEvent.type(screen.getByLabelText("Name"), "Dan watch");
    await userEvent.click(screen.getByRole("button", { name: "2 hours" }));
    await userEvent.click(screen.getByRole("button", { name: "Save guest" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/guests", { mac: "00:00:5E:00:53:30", name: "Dan watch", expires_in_hours: 2 }));

    await userEvent.click(await screen.findByRole("button", { name: "Change expiry for Bob laptop" }));
    await userEvent.click(screen.getByRole("button", { name: "1 week" }));
    await userEvent.click(screen.getByRole("button", { name: "Save expiry" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/guests/g2", { expires_in_hours: 168 }));
  });
});
