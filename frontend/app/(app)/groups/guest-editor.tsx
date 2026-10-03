"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";

import { HoursRule } from "@/components/hours-rule";
import { ColorPicker, IconPicker } from "@/components/look-picker";
import { errorField } from "@/components/settings-network";
import { Button, Card, Field, inputClass } from "@/components/ui";
import { ApiError, api, errorText } from "@/lib/api";
import { useFeatures } from "@/lib/features";
import { GUEST_COLOR, GUEST_ICON } from "@/lib/group-icons";
import { guestPool, poolUsage } from "@/lib/ipplan";
import { useSettings } from "@/lib/settings-context";
import type { Device, GuestSettings } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

type Rule = { on: boolean; hours: string };
type Draft = { color: string; icon: string; start: string; end: string; auto: Rule; idle: Rule };
type PoolField = "guest_start" | "guest_end";

const HOURS_ERROR = "Enter the hours as a whole number between 1 and 8760.";

function toRule(hours: number | null, fallback: number): Rule {
  return { on: hours !== null, hours: String(hours ?? fallback) };
}

function validHours(hours: string): boolean {
  const n = Number(hours.trim());
  return /^\d+$/.test(hours.trim()) && n >= 1 && n <= 8760;
}

function ruleValue(rule: Rule): number | null {
  return rule.on ? Number(rule.hours) : null;
}

