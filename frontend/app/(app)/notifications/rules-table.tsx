"use client";

import { Checkbox } from "@/components/ui";
import type { Rule } from "@/lib/types";

const HINTS: Record<string, string> = {
  "device.new": "Always delivered, even in quiet hours",
  "device.offline": "Muted during maintenance windows",
  "infra.down": "Muted during maintenance windows",
  "infra.up": "Only after an outage alert was delivered",
  "device.ip_mismatch": "A device uses an address other than its reservation",
  "security.risky_service": "Telnet, FTP, unauthenticated web UIs and similar",
  "security.new_port": "Found by the scheduled port scan",
};

// Column templates by channel count and whether the priority column is shown (full class names so Tailwind can see them).
const GRIDS = {
  "2-priority": "grid grid-cols-[1fr_52px_52px_112px] items-center gap-2 sm:grid-cols-[1fr_90px_90px_150px] sm:gap-3",
  "1-priority": "grid grid-cols-[1fr_52px_112px] items-center gap-2 sm:grid-cols-[1fr_90px_150px] sm:gap-3",
  "1": "grid grid-cols-[1fr_52px] items-center gap-2 sm:grid-cols-[1fr_90px] sm:gap-3",
  "0": "grid grid-cols-[1fr] items-center gap-2 sm:gap-3",
} as const;
const CHANNEL_LABEL = { email: "Email", gotify: "Gotify" } as const;
const PRIORITIES = Array.from({ length: 11 }, (_, n) => n);

export function priorityLabel(priority: number): string {
  const name = priority === 0 ? "silent" : priority <= 3 ? "low" : priority <= 7 ? "normal" : priority <= 9 ? "high" : "max";
  return `${priority} · ${name}`;
}
const HEAD = "text-center text-xs font-medium uppercase tracking-[.06em] text-faint";

export function RulesTable({ rules, channels, onChange }: { rules: Rule[]; channels: ("email" | "gotify")[]; onChange: (rule: Rule) => void }) {
  // Priority is a Gotify-only setting.
  const showPriority = channels.includes("gotify");
  const GRID = channels.length === 2 ? GRIDS["2-priority"] : showPriority ? GRIDS["1-priority"] : channels.length === 1 ? GRIDS["1"] : GRIDS["0"];
  return (
    <div>
      <div className={`${GRID} border-b border-line pb-2.5`}>
        <h2 className="font-display text-[19px] font-bold">Events</h2>
        {channels.map((channel) => (
          <span key={channel} className={HEAD}>
            {CHANNEL_LABEL[channel]}
          </span>
        ))}
        {showPriority && <span className={HEAD}>Priority</span>}
      </div>
      {rules.map((rule) => (
        <div key={rule.event_type} className={`${GRID} border-b border-row py-3 last:border-0`}>
          <span className="flex flex-col gap-0.5">
            <span className="text-sm">{rule.label}</span>
            {HINTS[rule.event_type] && <span className="text-xs text-faint">{HINTS[rule.event_type]}</span>}
          </span>
          {channels.map((channel) => (
            <span key={channel} className="flex justify-center">
              <Checkbox
                aria-label={`${rule.label} ${channel === "email" ? "email" : "Gotify"}`}
                checked={rule[channel]}
                onChange={(e) => onChange({ ...rule, [channel]: e.target.checked })}
              />
            </span>
          ))}
          {showPriority && (
            <span className="flex flex-col items-stretch gap-0.5">
              <select
                aria-label={`${rule.label} Gotify priority`}
                value={rule.priority}
                disabled={!rule.gotify}
                onChange={(e) => onChange({ ...rule, priority: Number(e.target.value) })}
                className={`h-9 rounded-md border bg-bg px-2 font-mono text-[12.5px] text-text disabled:opacity-40 ${
                  rule.priority !== rule.default_priority ? "border-accent" : "border-line2"
                }`}
              >
                {PRIORITIES.map((n) => (
                  <option key={n} value={n}>
                    {priorityLabel(n)}
                    {n === rule.default_priority ? " (default)" : ""}
                  </option>
                ))}
              </select>
              {rule.priority !== rule.default_priority && rule.gotify && (
                <span className="text-center text-[11px] text-accent-text">custom · default {rule.default_priority}</span>
              )}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
