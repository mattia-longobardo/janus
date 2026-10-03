"use client";

import { useEffect, useState } from "react";

import { Button, Checkbox, Field, Notice, inputClass } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { useFeatures } from "@/lib/features";
import { useSettings } from "@/lib/settings-context";
import type { GuestRules } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

type Rule = { on: boolean; hours: string };
type Draft = { start: string; end: string; auto: Rule; idle: Rule };

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

function RuleRow({
  label,
  hoursLabel,
  before,
  after,
  rule,
  onChange,
}: {
  label: string;
  hoursLabel: string;
  before: string;
  after: string;
  rule: Rule;
  onChange: (rule: Rule) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2.5 text-sm text-text2">
      <Checkbox aria-label={label} checked={rule.on} onChange={(e) => onChange({ ...rule, on: e.target.checked })} />
      <span>{before}</span>
      <input
        aria-label={hoursLabel}
        type="number"
        min={1}
        max={8760}
        disabled={!rule.on}
        className={`${inputClass} h-9 w-[84px] font-mono disabled:opacity-50`}
        value={rule.hours}
        onChange={(e) => onChange({ ...rule, hours: e.target.value })}
      />
      <span>{after}</span>
    </div>
  );
}

export function GuestsSection() {
  const { settings, reload: reloadSettings } = useSettings();
  const { reload: reloadFeatures } = useFeatures();
  const rulesRes = useResource<GuestRules>("/guests/settings");
  const [saved, setSaved] = useState<Draft>();
  const [draft, setDraft] = useState<Draft>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string }>();
  const { guest_start, guest_end } = settings.network;

  const auto = rulesRes.data?.auto_remove_hours;
  const idle = rulesRes.data?.inactive_remove_hours;
  const loaded = rulesRes.data !== undefined;

  // Depends on the values, not the response object: the periodic refetch must not wipe what the user is typing.
  useEffect(() => {
    if (!loaded) return;
    const next: Draft = { start: guest_start, end: guest_end, auto: toRule(auto ?? null, 24), idle: toRule(idle ?? null, 6) };
    setSaved(next);
    setDraft(next);
  }, [loaded, auto, idle, guest_start, guest_end]);

  const view = draft ?? { start: guest_start, end: guest_end, auto: toRule(null, 24), idle: toRule(null, 6) };
  const set = (patch: Partial<Draft>) => setDraft({ ...view, ...patch });
  const network: Record<string, string> = {};
  if (saved && view.start.trim() !== saved.start) network.guest_start = view.start.trim();
  if (saved && view.end.trim() !== saved.end) network.guest_end = view.end.trim();
  const rules = { auto_remove_hours: ruleValue(view.auto), inactive_remove_hours: ruleValue(view.idle) };
  const rulesDirty =
    saved !== undefined &&
    (rules.auto_remove_hours !== ruleValue(saved.auto) || rules.inactive_remove_hours !== ruleValue(saved.idle));
  const poolDirty = Object.keys(network).length > 0;

  async function save() {
    if ([view.auto, view.idle].some((r) => r.on && !validHours(r.hours))) {
      setMessage({ tone: "error", text: "Enter the hours as a whole number between 1 and 8760." });
      return;
    }
    setBusy(true);
    setMessage(undefined);
    let poolSaved = false;
    try {
      // The pool goes first: if it is refused, nothing else changes.
      if (poolDirty) {
        await api.put("/settings", { network });
        poolSaved = true;
      }
      if (rulesDirty) await api.put("/guests/settings", rules);
      await Promise.all([reloadSettings(), reloadFeatures(), rulesRes.reload()]);
      setMessage({ tone: "success", text: "Guest settings saved." });
    } catch (err) {
      setMessage({ tone: "error", text: errorText(err) });
      // A saved pool changes the settings and the features' pool flag even when the rules were refused.
      if (poolSaved) await Promise.all([reloadSettings(), reloadFeatures()]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {message && <Notice tone={message.tone}>{message.text}</Notice>}
      {rulesRes.error && <Notice tone="error">{rulesRes.error}</Notice>}
      <div className="grid gap-3.5 sm:grid-cols-2">
        <Field label="Guest pool from">
          <input className={`${inputClass} font-mono`} spellCheck={false} value={view.start} onChange={(e) => set({ start: e.target.value })} />
        </Field>
        <Field label="Guest pool to">
          <input className={`${inputClass} font-mono`} spellCheck={false} value={view.end} onChange={(e) => set({ end: e.target.value })} />
        </Field>
      </div>
      <span className="-mt-2 text-xs text-faint">Guests lease an address from this range, with internet access. Clear both to remove the pool.</span>
      <div className="flex flex-col gap-2">
        <RuleRow
          label="Remove guests after a fixed time"
          hoursLabel="Hours after added"
          before="Remove guests"
          after="hours after they were added"
          rule={view.auto}
          onChange={(auto) => set({ auto })}
        />
        <RuleRow
          label="Remove guests not seen for a while"
          hoursLabel="Hours not seen"
          before="Remove guests not seen for"
          after="hours"
          rule={view.idle}
          onChange={(idle) => set({ idle })}
        />
        <span className="text-xs text-faint">A guest&apos;s own expiry replaces both rules.</span>
      </div>
      <div className="flex justify-end">
        <Button variant="primary" aria-label="Save guest settings" disabled={busy || !(poolDirty || rulesDirty)} onClick={() => void save()}>
          Save
        </Button>
      </div>
    </div>
  );
}