// Guests are edited like a group: their look and rules live in /guests/settings, their pool in the network settings.
export function GuestEditor({
  guests,
  onDone,
  onError,
}: {
  guests: Device[];
  onDone: (text: string) => Promise<void>;
  onError: (text: string) => void;
}) {
  const { settings, reload: reloadSettings } = useSettings();
  const { reload: reloadFeatures } = useFeatures();
  const res = useResource<GuestSettings>("/guests/settings");
  const [saved, setSaved] = useState<Draft>();
  const [draft, setDraft] = useState<Draft>();
  const [busy, setBusy] = useState(false);
  const [poolError, setPoolError] = useState<{ field: PoolField; text: string }>();
  const { guest_start, guest_end } = settings.network;

  const loaded = res.data !== undefined;
  const auto = res.data?.auto_remove_hours ?? null;
  const idle = res.data?.inactive_remove_hours ?? null;
  const color = res.data?.color ?? GUEST_COLOR;
  const icon = res.data?.icon ?? GUEST_ICON;

  // Depends on the values, not the response object: a refetch must not wipe what the user is typing.
  useEffect(() => {
    if (!loaded) return;
    const next: Draft = { color, icon, start: guest_start, end: guest_end, auto: toRule(auto, 24), idle: toRule(idle, 6) };
    setSaved(next);
    setDraft(next);
  }, [loaded, color, icon, auto, idle, guest_start, guest_end]);

  const view = draft ?? { color, icon, start: guest_start, end: guest_end, auto: toRule(null, 24), idle: toRule(null, 6) };
  const set = (patch: Partial<Draft>) => setDraft({ ...view, ...patch });
  const network: Partial<Record<PoolField, string>> = {};
  if (saved && view.start.trim() !== saved.start) network.guest_start = view.start.trim();
  if (saved && view.end.trim() !== saved.end) network.guest_end = view.end.trim();
  const body = {
    auto_remove_hours: ruleValue(view.auto),
    inactive_remove_hours: ruleValue(view.idle),
    color: view.color,
    icon: view.icon,
  };
  const settingsDirty =
    saved !== undefined &&
    (body.auto_remove_hours !== ruleValue(saved.auto) ||
      body.inactive_remove_hours !== ruleValue(saved.idle) ||
      body.color !== saved.color ||
      body.icon !== saved.icon);
  const poolDirty = Object.keys(network).length > 0;

  const pool = guestPool(settings.network);
  const usage = pool ? poolUsage(pool, guests) : null;

  function changePool(field: PoolField, value: string) {
    set(field === "guest_start" ? { start: value } : { end: value });
    if (poolError?.field === field) setPoolError(undefined);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if ([view.auto, view.idle].some((r) => r.on && !validHours(r.hours))) {
      onError(HOURS_ERROR);
      return;
    }
    setBusy(true);
    setPoolError(undefined);
    let poolSaved = false;
    try {
      // The pool goes first: if it is refused, nothing else changes.
      if (poolDirty) {
        await api.put("/settings", { network });
        poolSaved = true;
      }
      if (settingsDirty) await api.put("/guests/settings", body);
      await Promise.all([reloadSettings(), reloadFeatures(), res.reload()]);
      await onDone("Guests saved.");
    } catch (err) {
      const field = !poolSaved && err instanceof ApiError && err.status === 422 ? errorField(err.message) : null;
      if (field === "guest_start" || field === "guest_end") {
        setPoolError({ field, text: errorText(err).replace(/^[a-z_]+:\s*/, "") });
        onError("Guest pool not saved — check the highlighted field.");
      } else {
        onError(errorText(err));
      }
      // A saved pool changes the settings and the features' pool flag even when the rest was refused.
      if (poolSaved) await Promise.all([reloadSettings(), reloadFeatures()]);
    } finally {
      setBusy(false);
    }
  }

  function poolInput(field: PoolField, value: string) {
    const error = poolError?.field === field;
    return (
      <input
        className={`${inputClass} font-mono ${error ? "border-bad" : ""}`}
        spellCheck={false}
        aria-invalid={error}
        aria-describedby={error ? `${field}-error` : undefined}
        value={value}
        onChange={(e) => changePool(field, e.target.value)}
      />
    );
  }

  function poolHint(field: PoolField, fallback?: string) {
    if (poolError?.field !== field) return fallback;
    return (
      <span id={`${field}-error`} className="text-bad">
        {poolError.text}
      </span>
    );
  }

  const free = usage ? usage.total - usage.used : null;

  return (
    <Card className="p-6">
      <form onSubmit={save} noValidate className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-display text-[22px] font-bold">Guests</h2>
          <span className="font-mono text-xs text-faint">
            {guests.length} guest{guests.length === 1 ? "" : "s"}
            {usage && ` · ${usage.used}/${usage.total} IPs used`}
          </span>
        </div>
        <Field label="Name">
          <input className={`${inputClass} text-muted`} value="Guests" readOnly />
        </Field>
        <ColorPicker value={view.color} onChange={(c) => set({ color: c })} />
        <IconPicker value={view.icon} onChange={(i) => set({ icon: i })} />
        <div className="flex flex-col gap-2">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Range start" hint={poolHint("guest_start")}>
              {poolInput("guest_start", view.start)}
            </Field>
            <Field label="Range end" hint={poolHint("guest_end", free === null ? undefined : `${free} free`)}>
              {poolInput("guest_end", view.end)}
            </Field>
          </div>
          <span className="text-xs text-faint">Guests lease an address from this range, with internet access. Clear both to remove the pool.</span>
        </div>
        <div className="flex flex-col gap-2">
          <div className="grid items-end gap-4 sm:grid-cols-2">
            <HoursRule
              label="Remove guests this many hours after they were added"
              checkboxLabel="Remove guests after a fixed time"
              inputLabel="Hours after added"
              checked={view.auto.on}
              onToggle={(on) => set({ auto: { ...view.auto, on } })}
              value={view.auto.hours}
              onValue={(hours) => set({ auto: { ...view.auto, hours } })}
              max={8760}
            />
            <HoursRule
              label="Remove guests not seen for"
              checkboxLabel="Remove guests not seen for a while"
              inputLabel="Hours not seen"
              checked={view.idle.on}
              onToggle={(on) => set({ idle: { ...view.idle, on } })}
              value={view.idle.hours}
              onValue={(hours) => set({ idle: { ...view.idle, hours } })}
              max={8760}
            />
          </div>
          <span className="text-xs text-faint">A guest&apos;s own expiry replaces both rules.</span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <Link href="/guests" className="text-[13px] text-ok underline hover:text-text">
            Open guests list
          </Link>
          <Button type="submit" variant="primary" disabled={busy || !(poolDirty || settingsDirty)}>
            Save changes
          </Button>
        </div>
      </form>
    </Card>
  );
}
