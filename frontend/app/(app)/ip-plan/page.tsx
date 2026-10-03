"use client";

import Link from "next/link";
import type { CSSProperties } from "react";

import { devicesCsv } from "@/components/ip-plan-export";
import { Button, Card, Notice, PageHeader } from "@/components/ui";
import { useFeatures } from "@/lib/features";
import { GUEST_COLOR, PENDING_COLOR } from "@/lib/group-icons";
import { buildCells, guestPool, inPool, lastOctet, poolUsage, rangeUsage, type Cell } from "@/lib/ipplan";
import { hasCapability } from "@/lib/provider-status";
import { useSettings } from "@/lib/settings-context";
import type { Device, Group } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

const GATEWAY_COLOR = "#C9CDD0";
const UNASSIGNED: CSSProperties = { background: "transparent", color: "var(--faint)", border: "1px solid var(--line)" };

function solid(color: string): CSSProperties {
  return { background: color, color: "#0E1113", border: `1px solid ${color}` };
}

function tint(color: string): CSSProperties {
  return { background: `${color}22`, color: "var(--text2)", border: `1px solid ${color}66` };
}

export default function IpPlanPage() {
  const { settings } = useSettings();
  const { features } = useFeatures();
  const quarantine = hasCapability(features, "dhcp", "quarantine");
  // The pool only matters while guests are on; guests are not in /devices, so they come from their own list.
  const pool = features?.guests?.enabled ? guestPool(settings.network) : null;
  const guestsRes = useResource<Device[]>(pool ? "/devices?access=guest" : null);
  const guestUsage = pool ? poolUsage(pool, guestsRes.data ?? []) : null;
  const devicesRes = useResource<Device[]>("/devices");
  const groupsRes = useResource<Group[]>("/groups");
  const devices = devicesRes.data ?? [];
  const groups = groupsRes.data ?? [];
  const cells = buildCells(groups, devices, settings.network.gateway);
  const qStart = lastOctet(settings.network.quarantine_start);
  const qEnd = lastOctet(settings.network.quarantine_end);
  const gateway = lastOctet(settings.network.gateway);
  const inUse = devices.filter((d) => d.static_ip).length;

  function cellStyle(cell: Cell): CSSProperties {
    if (cell.octet === gateway) return solid(GATEWAY_COLOR);
    if (cell.octet === 0 || cell.octet === 255) return UNASSIGNED;
    if (cell.device) return solid(cell.group?.color ?? GATEWAY_COLOR);
    if (cell.group) return tint(cell.group.color);
    if (quarantine && cell.octet >= qStart && cell.octet <= qEnd) return tint(PENDING_COLOR);
    if (inPool(cell.octet, pool)) return tint(GUEST_COLOR);
    return UNASSIGNED;
  }

  function cellTitle(cell: Cell): string {
    if (cell.octet === gateway) return `.${cell.octet} — gateway`;
    if (cell.device) return `.${cell.octet} — ${cell.device.name}`;
    if (cell.group) return `.${cell.octet} — free in ${cell.group.name}`;
    if (quarantine && cell.octet >= qStart && cell.octet <= qEnd) return `.${cell.octet} — quarantine pool`;
    if (inPool(cell.octet, pool)) return `.${cell.octet} — guest pool`;
    return `.${cell.octet} — unassigned`;
  }

  function exportCsv() {
    const blob = new Blob([devicesCsv(devices, groups)], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "janus-ip-plan.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <PageHeader
        title="IP plan"
        subtitle={`${settings.network.subnet} · ${inUse} in use · one range per group`}
        actions={
          <Button onClick={exportCsv} disabled={devices.length === 0}>
            Export
          </Button>
        }
      />
      {devicesRes.error && <Notice tone="error">{devicesRes.error}</Notice>}
      <div className="flex flex-col items-start gap-6 xl:flex-row">
        <Card aria-label="Address map" className="max-w-full overflow-x-auto p-[22px]">
          <div role="grid" aria-label="Addresses" className="grid w-[640px] grid-cols-16 gap-[5px] lg:w-[776px]">
            {cells.map((cell) => (
              <div
                key={cell.octet}
                role="gridcell"
                title={cellTitle(cell)}
                className="flex h-9 items-center justify-center rounded-md font-mono text-xs font-medium lg:h-11"
                style={cellStyle(cell)}
              >
                {cell.octet}
              </div>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-5 text-xs text-muted">
            <span className="flex items-center gap-1.5">
              <span className="size-3.5 rounded" style={{ background: "#6FB7FF" }} />
              in use
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-3.5 rounded" style={tint("#6FB7FF")} />
              free in range
            </span>
            {quarantine && (
              <span className="flex items-center gap-1.5">
                <span className="size-3.5 rounded" style={tint(PENDING_COLOR)} />
                quarantine pool
              </span>
            )}
            {pool && (
              <span className="flex items-center gap-1.5">
                <span className="size-3.5 rounded" style={tint(GUEST_COLOR)} />
                guest pool
              </span>
            )}
            <span className="flex items-center gap-1.5">
              <span className="size-3.5 rounded border border-line" />
              unassigned
            </span>
          </div>
        </Card>
        <Card className="flex w-full min-w-0 flex-col p-[22px] xl:flex-1">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="font-display text-[19px] font-bold">Ranges</h2>
            <Link href="/groups" className="text-[13px] text-ok underline hover:text-text">
              Edit groups →
            </Link>
          </div>
          {groups.map((g) => {
            const usage = rangeUsage(g, devices);
            return (
              <div key={g.id} className="grid grid-cols-[14px_1fr_auto] items-center gap-3 border-b border-row py-[9px]">
                <span className="size-3 rounded-[3px]" style={{ background: g.color }} />
                <span className="flex flex-col gap-0.5">
                  <span className="text-sm font-medium">{g.name}</span>
                  <span className="font-mono text-xs text-faint">
                    .{lastOctet(g.range_start)}–.{lastOctet(g.range_end)}
                  </span>
                </span>
                <span className="font-mono text-[13px] text-text2">
                  {usage.used}/{usage.total}
                </span>
              </div>
            );
          })}
          {quarantine && (
            <div className="grid grid-cols-[14px_1fr_auto] items-center gap-3 py-[9px]">
              <span className="size-3 rounded-[3px]" style={{ background: PENDING_COLOR }} />
              <span className="flex flex-col gap-0.5">
                <span className="text-sm font-medium">Quarantine</span>
                <span className="font-mono text-xs text-faint">
                  .{qStart}–.{qEnd}
                </span>
              </span>
              <span className="font-mono text-[13px] text-text2">
                {devices.filter((d) => d.access === "pending").length}/{qEnd - qStart + 1}
              </span>
            </div>
          )}
          {pool && guestUsage && (
            <div className="grid grid-cols-[14px_1fr_auto] items-center gap-3 py-[9px]">
              <span className="size-3 rounded-[3px]" style={{ background: GUEST_COLOR }} />
              <span className="flex flex-col gap-0.5">
                <span className="text-sm font-medium">Guests</span>
                <span className="font-mono text-xs text-faint">
                  .{lastOctet(pool.start)}–.{lastOctet(pool.end)}
                </span>
              </span>
              <span className="font-mono text-[13px] text-text2">
                {guestUsage.used}/{guestUsage.total}
              </span>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
