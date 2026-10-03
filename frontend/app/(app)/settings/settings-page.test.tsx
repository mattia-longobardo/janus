import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SettingsPage from "@/app/(app)/settings/page";
import * as featuresModule from "@/lib/features";
import type { ProviderRef } from "@/lib/types";

vi.mock("@/lib/use-resource", () => ({
  useResource: () => ({ data: [], error: null, loading: false, reload: async () => {} }),
}));

// Extra sections load their own data; this file only covers the built-in cards.
vi.mock("@/app/(app)/settings/sections", () => ({ EXTRA_SECTIONS: [] }));
vi.mock("@/lib/auth/client", () => ({ authClient: { useSession: () => ({ data: null }) } }));

vi.mock("@/lib/settings-context", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/settings-context")>();
  const settings = { ...mod.DEFAULT_SETTINGS, source: { sweep_interval_s: "custom" } };
  return { ...mod, useSettings: () => ({ settings, reload: async () => {} }) };
});

describe("SettingsPage network card", () => {
  it("has a single Save and no per-field Reset, even for overridden fields", () => {
    render(<SettingsPage />);
    expect(screen.queryByRole("button", { name: /^reset$/i })).toBeNull();
    expect(screen.getByRole("button", { name: /^(Save|Saved)$/ })).toBeTruthy();
  });

  it("shows the quarantine pool fields only when the DHCP provider has a quarantine", () => {
    const dhcp = (capabilities: string[]): ProviderRef => ({ kind: "x", label: "X", capabilities, policies: ["full"], down_since: null });
    const spy = vi.spyOn(featuresModule, "useFeatures");
    spy.mockReturnValue({ features: { providers: { dhcp: dhcp(["reservations"]), dns: null } }, reload: async () => {} });
    const { unmount } = render(<SettingsPage />);
    expect(screen.queryByLabelText("Quarantine from")).toBeNull();
    expect(screen.queryByLabelText("Quarantine to")).toBeNull();
    expect(screen.queryByText("Quarantine unknown devices")).toBeNull();
    unmount();
    spy.mockReturnValue({ features: { providers: { dhcp: dhcp(["reservations", "quarantine"]), dns: null } }, reload: async () => {} });
    render(<SettingsPage />);
    expect(screen.getByLabelText("Quarantine from")).toBeTruthy();
    expect(screen.getByLabelText("Quarantine to")).toBeTruthy();
  });
});
