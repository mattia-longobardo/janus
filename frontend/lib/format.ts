import type { Access } from "@/lib/types";

export function formatDateTime(iso: string | null | undefined, timeZone: string, timeFormat: "24h" | "12h" = "24h"): string {
  if (!iso) return "—";
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: timeFormat === "12h",
  }).formatToParts(new Date(iso));
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const period = part("dayPeriod");
  return `${part("day")}/${part("month")} ${part("hour")}:${part("minute")}${period ? ` ${period.toUpperCase()}` : ""}`;
}

export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "never";
  const seconds = Math.max(0, (now - Date.parse(iso)) / 1000);
  if (seconds < 5) return "now";
  if (seconds < 90) return `${Math.round(seconds)} s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172_800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86_400)} d ago`;
}

export const ACCESS_LABELS: Record<Access, string> = {
  authorized: "Full network",
  lan_only: "LAN only",
  pending: "Pending",
  blocked: "Blocked",
  guest: "Guest",
};

export function ipSortKey(ip: string | null | undefined): number {
  if (!ip) return Number.MAX_SAFE_INTEGER;
  return ip.split(".").reduce((acc, part) => acc * 256 + (Number(part) || 0), 0);
}

export function deviceIp(device: { static_ip: string | null; last_ip: string | null }): string | null {
  return device.static_ip ?? device.last_ip;
}
