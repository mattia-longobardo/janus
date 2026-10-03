import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SettingsPage from "@/app/(app)/settings/page";

vi.mock("@/lib/use-resource", () => ({
  useResource: () => ({ data: [], error: null, loading: false, reload: async () => {} }),
}));

// Extra sections load their own data; this file only covers the built-in cards.
vi.mock("@/app/(app)/settings/sections", () => ({ EXTRA_SECTIONS: [] }));

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
});
