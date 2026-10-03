"use client";

import { ArrowDown, ArrowUp, ArrowUpDown, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { HealthIcon } from "@/components/health";
import { Badge, IconTile, Pagination, StatusDot } from "@/components/ui";
import { useFeatures } from "@/lib/features";
import { deviceLook, guestLook } from "@/lib/group-icons";
import { ACCESS_LABELS, deviceIp, formatDateTime, ipSortKey, relativeTime } from "@/lib/format";
import { useSettings } from "@/lib/settings-context";
import type { Device, Group } from "@/lib/types";

type SortKey = "status" | "name" | "group" | "ip" | "mac" | "vendor" | "seen";
type SortDir = "asc" | "desc";

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "status", label: "Status" },
  { key: "name", label: "Name" },
  { key: "group", label: "Group" },
  { key: "ip", label: "Static IP" },
  { key: "mac", label: "MAC" },
  { key: "vendor", label: "Vendor" },
  { key: "seen", label: "Seen" },
];

const text = (value: string | null | undefined) => (value ?? "").toLowerCase();

export function sortDevices(devices: Device[], groups: Group[], key: SortKey, dir: SortDir): Device[] {
  const groupName = (d: Device) => text(groups.find((g) => g.id === d.group_id)?.name);
  const seen = (d: Device) => (d.online ? Number.MAX_SAFE_INTEGER : d.last_seen ? Date.parse(d.last_seen) : 0);
  const compare: Record<SortKey, (a: Device, b: Device) => number> = {
    status: (a, b) => Number(b.online) - Number(a.online),
    name: (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" }),
    group: (a, b) => groupName(a).localeCompare(groupName(b)),
    ip: (a, b) => ipSortKey(deviceIp(a)) - ipSortKey(deviceIp(b)),
    mac: (a, b) => text(a.mac).localeCompare(text(b.mac)),
    vendor: (a, b) => {
      if (!a.vendor !== !b.vendor) return a.vendor ? -1 : 1;
      return text(a.vendor).localeCompare(text(b.vendor));
    },
    seen: (a, b) => seen(b) - seen(a),
  };
  const sign = dir === "asc" ? 1 : -1;
  const byIp = compare.ip;
  return [...devices].sort((a, b) => sign * compare[key](a, b) || byIp(a, b));
}
const PAGE_SIZE_KEY = "janus.pageSize";

function storedPageSize(): number {
  try {
    const value = Number(localStorage.getItem(PAGE_SIZE_KEY));
    return [10, 25, 50, 100].includes(value) ? value : 25;
  } catch {
    return 25;
  }
}

export function DeviceTable({
  devices,
  groups,
  paginate = true,
  onDelete,
}: {
  devices: Device[];
  groups: Group[];
  paginate?: boolean;
  onDelete?: (device: Device) => void;
}) {
  const { settings } = useSettings();
  const guest = guestLook(useFeatures().features);
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir } | null>(null);
  const [pageSize, setPageSize] = useState(25);
  useEffect(() => setPageSize(storedPageSize()), []);
  const pages = Math.max(1, Math.ceil(devices.length / pageSize));
  useEffect(() => {
    if (page > pages - 1) setPage(pages - 1);
  }, [page, pages]);

  if (devices.length === 0) return <p className="px-5 py-8 text-center text-sm text-muted">No devices match.</p>;
  const ordered = sort ? sortDevices(devices, groups, sort.key, sort.dir) : devices;
  const shown = paginate ? ordered.slice(page * pageSize, (page + 1) * pageSize) : ordered;

  function toggleSort(key: SortKey) {
    setSort((current) => (current?.key === key ? { key, dir: current.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
    setPage(0);
  }
  const group = (id: number | null) => groups.find((g) => g.id === id);

  function changeSize(size: number) {
    setPageSize(size);
    setPage(0);
    try {
      localStorage.setItem(PAGE_SIZE_KEY, String(size));
    } catch {
      // storage blocked: keep the size for this page only
    }
  }

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[920px] text-sm [&_td]:whitespace-nowrap">
          <thead>
            <tr className="border-y border-line text-left text-xs uppercase tracking-[.06em] text-faint">
              {COLUMNS.map((column) => {
                const active = sort?.key === column.key;
                const Arrow = !active ? ArrowUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
                    className="px-4 py-1.5 font-medium"
                  >
                    <button
                      type="button"
                      onClick={() => toggleSort(column.key)}
                      className={`-mx-1.5 inline-flex h-8 items-center gap-1.5 rounded px-1.5 uppercase tracking-[.06em] hover:text-text ${active ? "text-text" : ""}`}
                    >
                      {column.label}
                      <Arrow aria-hidden className={`size-3.5 ${active ? "" : "opacity-40"}`} />
                    </button>
                  </th>
                );
              })}
              {onDelete && (
                <th scope="col" className="sticky right-0 w-12 bg-card px-3 py-2.5">
                  <span className="sr-only">Actions</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {shown.map((d) => {
              const g = group(d.group_id);
              const { Icon, color } = deviceLook(d, groups, guest);
              return (
                <tr key={d.id} className="border-b border-row hover:bg-card2">
                  <td className="px-4 py-2.5">
                    <span className="flex items-center gap-2 text-text2">
                      <StatusDot online={d.online} />
                      {d.online ? "Online" : "Offline"}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 font-medium">
                    <span className="flex items-center gap-3">
                      <IconTile Icon={Icon} color={color} size={30} muted={!d.online} />
                      <span className="flex flex-wrap items-center gap-2">
                        <Link href={`/devices/${d.id}`} className="text-text hover:underline">
                          {d.name}
                        </Link>
                        <HealthIcon device={d} />
                        {d.private_mac && <Badge tone="accent">private MAC</Badge>}
                        {(d.access === "lan_only" || d.access === "blocked") && (
                          <Badge tone={d.access === "blocked" ? "bad" : "neutral"}>{ACCESS_LABELS[d.access]}</Badge>
                        )}
                      </span>
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-muted">{g?.name ?? "—"}</td>
                  <td className="px-4 py-2.5 font-mono text-[13px]">{d.static_ip ?? <span className="text-faint">{d.last_ip ?? "—"}</span>}</td>
                  <td className="px-4 py-2.5 font-mono text-[13px] text-muted">{d.mac ?? "—"}</td>
                  <td className="max-w-44 truncate px-4 py-2.5 text-muted" title={d.vendor ?? undefined}>{d.vendor ?? "—"}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-faint" title={formatDateTime(d.last_seen, settings.timezone, settings.time_format)}>
                    {d.online ? "now" : relativeTime(d.last_seen)}
                  </td>
                  {onDelete && (
                    <td className="sticky right-0 bg-card px-3 py-1.5 text-right">
                      <button
                        type="button"
                        aria-label={`Delete ${d.name}`}
                        title="Delete device"
                        onClick={() => onDelete(d)}
                        className="inline-flex size-9 items-center justify-center rounded-md text-faint hover:bg-row hover:text-bad"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {paginate && <Pagination page={page} pageSize={pageSize} total={devices.length} onPage={setPage} onPageSize={changeSize} />}
    </>
  );
}
