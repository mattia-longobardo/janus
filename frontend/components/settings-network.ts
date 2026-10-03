import type { AppSettings, NetworkField } from "@/lib/types";

export type NetDraft = Record<NetworkField, string>;
export type NetPatch = Partial<Record<NetworkField, string | number | null>>;

export const NETWORK_FIELDS: NetworkField[] = [
  "subnet",
  "gateway",
  "sentinel_interface",
  "sweep_interval_s",
  "scan_window_start",
  "scan_window_end",
  "quarantine_start",
  "quarantine_end",
  "guest_start",
  "guest_end",
];

export function toDraft(settings: AppSettings): NetDraft {
  const n = settings.network;
  return {
    subnet: n.subnet,
    gateway: n.gateway,
    quarantine_start: n.quarantine_start,
    quarantine_end: n.quarantine_end,
    guest_start: n.guest_start,
    guest_end: n.guest_end,
    sentinel_interface: n.sentinel_interface,
    sweep_interval_s: String(n.sweep_interval_s),
    scan_window_start: settings.scan_window.start,
    scan_window_end: settings.scan_window.end,
  };
}

export function networkPatch(draft: NetDraft, settings: AppSettings): NetPatch {
  const current = toDraft(settings);
  const patch: NetPatch = {};
  for (const field of NETWORK_FIELDS) {
    const value = draft[field].trim();
    if (value === current[field]) continue;
    patch[field] = field === "sweep_interval_s" ? Number(value) : value;
  }
  return patch;
}

export function errorField(detail: string): NetworkField | null {
  const prefix = detail.split(":")[0].trim();
  if ((NETWORK_FIELDS as string[]).includes(prefix)) return prefix as NetworkField;
  if (/quarantine pool/i.test(detail)) return "quarantine_start";
  return null;
}
