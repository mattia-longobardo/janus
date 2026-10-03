"use client";

import clsx from "clsx";
import { Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { CutoverReadiness } from "@/components/cutover-readiness";
import { type NetDraft, errorField, networkPatch, toDraft } from "@/components/settings-network";
import { REPEATS, nextRun, zoneLabel } from "@/components/settings-schedule";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button, Checkbox, Field, Notice, PageHeader, inputClass } from "@/components/ui";
import { ApiError, api, errorText } from "@/lib/api";
import { DAY_NAMES, describeDays, hasDay, toggleDay } from "@/lib/days";
import { useFeatures } from "@/lib/features";
import { useSettings } from "@/lib/settings-context";
import type { AppSettings, MaintenanceWindow, NetworkField } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

import { EXTRA_SECTIONS } from "./sections";
import { SectionCard } from "./sections/section-card";

const DURATIONS = [5, 10, 15, 30, 45, 60, 90, 120];
const NET_LAYOUT: { field: NetworkField; label: string; type?: "text" | "time" | "number"; suffix?: string; wide?: boolean }[] = [
  { field: "subnet", label: "Subnet" },
  { field: "gateway", label: "Gateway" },
  { field: "sentinel_interface", label: "Interface" },
  { field: "sweep_interval_s", label: "ARP sweep every", type: "number", suffix: "s" },
  { field: "pihole_url", label: "Pi-hole API", wide: true },
  { field: "quarantine_start", label: "Quarantine from" },
  { field: "quarantine_end", label: "Quarantine to" },
  { field: "scan_window_start", label: "Port scans from", type: "time" },
  { field: "scan_window_end", label: "Port scans until", type: "time" },
];
type General = Pick<AppSettings, "timezone" | "time_format">;

