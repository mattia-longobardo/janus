import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as featuresModule from "@/lib/features";
import type { Features } from "@/lib/types";
import { ProviderPageGate } from "@/providers/provider-page-gate";

const pihole = (capabilities: string[]) => ({ kind: "pihole", label: "Pi-hole", capabilities, policies: [], down_since: null });
const unifi = { kind: "unifi", label: "UniFi", capabilities: ["reservations"], policies: ["full"], down_since: null };

function show(features: Features | null) {
  vi.spyOn(featuresModule, "useFeatures").mockReturnValue({ features, reload: async () => {} });
  render(
    <ProviderPageGate href="/integrations/pihole/cutover">
      <p>cutover checks</p>
    </ProviderPageGate>,
  );
}

describe("ProviderPageGate", () => {
  it("opens the cutover page while Pi-hole holds the DHCP role", () => {
    show({ providers: { dhcp: pihole(["reservations", "dhcp_server", "quarantine"]), dns: { ...pihole(["dns_query_log"]), shared: true } } });
    expect(screen.getByText("cutover checks")).toBeTruthy();
  });

  it("keeps it closed for a DNS-only Pi-hole next to UniFi", () => {
    show({ providers: { dhcp: unifi, dns: pihole(["dns_query_log", "dns_probe"]) } });
    expect(screen.queryByText("cutover checks")).toBeNull();
    expect(screen.getByText("This page is not available with the current network provider.")).toBeTruthy();
  });

  it("renders nothing of the page until features load", () => {
    show(null);
    expect(screen.queryByText("cutover checks")).toBeNull();
    expect(screen.queryByText(/not available/)).toBeNull();
  });
});
