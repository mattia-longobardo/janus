"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { AppSettings } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

export const DEFAULT_SETTINGS: AppSettings = {
  timezone: "Europe/Rome",
  time_format: "24h",
  sync_mode: "dry-run",
  network: {
    subnet: "192.168.1.0/24",
    gateway: "192.168.1.1",
    quarantine_start: "192.168.1.240",
    quarantine_end: "192.168.1.254",
    guest_start: "",
    guest_end: "",
    sentinel_interface: "",
    sweep_interval_s: 60,
  },
  scan_window: { start: "08:00", end: "22:00" },
  source: {},
  status: { dhcp_down_since: null, dns_down_since: null, sentinel_down_since: null, last_sweep_at: null, maintenance_active: false },
  channels: { gotify_url: "", email_sender: "" },
};

const SettingsContext = createContext<{ settings: AppSettings; reload: () => Promise<void> }>({
  settings: DEFAULT_SETTINGS,
  reload: async () => {},
});

export function SettingsProvider({ children }: { children: ReactNode }) {
  const { data, reload } = useResource<AppSettings>("/settings", { refreshMs: 15_000 });
  return <SettingsContext.Provider value={{ settings: data ?? DEFAULT_SETTINGS, reload }}>{children}</SettingsContext.Provider>;
}

export function useSettings() {
  return useContext(SettingsContext);
}
