import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { ClientsPage } from "@/providers/unifi/clients-page";

const ROWS = [
  { mac: "00:00:5E:00:53:10", name: "laptop-a", ip: "192.168.1.10", online: true, uplink: "AP Living room", ssid: "Home", signal: -55, uptime_s: 120, device_id: "d1" },
  { mac: "00:00:5E:00:53:11", name: "", ip: "192.168.1.240", online: true, uplink: "Switch Office port 4", ssid: null, signal: null, uptime_s: 60, device_id: null },
];

function mockClients() {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(ROWS), { status: 200, headers: { "content-type": "application/json" } }),
  );
}

it("links known clients and flags the others", async () => {
  mockClients();
  render(<ClientsPage />);
  const link = await screen.findByRole("link", { name: "laptop-a" });
  expect(link.getAttribute("href")).toBe("/devices/d1");
  expect(screen.getAllByText("not in Janus")).toHaveLength(1);
  expect(screen.getByText("Switch Office port 4")).toBeTruthy();
});

it("filters by the search text", async () => {
  mockClients();
  render(<ClientsPage />);
  await screen.findByRole("link", { name: "laptop-a" });
  const { default: userEvent } = await import("@testing-library/user-event");
  await userEvent.type(screen.getByRole("searchbox", { name: "Search clients" }), "office");
  expect(screen.queryByRole("link", { name: "laptop-a" })).toBeNull();
  expect(screen.getByText("not in Janus")).toBeTruthy();
});
