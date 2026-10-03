import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import GroupsPage from "@/app/(app)/groups/page";
import * as featuresModule from "@/lib/features";
import { makeGroup } from "@/lib/test-data";
import type { Features, ProviderRef } from "@/lib/types";

const GROUPS = [makeGroup({ id: 1, name: "People" }), makeGroup({ id: 2, name: "Power meters", default_access: "lan_only" })];

vi.mock("@/lib/use-resource", () => ({
  useResource: (path: string) => ({ data: path === "/groups" ? GROUPS : [], error: null, loading: false, reload: async () => {} }),
}));

const pihole: ProviderRef = { kind: "pihole", label: "Pi-hole", capabilities: ["reservations", "quarantine"], policies: ["full", "lan_only"], down_since: null };
const unifi: ProviderRef = { kind: "unifi", label: "UniFi", capabilities: ["reservations"], policies: ["full"], down_since: null };

function show(features: Features) {
  vi.spyOn(featuresModule, "useFeatures").mockReturnValue({ features, reload: async () => {} });
  render(<GroupsPage />);
}

const accessOptions = () => [...screen.getByRole("group", { name: "Default access" }).querySelectorAll("button")].map((b) => b.textContent);

describe("GroupsPage follows the DHCP provider", () => {
  it("lists the quarantine pool and offers LAN only with Pi-hole", async () => {
    show({ providers: { dhcp: pihole, dns: null } });
    expect(screen.getAllByText("Quarantine").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: /People/ }));
    expect(accessOptions()).toEqual(["Full network", "LAN only"]);
  });

  it("hides the quarantine row and LAN only with UniFi, except on a group that already has it", async () => {
    show({ providers: { dhcp: unifi, dns: null } });
    expect(screen.queryByText("Quarantine")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /People/ }));
    expect(accessOptions()).toEqual(["Full network"]);
    await userEvent.click(screen.getByRole("button", { name: /Power meters/ }));
    expect(accessOptions()).toEqual(["Full network", "LAN only"]);
  });
});
