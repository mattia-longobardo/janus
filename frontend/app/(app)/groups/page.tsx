"use client";

import clsx from "clsx";
import { Plus } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { CompactGroup } from "@/components/compact-group";
import { HoursRule } from "@/components/hours-rule";
import { ColorPicker, IconPicker, PALETTE } from "@/components/look-picker";
import { Button, Card, Field, IconTile, Notice, PageHeader, SCROLL_TARGET, Segmented, inputClass } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { useFeatures } from "@/lib/features";
import { ACCESS_LABELS } from "@/lib/format";
import { PENDING_COLOR, QuarantineIcon, guestLook, iconFor } from "@/lib/group-icons";
import { guestPool, lastOctet, rangeUsage } from "@/lib/ipplan";
import { hasCapability, lanOnlyAllowed } from "@/lib/provider-status";
import { useSettings } from "@/lib/settings-context";
import type { Access, Device, Group } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

import { GuestEditor } from "./guest-editor";

const ROW = "grid grid-cols-[34px_1fr_90px_56px] items-center gap-3.5 px-4 sm:grid-cols-[34px_1fr_110px_60px_120px]";
const HEAD = "text-xs font-medium uppercase tracking-[.06em] text-faint";

type Draft = Omit<Group, "id" | "device_count">;
const EMPTY: Draft = {
  name: "",
  color: PALETTE[0],
  icon: "device",
  range_start: "",
  range_end: "",
  default_access: "authorized",
  offline_alert_hours: null,
  scan_enabled: false,
  scan_interval_hours: 168,
};

function span(start: string, end: string): string {
  return `.${lastOctet(start)}–.${lastOctet(end)}`;
}

