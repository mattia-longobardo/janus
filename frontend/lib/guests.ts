import { formatDateTime } from "@/lib/format";
import type { ExpiryInput, Guest, GuestRules } from "@/lib/types";

export const PRESETS = [
  { label: "2 hours", hours: 2 },
  { label: "1 day", hours: 24 },
  { label: "3 days", hours: 72 },
  { label: "1 week", hours: 168 },
];

const HOUR = 3_600_000;

function dayKey(date: Date, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

// The calendar day after a YYYY-MM-DD key (pure date arithmetic, so DST cannot shift it).
function nextDay(key: string): string {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10);
}

// YYYY-MM-DD of today in the given zone: the earliest date a guest can expire on.
export function todayIn(timeZone: string, now: Date = new Date()): string {
  return dayKey(now, timeZone);
}

function clock(date: Date, timeZone: string, fmt: "24h" | "12h"): string {
  return formatDateTime(date.toISOString(), timeZone, fmt).split(" ").slice(1).join(" ");
}

// "expired" means the worker job has not run yet: it removes the guest on its next pass.
export function describeExpiry(
  g: Pick<Guest, "effective_expires_at">,
  now: Date,
  fmt: "24h" | "12h",
  timeZone: string = Intl.DateTimeFormat().resolvedOptions().timeZone,
): string {
  if (!g.effective_expires_at) return "never";
  const when = new Date(g.effective_expires_at);
  const left = when.getTime() - now.getTime();
  if (left <= 0) return "expired";
  if (left < HOUR) return `in ${Math.max(1, Math.round(left / 60_000))} min`;
  if (left < 24 * HOUR) return `in ${Math.round(left / HOUR)} h`;
  if (dayKey(when, timeZone) === nextDay(dayKey(now, timeZone))) return `tomorrow ${clock(when, timeZone, fmt)}`;
  return formatDateTime(g.effective_expires_at, timeZone, fmt);
}

export function sortGuests(gs: Guest[]): Guest[] {
  const key = (g: Guest) => (g.effective_expires_at ? Date.parse(g.effective_expires_at) : Number.POSITIVE_INFINITY);
  return [...gs].sort((a, b) => key(a) - key(b) || a.name.localeCompare(b.name));
}

// Short summary of the global rules, e.g. "24 h / 6 h idle"; null when both are off.
export function describeRules(rules: GuestRules | undefined): string | null {
  if (!rules) return null;
  const parts = [
    rules.auto_remove_hours !== null && `${rules.auto_remove_hours} h`,
    rules.inactive_remove_hours !== null && `${rules.inactive_remove_hours} h idle`,
  ].filter(Boolean);
  return parts.length ? parts.join(" / ") : null;
}

// A new guest has no expiry to clear: "Never" / "Use default" simply sends none.
export function newGuestExpiry(input: ExpiryInput): Exclude<ExpiryInput, { clear_expiry: true }> {
  return "clear_expiry" in input ? {} : input;
}
