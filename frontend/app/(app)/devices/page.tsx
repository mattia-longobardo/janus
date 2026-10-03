"use client";

import { FileSpreadsheet } from "lucide-react";
import { useMemo, useState } from "react";

import { DeviceTable } from "@/components/device-table";
import { Chip, Notice, inputClass } from "@/components/ui";
import { errorText } from "@/lib/api";
import { deleteDevice } from "@/lib/delete-device";
import { filterDevices } from "@/lib/filter";
import { ACCESS_LABELS } from "@/lib/format";
import type { Access, Device, Group } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

export default function DevicesPage() {
  const devicesRes = useResource<Device[]>("/devices", { refreshMs: 15_000 });
  const groupsRes = useResource<Group[]>("/groups");
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string }>();

  async function remove(device: Device) {
    try {
      if (!(await deleteDevice(device))) return;
      setNotice({ tone: "success", text: `${device.name} deleted.` });
      await devicesRes.reload();
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err) });
    }
  }
  const [groupId, setGroupId] = useState<number | "all" | "issues">("all");
  const [access, setAccess] = useState<Access | "all">("all");
  const groups = useMemo(() => groupsRes.data ?? [], [groupsRes.data]);
  const devices = useMemo(() => devicesRes.data ?? [], [devicesRes.data]);
  const base = useMemo(() => filterDevices(devices, { query, groupId: "all", access }), [devices, query, access]);
  const attention = base.filter((d) => d.health !== "ok");
  const shown = groupId === "all" ? base : groupId === "issues" ? attention : base.filter((d) => d.group_id === groupId);
  const chips = groups.map((g) => ({ group: g, count: base.filter((d) => d.group_id === g.id).length })).filter((c) => c.count > 0);
  const online = devices.filter((d) => d.online).length;
  const exportParams = new URLSearchParams();
  if (typeof groupId === "number") exportParams.set("group_id", String(groupId));
  if (access !== "all") exportParams.set("access", access);
  const exportHref = `/api/devices/export.xlsx${exportParams.size ? `?${exportParams}` : ""}`;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h1 className="font-display text-[32px] font-bold tracking-[-0.02em] lg:text-4xl">Devices</h1>
          <p className="font-mono text-[13px] text-faint">
            {devices.length} known · {online} online · {devices.filter((d) => d.access === "pending").length} pending
          </p>
        </div>
        <a
          href={exportHref}
          download
          className="inline-flex h-11 items-center gap-2 rounded-lg border border-line2 bg-card px-[18px] text-sm font-medium text-text hover:bg-card2"
        >
          <FileSpreadsheet className="size-4" aria-hidden />
          Download Excel
        </a>
      </header>
      {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
      {devicesRes.error && <Notice tone="error">{devicesRes.error}</Notice>}
      <section className="overflow-hidden rounded-[14px] border border-line bg-card">
        <div className="flex flex-col gap-3 px-5 py-4 lg:flex-row lg:items-center">
          <label className="flex h-11 items-center gap-2 rounded-lg border border-line2 bg-bg px-3.5 text-faint lg:w-[260px]">
            <span className="font-mono text-xs" aria-hidden>
              /
            </span>
            <input
              type="search"
              aria-label="Search devices"
              placeholder="Name, IP or MAC"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full bg-transparent text-sm text-text outline-none placeholder:text-faint"
            />
          </label>
          <label className="lg:w-48">
            <span className="sr-only">Access</span>
            <select className={inputClass} value={access} onChange={(e) => setAccess(e.target.value as Access | "all")}>
              <option value="all">Any access</option>
              {(Object.keys(ACCESS_LABELS) as Access[]).filter((key) => key !== "guest").map((key) => (
                <option key={key} value={key}>
                  {ACCESS_LABELS[key]}
                </option>
              ))}
            </select>
          </label>
          <div className="flex flex-wrap gap-2 lg:ml-auto lg:justify-end">
            <Chip active={groupId === "all"} count={base.length} onClick={() => setGroupId("all")}>
              All
            </Chip>
            {attention.length > 0 && (
              <Chip active={groupId === "issues"} count={attention.length} onClick={() => setGroupId("issues")}>
                <span className={attention.some((d) => d.health === "critical") ? "text-bad" : "text-accent-text"}>Needs attention</span>
              </Chip>
            )}
            {chips.map(({ group, count }) => (
              <Chip key={group.id} active={groupId === group.id} count={count} onClick={() => setGroupId(group.id)}>
                {group.name}
              </Chip>
            ))}
          </div>
        </div>
        <DeviceTable devices={shown} groups={groups} onDelete={(d) => void remove(d)} />
      </section>
    </div>
  );
}
