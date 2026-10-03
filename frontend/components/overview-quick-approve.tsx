"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button, inputClass } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { useFeatures } from "@/lib/features";
import { formatDateTime } from "@/lib/format";
import { lanOnlyAllowed } from "@/lib/provider-status";
import { useSettings } from "@/lib/settings-context";
import type { Approval, Device, Group } from "@/lib/types";

function timeOf(iso: string | null, tz: string, format: "24h" | "12h"): string {
  const full = formatDateTime(iso, tz, format);
  return full === "—" ? "—" : full.slice(6);
}

export function QuickApproveCard({ device, groups, onDone }: { device: Device; groups: Group[]; onDone: (text: string) => void }) {
  const { settings } = useSettings();
  const { features } = useFeatures();
  const lanOnly = lanOnlyAllowed(features);
  const [name, setName] = useState(device.dhcp_hostname ?? device.name);
  const [groupId, setGroupId] = useState<number | "">("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function approve(access?: "lan_only") {
    if (groupId === "") {
      setError("Choose a group first.");
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      const body: Record<string, unknown> = { name: name.trim(), group_id: groupId };
      if (access) body.access = access;
      const result = await api.post<Approval>(`/devices/${device.id}/approve`, body);
      onDone(`${result.device.name} approved on ${result.device.static_ip}`);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function block() {
    if (!window.confirm(`Block ${device.name}? It will get no network.`)) return;
    setBusy(true);
    try {
      await api.post<Approval>(`/devices/${device.id}/block`);
      onDone(`${device.name} blocked`);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flex flex-col gap-3.5 rounded-[14px] border border-accent-line bg-card p-5">
      <span className="text-xs font-semibold uppercase tracking-[.08em] text-accent-text">
        New device · {timeOf(device.first_seen, settings.timezone, settings.time_format)}
      </span>
      <h2 className="font-display text-[28px] font-bold leading-tight break-all">{device.name}</h2>
      <div className="flex flex-col gap-2 text-sm">
        <div className="flex justify-between gap-3">
          <span className="text-faint">MAC</span>
          <span className="font-mono">{device.mac ?? "—"}</span>
        </div>
        <div className="flex justify-between gap-3">
          <span className="text-faint">Vendor</span>
          <span className="truncate">{device.vendor ?? (device.private_mac ? "Private MAC" : "Unknown")}</span>
        </div>
        <div className="flex justify-between gap-3">
          <span className="text-faint">Current IP</span>
          <span className="font-mono text-accent-text">{device.last_ip ?? "—"}</span>
        </div>
      </div>
      <input aria-label="Name" className={inputClass} value={name} onChange={(e) => setName(e.target.value)} maxLength={64} />
      <select aria-label="Group" className={inputClass} value={groupId} onChange={(e) => setGroupId(Number(e.target.value))}>
        <option value="" disabled>
          Choose a group…
        </option>
        {groups.map((g) => (
          <option key={g.id} value={g.id}>
            {g.name}
          </option>
        ))}
      </select>
      {error && (
        <p role="alert" className="text-sm text-bad">
          {error}
        </p>
      )}
      <Button variant="primary" className="h-[52px] text-base" disabled={busy} onClick={() => void approve()}>
        Approve
      </Button>
      <div className={lanOnly ? "grid grid-cols-2 gap-2.5" : "grid gap-2.5"}>
        {lanOnly && (
          <Button disabled={busy} onClick={() => void approve("lan_only")}>
            LAN only
          </Button>
        )}
        <Button variant="danger" disabled={busy} onClick={() => void block()}>
          Block
        </Button>
      </div>
    </section>
  );
}

export function PendingLinkCard({ device }: { device: Device }) {
  const { settings } = useSettings();
  return (
    <Link href={`/pending#${device.id}`} className="flex items-center justify-between gap-3 rounded-[14px] border border-line bg-card px-[18px] py-4">
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-[15px] font-semibold text-text">{device.name}</span>
        <span className="text-xs text-muted">
          {device.private_mac ? "private MAC" : device.vendor ?? "unknown vendor"} · {timeOf(device.first_seen, settings.timezone, settings.time_format)}
        </span>
      </span>
      <ChevronRight className="size-4 text-accent-text" aria-hidden />
    </Link>
  );
}
