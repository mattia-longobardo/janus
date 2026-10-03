"use client";

import Link from "next/link";
import { useState } from "react";

import { ApproveForm } from "@/components/approve-form";
import { InfoCard, InfoRow } from "@/components/device-info";
import { Card, Notice } from "@/components/ui";
import { describeEvent } from "@/lib/events";
import { useFeatures } from "@/lib/features";
import { formatDateTime, ipSortKey, relativeTime } from "@/lib/format";
import { hasCapability } from "@/lib/provider-status";
import { useSettings } from "@/lib/settings-context";
import type { Approval, Device, EventItem, Group } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

const EVENT_DOT: Record<string, string> = {
  "device.new": "bg-accent",
  "notify.failed": "bg-bad",
  "ip.conflict": "bg-bad",
  "device.approved": "bg-ok",
  "device.blocked": "bg-bad",
};

const ENFORCEMENT: Record<string, string> = {
  "dry-run": "saved (provider sync is in dry-run)",
  "no provider": "saved (no network provider: Janus only records it)",
};

export default function PendingPage() {
  const { settings } = useSettings();
  const { features } = useFeatures();
  const devicesRes = useResource<Device[]>("/devices?access=pending", { refreshMs: 15_000 });
  const groupsRes = useResource<Group[]>("/groups");
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string }>();
  const pending = devicesRes.data ?? [];
  const groups = groupsRes.data ?? [];

  function done(result: Approval) {
    const enforcement = ENFORCEMENT[result.enforcement] ?? result.enforcement;
    const what = result.device.access === "blocked" ? "blocked" : `approved on ${result.device.static_ip}`;
    setNotice({ tone: result.enforcement.startsWith("failed") ? "error" : "success", text: `${result.device.name} ${what} — ${enforcement}` });
    void devicesRes.reload();
  }

  return (
    <div className="flex flex-col gap-6">
      <Link href="/" className="self-start text-sm no-underline">
        <span className="text-ok hover:text-text">← Back to overview</span>
      </Link>
      {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
      {devicesRes.error && <Notice tone="error">{devicesRes.error}</Notice>}
      {!devicesRes.loading && pending.length === 0 && (
        <>
          <header className="flex flex-col gap-1.5">
            <h1 className="font-display text-[30px] font-bold tracking-[-0.02em] lg:text-[36px]">Pending devices</h1>
            <p className="font-mono text-[13px] text-faint">nothing waiting</p>
          </header>
          <Card className="p-8 text-center text-muted">Nothing is waiting. New devices appear here as soon as they connect.</Card>
        </>
      )}
      {pending.map((device, index) => (
        <PendingDevice key={device.id} device={device} groups={groups} onDone={done} first={index === 0} quarantine={hasCapability(features, "dhcp", "quarantine") ? settings.network : null} />
      ))}
    </div>
  );
}

function PendingDevice({
  device,
  groups,
  onDone,
  first,
  quarantine,
}: {
  device: Device;
  groups: Group[];
  onDone: (result: Approval) => void;
  first: boolean;
  quarantine: { quarantine_start: string; quarantine_end: string } | null; // null: the DHCP provider has no quarantine pool
}) {
  const { settings } = useSettings();
  const eventsRes = useResource<EventItem[]>(device.mac ? `/events?mac=${encodeURIComponent(device.mac)}&limit=10` : null);
  const inQuarantine =
    quarantine !== null &&
    device.last_ip !== null &&
    ipSortKey(device.last_ip) >= ipSortKey(quarantine.quarantine_start) &&
    ipSortKey(device.last_ip) <= ipSortKey(quarantine.quarantine_end);
  const time = (iso: string | null) => formatDateTime(iso, settings.timezone, settings.time_format);
  const events = eventsRes.data ?? [];

  return (
    <section id={device.id} className={first ? "flex flex-col gap-6" : "flex flex-col gap-6 border-t border-line pt-8"}>
      <header className="flex flex-wrap items-end justify-between gap-6">
        <div className="flex min-w-0 flex-col gap-1.5">
          <h1 className="break-words font-display text-[30px] font-bold tracking-[-0.02em] lg:text-[36px]">{device.name}</h1>
          <p className="font-mono text-[13px] text-faint">
            new device · {inQuarantine ? "in quarantine" : "detected"} · first seen {relativeTime(device.first_seen)}
          </p>
        </div>
        <span className="inline-flex h-[34px] items-center rounded-full border border-accent-line px-3.5 text-[13px] font-medium text-accent-text">
          Waiting for approval
        </span>
      </header>
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <div className="flex flex-col gap-5">
          <InfoCard title="What we know">
            <InfoRow labelWidth={150} label="MAC" mono value={device.mac ?? "—"} />
            <InfoRow labelWidth={150} label="Vendor (OUI)" mono value={device.vendor ?? (device.private_mac ? "hidden (private MAC)" : "unknown")} />
            <InfoRow labelWidth={150} label="DHCP hostname" mono value={device.dhcp_hostname ?? "— not sent —"} />
            <InfoRow labelWidth={150} label="First seen" mono value={time(device.first_seen)} />
            <InfoRow labelWidth={150} label="Last seen" mono value={device.online ? "now" : time(device.last_seen)} />
            <InfoRow labelWidth={150} label="Current IP" mono value={device.last_ip ? `${device.last_ip}${inQuarantine ? " (quarantine)" : ""}` : "—"} />
            <InfoRow labelWidth={150} label="Private MAC" mono value={device.private_mac ? "Yes" : "No"} />
          </InfoCard>
          <InfoCard title="Events">
            {events.length === 0 ? (
              <p className="py-2 text-sm text-muted">No events for this device yet.</p>
            ) : (
              <ol className="flex flex-col">
                {events.map((event) => (
                  <li key={event.id} className="grid grid-cols-[96px_14px_1fr] items-start gap-3 py-[7px]">
                    <span className="font-mono text-xs text-faint">{time(event.ts)}</span>
                    <span className={`mt-[5px] size-2 rounded-full ${EVENT_DOT[event.type] ?? "bg-muted"}`} aria-hidden />
                    <span className="text-sm text-text2">{describeEvent(event)}</span>
                  </li>
                ))}
              </ol>
            )}
          </InfoCard>
        </div>
        <ApproveForm device={device} groups={groups} onApproved={onDone} onBlocked={onDone} />
      </div>
    </section>
  );
}