export default function GroupsPage() {
  const { settings } = useSettings();
  const { features } = useFeatures();
  const groupsRes = useResource<Group[]>("/groups");
  const devicesRes = useResource<Device[]>("/devices");
  const [selected, setSelected] = useState<number | "new" | "guests" | null>(null);
  const [opened, setOpened] = useState(0);
  const editorRef = useRef<HTMLDivElement>(null);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string }>();
  const groups = groupsRes.data ?? [];
  const devices = devicesRes.data ?? [];
  const current = typeof selected === "number" ? groups.find((g) => g.id === selected) : undefined;
  const pendingCount = devices.filter((d) => d.access === "pending").length;
  const quarantineOn = hasCapability(features, "dhcp", "quarantine");
  const guestsOn = Boolean(features?.guests?.enabled);
  const guestsRes = useResource<Device[]>(guestsOn ? "/devices?access=guest" : null);
  const pool = guestPool(settings.network);
  const guestTile = guestLook(features);
  const guests = guestsRes.data ?? [];

  function open(value: number | "new" | "guests") {
    setSelected(value);
    setOpened((n) => n + 1);
  }

  // Below xl the editor sits under the list, usually off-screen on a phone: bring it into view on every pick.
  useEffect(() => {
    if (opened === 0 || window.matchMedia?.("(min-width: 1280px)").matches) return;
    editorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [opened]);

  return (
    <>
      <PageHeader
        title="Groups"
        subtitle="people and device categories · each owns an IP range and a default policy"
        actions={
          <Button variant="primary" onClick={() => open("new")}>
            <Plus className="size-4" aria-hidden />
            New group
          </Button>
        }
      />
      {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
      {groupsRes.error && <Notice tone="error">{groupsRes.error}</Notice>}
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <Card className="overflow-hidden">
          <div className={clsx(ROW, "border-b border-line py-3")}>
            <span />
            <span className={HEAD}>Group</span>
            <span className={HEAD}>Range</span>
            <span className={HEAD}>Devices</span>
            <span className={clsx(HEAD, "hidden sm:block")}>Default access</span>
          </div>
          {groups.map((g) => (
            <button
              key={g.id}
              type="button"
              aria-pressed={selected === g.id}
              onClick={() => open(g.id)}
              className={clsx(ROW, "w-full border-b border-row py-3 text-left text-text", selected === g.id ? "bg-accent-soft" : "hover:bg-card2")}
            >
              <IconTile Icon={iconFor(g.icon)} color={g.color} size={34} />
              <span className="truncate text-[15px] font-semibold">{g.name}</span>
              <span className="font-mono text-[13px] text-muted">{span(g.range_start, g.range_end)}</span>
              <span className="font-mono text-[13px] text-text2">{g.device_count}</span>
              <span className="hidden text-[13px] text-muted sm:block">{ACCESS_LABELS[g.default_access]}</span>
            </button>
          ))}
          {quarantineOn && (
            <div className={clsx(ROW, "py-3 text-text")} title="The DHCP pool for unknown devices, set in Settings → Network">
              <IconTile Icon={QuarantineIcon} color={PENDING_COLOR} size={34} />
              <span className="text-[15px] font-semibold">Quarantine</span>
              <span className="font-mono text-[13px] text-muted">{span(settings.network.quarantine_start, settings.network.quarantine_end)}</span>
              <span className="font-mono text-[13px] text-text2">{pendingCount}</span>
              <span className="hidden text-[13px] text-muted sm:block">Quarantine</span>
            </div>
          )}
          {guestsOn && (
            <button
              type="button"
              aria-pressed={selected === "guests"}
              onClick={() => open("guests")}
              className={clsx(
                ROW,
                "w-full py-3 text-left text-text",
                quarantineOn && "border-t border-row",
                selected === "guests" ? "bg-accent-soft" : "hover:bg-card2",
              )}
            >
              <IconTile Icon={guestTile.Icon} color={guestTile.color} size={34} />
              <span className="text-[15px] font-semibold">Guests</span>
              <span className="font-mono text-[13px] text-muted">{pool ? span(pool.start, pool.end) : "no pool"}</span>
              <span className="font-mono text-[13px] text-text2">{guests.length}</span>
              <span className="hidden text-[13px] text-muted sm:block">{ACCESS_LABELS.guest}</span>
            </button>
          )}
        </Card>
        <div ref={editorRef} className={SCROLL_TARGET}>
          {selected === null ? (
            <Card className="p-6 text-sm text-muted">Select a group to edit it, or create a new one.</Card>
          ) : selected === "guests" ? (
            <GuestEditor
              guests={guests}
              onDone={async (text) => {
                setNotice({ tone: "success", text });
                setSelected(null);
                await guestsRes.reload();
              }}
              onError={(text) => setNotice({ tone: "error", text })}
            />
          ) : (
            <GroupEditor
              key={selected}
              group={current}
              devices={devices}
              onDone={async (text) => {
                setNotice({ tone: "success", text });
                setSelected(null);
                await groupsRes.reload();
              }}
              onError={(text) => setNotice({ tone: "error", text })}
            />
          )}
        </div>
      </div>
    </>
  );
}

function GroupEditor({
  group,
  devices,
  onDone,
  onError,
}: {
  group?: Group;
  devices: Device[];
  onDone: (text: string) => Promise<void>;
  onError: (text: string) => void;
}) {
  const [draft, setDraft] = useState<Draft>(group ? { ...group } : EMPTY);
  const { features } = useFeatures();
  // Keep LAN only on a group that already has it, so the editor never shows a value it cannot display.
  const lanOnly = lanOnlyAllowed(features) || group?.default_access === "lan_only";
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const usage = group ? rangeUsage(group, devices) : null;
  const free = usage ? usage.total - usage.used : null;

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      if (group) {
        await api.patch(`/groups/${group.id}`, draft);
        await onDone(`${draft.name} saved.`);
      } else {
        await api.post("/groups", draft);
        await onDone(`${draft.name} created.`);
      }
    } catch (err) {
      onError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!group || !window.confirm(`Delete ${group.name}?`)) return;
    try {
      await api.del(`/groups/${group.id}`);
      await onDone(`${group.name} deleted.`);
    } catch (err) {
      onError(errorText(err));
    }
  }

  const rangeHint =
    free === null || !group
      ? undefined
      : free <= 2
        ? `${free} free · widen to .${Math.min(254, lastOctet(group.range_end) + 10)} to grow`
        : `${free} free`;

  return (
    <Card className="p-6">
      <form onSubmit={save} className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-display text-[22px] font-bold">{group ? draft.name || group.name : "New group"}</h2>
          {group && usage && (
            <span className="font-mono text-xs text-faint">
              {group.device_count} devices · {usage.used}/{usage.total} IPs used
            </span>
          )}
        </div>
        <Field label="Name">
          <input className={inputClass} value={draft.name} onChange={(e) => set("name", e.target.value)} required maxLength={64} />
        </Field>
        <ColorPicker value={draft.color} onChange={(color) => set("color", color)} />
        <IconPicker value={draft.icon} onChange={(icon) => set("icon", icon)} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Range start">
            <input className={`${inputClass} font-mono`} value={draft.range_start} onChange={(e) => set("range_start", e.target.value)} required />
          </Field>
          <Field label="Range end" hint={rangeHint}>
            <input className={`${inputClass} font-mono`} value={draft.range_end} onChange={(e) => set("range_end", e.target.value)} required />
          </Field>
        </div>
        {group && (
          <CompactGroup group={group} onDone={(text) => void onDone(text)} onError={onError} />
        )}
        <div className="flex flex-col gap-2">
          <span className="text-[13px] font-medium text-text2">Default access for new members</span>
          <div>
            <Segmented<Access>
              label="Default access"
              value={draft.default_access}
              onChange={(value) => set("default_access", value)}
              options={[
                { value: "authorized", label: ACCESS_LABELS.authorized },
                ...(lanOnly ? [{ value: "lan_only" as const, label: ACCESS_LABELS.lan_only }] : []),
              ]}
            />
          </div>
          {lanOnly && (
            <span className="text-xs text-faint">
              LAN only: the device gets no gateway, so it talks to home devices but never reaches the internet.
            </span>
          )}
        </div>
        <div className="grid items-end gap-4 sm:grid-cols-2">
          <HoursRule
            label="Alert when a member is offline for more than"
            checkboxLabel="Offline alerts"
            inputLabel="Offline hours"
            checked={draft.offline_alert_hours !== null}
            onToggle={(on) => set("offline_alert_hours", on ? draft.offline_alert_hours ?? 24 : null)}
            value={draft.offline_alert_hours ?? ""}
            onValue={(value) => set("offline_alert_hours", value ? Number(value) : 1)}
          />
          <HoursRule
            label="Scan members for open ports every"
            checkboxLabel="Scheduled port scans"
            inputLabel="Scan interval hours"
            checked={draft.scan_enabled}
            onToggle={(on) => set("scan_enabled", on)}
            value={draft.scan_interval_hours}
            onValue={(value) => set("scan_interval_hours", Number(value) || 1)}
            max={720}
          />
        </div>
        <div className="flex flex-wrap justify-between gap-3 border-t border-line pt-4">
          {group ? (
            <Button variant="danger" onClick={() => void remove()}>
              Delete group
            </Button>
          ) : (
            <span />
          )}
          <Button type="submit" variant="primary" disabled={busy}>
            {group ? "Save changes" : "Create group"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