function NetInput({
  field,
  label,
  draft,
  onChange,
  error,
  type = "text",
  suffix,
}: {
  field: NetworkField;
  label: string;
  draft: NetDraft;
  onChange: (field: NetworkField, value: string) => void;
  error?: string;
  type?: "text" | "time" | "number";
  suffix?: string;
}) {
  const id = `net-${field}`;
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <label htmlFor={id} className="text-[13px] font-medium text-text2">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type={type}
          min={type === "number" ? 10 : undefined}
          max={type === "number" ? 3600 : undefined}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-error` : undefined}
          className={clsx(`${inputClass} font-mono`, suffix && "pr-8", error && "border-bad")}
          value={draft[field]}
          spellCheck={false}
          onChange={(e) => onChange(field, e.target.value)}
        />
        {suffix && <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 font-mono text-sm text-faint">{suffix}</span>}
      </div>
      {error && (
        <span id={`${id}-error`} role="alert" className="text-xs text-bad">
          {error}
        </span>
      )}
    </div>
  );
}

export default function SettingsPage() {
  const { settings, reload } = useSettings();
  const { features } = useFeatures();
  const windowsRes = useResource<MaintenanceWindow[]>("/maintenance-windows");
  const [general, setGeneral] = useState<General>({ timezone: settings.timezone, time_format: settings.time_format });
  const [drafts, setDrafts] = useState<Record<number, MaintenanceWindow>>({});
  const [busy, setBusy] = useState(false);
  const [net, setNet] = useState<NetDraft>(() => toDraft(settings));
  const [netError, setNetError] = useState<{ field: NetworkField; text: string }>();
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string }>();
  const zones = useMemo(() => {
    const list = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
    const all = list.includes(settings.timezone) ? list : [settings.timezone, ...list];
    const now = new Date();
    return all.map((zone) => ({ zone, label: zoneLabel(zone, now) }));
  }, [settings.timezone]);

  useEffect(() => setGeneral({ timezone: settings.timezone, time_format: settings.time_format }), [settings.timezone, settings.time_format]);
  useEffect(() => setNet(toDraft(settings)), [settings]);

  const windows = (windowsRes.data ?? []).map((w) => drafts[w.id] ?? w);
  const dirtyWindows = windows.filter((w) => {
    const original = windowsRes.data?.find((o) => o.id === w.id);
    return original && JSON.stringify(original) !== JSON.stringify(w);
  });
  const generalDirty = general.timezone !== settings.timezone || general.time_format !== settings.time_format;
  const patch = networkPatch(net, settings);
  const networkDirty = Object.keys(patch).length > 0;
  const dirty = generalDirty || networkDirty || dirtyWindows.length > 0;

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  async function save() {
    setBusy(true);
    try {
      setNetError(undefined);
      if (generalDirty || networkDirty) {
        await api.put("/settings", { ...(generalDirty ? general : {}), ...(networkDirty ? { network: patch } : {}) });
      }
      for (const w of dirtyWindows) {
        const { id, ...body } = w;
        await api.patch(`/maintenance-windows/${id}`, body);
      }
      setDrafts({});
      await Promise.all([reload(), windowsRes.reload()]);
      setNotice({ tone: "success", text: "Settings saved." });
    } catch (err) {
      const field = err instanceof ApiError && err.status === 422 ? errorField(err.message) : null;
      if (field) {
        setNetError({ field, text: err instanceof Error ? err.message.replace(/^[a-z_]+:\s*/, "") : "" });
        setNotice({ tone: "error", text: "Network settings not saved — check the highlighted field." });
      } else {
        setNotice({ tone: "error", text: errorText(err) });
      }
    } finally {
      setBusy(false);
    }
  }

  async function addWindow() {
    try {
      await api.post("/maintenance-windows", { name: "New window", start_time: "03:00", duration_min: 15, days: 127 });
      await windowsRes.reload();
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err) });
    }
  }

  async function removeWindow(w: MaintenanceWindow) {
    if (!window.confirm(`Delete ${w.name}?`)) return;
    try {
      await api.del(`/maintenance-windows/${w.id}`);
      setDrafts(({ [w.id]: _removed, ...rest }) => rest);
      await windowsRes.reload();
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err) });
    }
  }

  function changeNet(field: NetworkField, value: string) {
    setNet((d) => ({ ...d, [field]: value }));
    if (netError?.field === field) setNetError(undefined);
  }

  const applying = settings.sync_mode === "apply";
  const q = settings.network;

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="general · maintenance · network · access control"
        actions={
          <Button variant="primary" disabled={!dirty || busy} onClick={() => void save()}>
            {dirty ? "Save" : "Saved"}
          </Button>
        }
      />
      {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
      <div className="grid gap-5 xl:grid-cols-2">
        <div className="min-w-0">
          <SectionCard title="General">
            <Field label="Timezone" hint="Used for schedules, quiet hours, maintenance windows and every timestamp">
              <select className={inputClass} value={general.timezone} onChange={(e) => setGeneral((g) => ({ ...g, timezone: e.target.value }))}>
                {zones.map(({ zone, label }) => (
                  <option key={zone} value={zone}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Time format">
              <select
                className={inputClass}
                value={general.time_format}
                onChange={(e) => setGeneral((g) => ({ ...g, time_format: e.target.value as General["time_format"] }))}
              >
                <option value="24h">24-hour</option>
                <option value="12h">12-hour</option>
              </select>
            </Field>
            <div className="flex flex-col gap-2">
              <span className="text-[13px] font-medium text-text2">Theme</span>
              <div>
                <ThemeToggle />
              </div>
              <span className="text-xs text-faint">Applies right away on this browser.</span>
            </div>
          </SectionCard>
        </div>
        <div className="min-w-0">
          <SectionCard title="Network">
            <div className="grid gap-3.5 sm:grid-cols-2">
              {NET_LAYOUT.map(({ field, label, type, suffix, wide }) => (
                <div key={field} className={wide ? "sm:col-span-2" : undefined}>
                  <NetInput
                    field={field}
                    label={label}
                    type={type}
                    suffix={suffix}
                    draft={net}
                    onChange={changeNet}
                    error={netError?.field === field ? netError.text : undefined}
                  />
                </div>
              ))}
            </div>
            <span className="mt-auto text-xs text-faint">
              Changing interface, subnet or sweep interval restarts the scanner (a few seconds). The Pi-hole password stays in the server configuration.
            </span>
          </SectionCard>
        </div>
        <div className="min-w-0">
          <SectionCard
            title="Maintenance windows"
            action={
              <Button className="h-9" onClick={() => void addWindow()}>
                <Plus className="size-4" aria-hidden />
                Add
              </Button>
            }
          >
            {windows.length === 0 && <p className="text-sm text-muted">No windows. Add one for the nightly router reboot.</p>}
            {windows.map((w) => (
              <WindowCard
                key={w.id}
                window={w}
                timezone={settings.timezone}
                onChange={(next) => setDrafts((d) => ({ ...d, [w.id]: next }))}
                onDelete={() => void removeWindow(w)}
              />
            ))}
          </SectionCard>
        </div>
        <div className="min-w-0">
          <SectionCard title="Access control">
            <div className="flex flex-col">
              <StatusRow
                title="Quarantine unknown devices"
                detail={
                  applying
                    ? `Pool .${q.quarantine_start.split(".")[3]}–.${q.quarantine_end.split(".")[3]} · no gateway`
                    : "dry-run — enforced after the Pi-hole DHCP cutover"
                }
                on={applying}
              />
              <StatusRow title="ARP isolation" detail="Planned · also cuts off devices that set a manual static IP" on={false} />
              <StatusRow
                title="Pi-hole sync"
                detail={applying ? "apply — Janus writes reservations to Pi-hole" : "dry-run — Janus only compares with Pi-hole"}
                on={applying}
              />
              <CutoverReadiness />
            </div>
          </SectionCard>
        </div>
        {EXTRA_SECTIONS.filter((s) => !s.requires || (features && s.requires(features))).map(({ id, title, Component }) => (
          <div key={id} className="min-w-0">
            <SectionCard title={title}>
              <Component />
            </SectionCard>
          </div>
        ))}
      </div>
    </>
  );
}

function StatusRow({ title, detail, on }: { title: string; detail: string; on: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-row py-3 last:border-0">
      <span className="flex flex-col gap-0.5">
        <span className="text-[15px] font-semibold">{title}</span>
        <span className="text-[13px] text-muted">{detail}</span>
      </span>
      <span
        className={clsx(
          "rounded-full border px-2.5 py-0.5 font-mono text-xs",
          on ? "border-ok text-ok" : "border-line2 text-faint",
        )}
      >
        {on ? "on" : "off"}
      </span>
    </div>
  );
}

function WindowCard({
  window: w,
  timezone,
  onChange,
  onDelete,
}: {
  window: MaintenanceWindow;
  timezone: string;
  onChange: (next: MaintenanceWindow) => void;
  onDelete: () => void;
}) {
  const set = <K extends keyof MaintenanceWindow>(key: K, value: MaintenanceWindow[K]) => onChange({ ...w, [key]: value });
  const preset = REPEATS.find((r) => r.value === w.days);
  const [custom, setCustom] = useState(!preset);
  const durations = DURATIONS.includes(w.duration_min) ? DURATIONS : [...DURATIONS, w.duration_min].sort((a, b) => a - b);

  return (
    <div className="flex flex-col gap-3.5 rounded-[10px] border border-line p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <input
            aria-label="Window name"
            className="w-full bg-transparent text-[15px] font-semibold outline-none focus:underline"
            value={w.name}
            maxLength={64}
            onChange={(e) => set("name", e.target.value)}
          />
          <span className="font-mono text-xs text-faint">
            {describeDays(w.days).toLowerCase()} · next: {w.enabled ? nextRun(w.days, w.start_time, timezone) : "disabled"}
          </span>
        </span>
        <Checkbox aria-label="Window enabled" checked={w.enabled} onChange={(e) => set("enabled", e.target.checked)} />
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Start">
          <input type="time" className={`${inputClass} font-mono`} value={w.start_time} onChange={(e) => e.target.value && set("start_time", e.target.value)} />
        </Field>
        <Field label="Duration">
          <select className={inputClass} value={w.duration_min} onChange={(e) => set("duration_min", Number(e.target.value))}>
            {durations.map((minutes) => (
              <option key={minutes} value={minutes}>
                {minutes} min
              </option>
            ))}
          </select>
        </Field>
        <Field label="Repeat">
          <select
            className={inputClass}
            value={custom ? "custom" : String(w.days)}
            onChange={(e) => {
              if (e.target.value === "custom") {
                setCustom(true);
              } else {
                setCustom(false);
                set("days", Number(e.target.value));
              }
            }}
          >
            {REPEATS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
            <option value="custom">Custom</option>
          </select>
        </Field>
      </div>
      {custom && (
        <div role="group" aria-label="Days" className="flex flex-wrap gap-1.5">
          {DAY_NAMES.map((day, index) => (
            <button
              key={day}
              type="button"
              aria-pressed={hasDay(w.days, index)}
              onClick={() => set("days", toggleDay(w.days, index) || w.days)}
              className={clsx(
                "h-9 w-12 rounded-md border text-xs font-medium",
                hasDay(w.days, index) ? "border-accent bg-accent-soft text-text" : "border-line2 text-muted",
              )}
            >
              {day}
            </button>
          ))}
        </div>
      )}
      <div className="flex flex-col">
        <Checkbox label="Mute offline and infrastructure alerts" checked={w.mute_alerts} onChange={(e) => set("mute_alerts", e.target.checked)} />
        <Checkbox
          label="Pause ARP isolation while the gateway reboots"
          checked={w.pause_isolation}
          onChange={(e) => set("pause_isolation", e.target.checked)}
        />
      </div>
      <div className="flex justify-end">
        <Button variant="danger" className="h-9" onClick={onDelete}>
          Delete window
        </Button>
      </div>
    </div>
  );
}
