"use client";

import clsx from "clsx";
import { Clock3 } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { deleteDevice } from "@/lib/delete-device";
import { DeviceTable } from "@/components/device-table";
import { PendingLinkCard, QuickApproveCard } from "@/components/overview-quick-approve";
import { Badge, Button, Card, Chip, Notice } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { useFeatures } from "@/lib/features";
import { filterDevices } from "@/lib/filter";
import { formatDateTime } from "@/lib/format";
import { hasCapability, providerSummary } from "@/lib/provider-status";
import { useSettings } from "@/lib/settings-context";
import type { Approval, Device, Group } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

export default function OverviewPage() {
  const { settings } = useSettings();
  const { features } = useFeatures();
  const devicesRes = useResource<Device[]>("/devices", { refreshMs: 15_000 });
  const groupsRes = useResource<Group[]>("/groups");
  const [query, setQuery] = useState("");
  const [groupId, setGroupId] = useState<number | "all" | "issues">("all");
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string }>();
  const search = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      if (target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) return;
      event.preventDefault();
      search.current?.focus();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const devices = useMemo(() => devicesRes.data ?? [], [devicesRes.data]);
  const groups = useMemo(() => groupsRes.data ?? [], [groupsRes.data]);
  const approved = useMemo(() => devices.filter((d) => d.access === "authorized" || d.access === "lan_only"), [devices]);
  const pending = devices.filter((d) => d.access === "pending");
  const blocked = devices.filter((d) => d.access === "blocked");
  const online = approved.filter((d) => d.online).length;
  const searched = useMemo(() => filterDevices(approved, { query, groupId: "all", access: "all" }), [approved, query]);
  const attention = searched.filter((d) => d.health !== "ok");
  const shown = groupId === "all" ? searched : groupId === "issues" ? attention : searched.filter((d) => d.group_id === groupId);
  const groupChips = groups
    .map((g) => ({ group: g, count: searched.filter((d) => d.group_id === g.id).length }))
    .filter((chip) => chip.count > 0);
  // Quarantine wording only makes sense when the DHCP provider can park unknown devices in a pool.
  const canQuarantine = hasCapability(features, "dhcp", "quarantine");
  const quarantine = canQuarantine && settings.sync_mode === "apply";
  const pendingNote = quarantine ? "in quarantine" : settings.sync_mode === "apply" ? "detected" : "detected · dry-run";
  const summary = providerSummary(features);

  const stats = [
    { label: "Registered", value: approved.length, note: "from the IP plan", tone: "text-text" },
    { label: "Online now", value: online, note: `${approved.length - online} offline`, tone: "text-ok" },
    { label: "Pending", value: pending.length, note: pendingNote, tone: "text-accent-text" },
    { label: "Blocked", value: blocked.length, note: "MAC denied", tone: "text-bad" },
  ];

  async function block(device: Device) {
    if (!window.confirm(`Block ${device.name}? It will get no network.`)) return;
    try {
      const result = await api.post<Approval>(`/devices/${device.id}/block`);
      setNotice({ tone: "success", text: `${result.device.name} blocked — ${result.enforcement}` });
      await devicesRes.reload();
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err) });
    }
  }

  async function remove(device: Device) {
    try {
      if (!(await deleteDevice(device))) return;
      setNotice({ tone: "success", text: `${device.name} deleted.` });
      await devicesRes.reload();
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err) });
    }
  }

  async function quickDone(text: string) {
    setNotice({ tone: "success", text });
    await devicesRes.reload();
  }

  const seenAt = (iso: string | null) => {
    const full = formatDateTime(iso, settings.timezone, settings.time_format);
    return full === "—" ? "—" : full.slice(6);
  };

  return (
    <div className="flex flex-col gap-6">
      <header className="hidden flex-wrap items-end justify-between gap-6 lg:flex">
        <div className="flex min-w-0 flex-col gap-1.5">
          <h1 className="font-display text-4xl font-bold tracking-[-0.02em]">Home network</h1>
          <p className="font-mono text-[13px] text-faint">
            {settings.network.subnet} · gateway {settings.network.gateway}
            {summary ? ` · ${summary}` : ""}
          </p>
        </div>
        <label className="flex h-11 w-[260px] items-center gap-2 rounded-lg border border-line2 bg-card px-3.5 text-faint">
          <span className="font-mono text-xs" aria-hidden>
            /
          </span>
          <input
            ref={search}
            type="search"
            aria-label="Search devices"
            placeholder="Name, IP or MAC"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full bg-transparent text-sm text-text outline-none placeholder:text-faint"
          />
        </label>
      </header>

      {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
      {devicesRes.error && <Notice tone="error">{devicesRes.error}</Notice>}

      <section aria-label="Summary" className="hidden grid-cols-4 gap-4 lg:grid">
        {stats.map((stat) => (
          <Card key={stat.label} className="flex flex-col gap-1.5 px-[22px] py-5">
            <span className="text-[13px] text-muted">{stat.label}</span>
            <span className={clsx("font-display text-[40px] font-bold leading-none", stat.tone)}>{stat.value}</span>
            <span className="font-mono text-xs text-faint">{stat.note}</span>
          </Card>
        ))}
      </section>

      <section aria-label="Summary" className="grid grid-cols-3 gap-2.5 lg:hidden">
        <Card className="p-3">
          <div className="font-display text-[26px] font-bold text-ok">{online}</div>
          <div className="text-xs text-muted">online</div>
        </Card>
        <Card className={clsx("p-3", pending.length > 0 && "border-accent-line")}>
          <div className="font-display text-[26px] font-bold text-accent-text">{pending.length}</div>
          <div className="text-xs text-muted">pending</div>
        </Card>
        <Card className="p-3">
          <div className="font-display text-[26px] font-bold text-bad">{blocked.length}</div>
          <div className="text-xs text-muted">blocked</div>
        </Card>
      </section>

      {pending.length > 0 && (
        <div className="flex flex-col gap-3 lg:hidden">
          <QuickApproveCard key={pending[0].id} device={pending[0]} groups={groups} onDone={(text) => void quickDone(text)} />
          {pending.slice(1).map((d) => (
            <PendingLinkCard key={d.id} device={d} />
          ))}
        </div>
      )}

      {pending.length > 0 && (
        <section className="hidden overflow-hidden rounded-[14px] border border-accent-line bg-card lg:block">
          <div className="flex items-center justify-between gap-4 bg-accent-soft px-5 py-4">
            <div className="flex items-center gap-3">
              <Clock3 className="size-5 text-accent-text" aria-hidden />
              <h2 className="font-display text-xl font-bold">New devices waiting for approval</h2>
            </div>
            {canQuarantine && (
              <span className="text-[13px] text-accent-text">
                {quarantine ? "No internet access until you approve them" : "Detected — quarantine starts at the DHCP cutover"}
              </span>
            )}
          </div>
          {pending.map((d) => (
            <div
              key={d.id}
              className="grid grid-cols-[1.4fr_1.3fr_1fr_1fr_1.1fr_auto] items-center gap-4 border-t border-line px-5 py-3.5"
            >
              <div className="flex min-w-0 flex-col gap-1">
                <Link href={`/devices/${d.id}`} className="truncate text-[15px] font-semibold text-text hover:underline">
                  {d.name}
                </Link>
                <span className="flex items-center gap-2 text-xs text-muted">
                  {d.vendor ?? (d.private_mac ? "Private MAC" : "Unknown vendor")}
                  {d.private_mac && <Badge tone="accent">private MAC</Badge>}
                </span>
              </div>
              <span className="font-mono text-[13px] text-text2">{d.mac ?? "—"}</span>
              <span className="font-mono text-[13px] text-muted">seen at {seenAt(d.last_seen ?? d.first_seen)}</span>
              <span className="truncate text-[13px] text-muted">→ —</span>
              <span className="font-mono text-[13px] text-accent-text">{d.last_ip ?? "—"}</span>
              <div className="flex gap-2">
                <Button variant="danger" onClick={() => void block(d)}>
                  Block
                </Button>
                <Link
                  href={`/pending#${d.id}`}
                  className="inline-flex h-11 items-center rounded-lg border border-accent bg-accent px-[18px] text-sm font-semibold text-accent-ink"
                >
                  Approve…
                </Link>
              </div>
            </div>
          ))}
        </section>
      )}

      <section className="overflow-hidden rounded-[14px] border border-line bg-card">
        <div className="flex flex-col gap-3 px-5 py-4 lg:flex-row lg:items-center lg:justify-between lg:gap-4">
          <h2 className="shrink-0 whitespace-nowrap font-display text-xl font-bold">Approved devices</h2>
          <label className="flex h-11 items-center gap-2 rounded-lg border border-line2 bg-bg px-3.5 text-faint lg:hidden">
            <input
              type="search"
              aria-label="Search approved devices"
              placeholder="Name, IP or MAC"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full bg-transparent text-sm text-text outline-none placeholder:text-faint"
            />
          </label>
          <div className="flex flex-wrap gap-2 lg:justify-end">
            <Chip active={groupId === "all"} count={searched.length} onClick={() => setGroupId("all")}>
              All
            </Chip>
            {attention.length > 0 && (
              <Chip active={groupId === "issues"} count={attention.length} onClick={() => setGroupId("issues")}>
                <span className={attention.some((d) => d.health === "critical") ? "text-bad" : "text-accent-text"}>Needs attention</span>
              </Chip>
            )}
            {groupChips.map(({ group, count }) => (
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
