const BAD = new Set(["ip.conflict", "infra.down", "security.risky_service", "sync.failed", "scan.failed", "notify.failed", "device.blocked"]);
const WARN = new Set(["device.new", "device.ip_mismatch", "device.private_mac", "security.new_port", "maintenance.start"]);
const GOOD = new Set(["device.approved", "infra.up", "sync.applied", "scan.completed", "notify.test", "maintenance.end", "guest.added"]);

export type EventTone = "bad" | "warn" | "good" | "neutral";

export function eventTone(type: string): EventTone {
  if (BAD.has(type)) return "bad";
  if (WARN.has(type)) return "warn";
  if (GOOD.has(type)) return "good";
  return "neutral";
}

export const TONE_DOT: Record<EventTone, string> = { bad: "bg-bad", warn: "bg-accent", good: "bg-ok", neutral: "bg-muted" };
