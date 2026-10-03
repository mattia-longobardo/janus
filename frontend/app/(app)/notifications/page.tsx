"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { RulesTable } from "@/app/(app)/notifications/rules-table";
import { Button, Card, Checkbox, Field, Notice, PageHeader, inputClass } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { useFeatures } from "@/lib/features";
import { useSettings } from "@/lib/settings-context";
import type { NotifySettings, Rule } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

export default function NotificationsPage() {
  const { settings: app } = useSettings();
  const { features } = useFeatures();
  const channels = (["email", "gotify"] as const).filter((c) => features?.notify?.[c]);
  const res = useResource<{ settings: NotifySettings; rules: Rule[] }>("/notifications");
  const [draft, setDraft] = useState<NotifySettings>();
  const saved = useRef<NotifySettings>(undefined);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string }>();

  useEffect(() => {
    if (res.data) {
      setDraft(res.data.settings);
      saved.current = res.data.settings;
    }
  }, [res.data]);

  if (!features) return <p className="text-muted">Loading…</p>;
  if (channels.length === 0)
    return (
      <Notice tone="error">
        No notification channel is configured. Add Gotify or e-mail in Settings → Integrations.{" "}
        <Link href="/settings#integrations" className="underline">
          Open Settings
        </Link>
      </Notice>
    );
  if (res.error) return <Notice tone="error">{res.error}</Notice>;
  if (!res.data || !draft) return <p className="text-muted">Loading…</p>;

  async function persist(next: NotifySettings) {
    if (JSON.stringify(next) === JSON.stringify(saved.current)) return;
    try {
      const body = { ...next, quiet_start: next.quiet_start || null, quiet_end: next.quiet_end || null };
      await api.put("/notifications/settings", body);
      saved.current = next;
      setNotice({ tone: "success", text: "Saved." });
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err) });
    }
  }

  function toggle<K extends "enabled" | "email_enabled" | "gotify_enabled">(key: K, value: boolean) {
    if (!draft) return;
    const next = { ...draft, [key]: value };
    setDraft(next);
    void persist(next);
  }

  function edit<K extends "email_recipient" | "quiet_start" | "quiet_end">(key: K, value: NotifySettings[K]) {
    setDraft((d) => (d ? { ...d, [key]: value } : d));
  }

  async function changeRule(rule: Rule) {
    try {
      const priority = rule.priority === rule.default_priority ? null : rule.priority;
      await api.put("/notifications/rules", [{ event_type: rule.event_type, email: rule.email, gotify: rule.gotify, priority }]);
      await res.reload();
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err) });
    }
  }

  async function test(channel: "email" | "gotify") {
    try {
      await api.post(`/notifications/test/${channel}`);
      setNotice({ tone: "success", text: `Test queued for ${channel === "email" ? "email" : "Gotify"} — it arrives within a minute.` });
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err) });
    }
  }

  const commit = () => draft && void persist(draft);

  return (
    <>
      <PageHeader
        title="Notifications"
        subtitle="choose channels and what reaches you"
        actions={<Checkbox label="Notifications on" checked={draft.enabled} onChange={(e) => toggle("enabled", e.target.checked)} />}
      />
      {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
      <div className="grid gap-5 lg:grid-cols-2">
        {channels.includes("email") && (
          <Card className="flex flex-col gap-[18px] px-6 py-[22px]">
            <div className="flex items-center justify-between gap-3">
              <span className="flex flex-col gap-1">
                <span className="font-display text-[19px] font-bold">Email</span>
                <span className="text-[13px] text-muted">via Stalwart{app.channels.email_sender ? ` · ${app.channels.email_sender}` : ""}</span>
              </span>
              <Checkbox aria-label="Enable Email" checked={draft.email_enabled} onChange={(e) => toggle("email_enabled", e.target.checked)} />
            </div>
            <Field label="Recipient">
              <input
                className={inputClass}
                type="email"
                value={draft.email_recipient}
                onChange={(e) => edit("email_recipient", e.target.value)}
                onBlur={commit}
                onKeyDown={(e) => e.key === "Enter" && commit()}
              />
            </Field>
            <div className="flex justify-end">
              <Button onClick={() => void test("email")}>Send test</Button>
            </div>
          </Card>
        )}
        {channels.includes("gotify") && (
          <Card className="flex flex-col gap-[18px] px-6 py-[22px]">
            <div className="flex items-center justify-between gap-3">
              <span className="flex flex-col gap-1">
                <span className="font-display text-[19px] font-bold">Gotify</span>
                <span className="text-[13px] text-muted">push to your phone</span>
              </span>
              <Checkbox aria-label="Enable Gotify" checked={draft.gotify_enabled} onChange={(e) => toggle("gotify_enabled", e.target.checked)} />
            </div>
            <Field label="Server" hint="Priority: set per event below (0 silent · 4 normal · 8 high · 10 max).">
              <input className={`${inputClass} font-mono text-text2`} value={app.channels.gotify_url || "not configured"} readOnly />
            </Field>
            <div className="flex justify-end">
              <Button onClick={() => void test("gotify")}>Send test</Button>
            </div>
          </Card>
        )}
      </div>
      <Card className="mt-5 px-6 py-5">
        <RulesTable rules={res.data.rules} channels={[...channels]} onChange={(rule) => void changeRule(rule)} />
      </Card>
      <Card className="mt-5 flex flex-wrap items-center justify-between gap-4 px-6 py-5">
        <span className="flex flex-col gap-1">
          <span className="text-[15px] font-semibold">Quiet hours</span>
          <span className="text-[13px] text-muted">Silence everything except new devices</span>
        </span>
        <span className="flex items-center gap-3">
          <input
            aria-label="Quiet from"
            type="time"
            className={`${inputClass} w-[120px] font-mono`}
            value={draft.quiet_start ?? ""}
            onChange={(e) => edit("quiet_start", e.target.value || null)}
            onBlur={commit}
          />
          <span className="text-faint">→</span>
          <input
            aria-label="Quiet until"
            type="time"
            className={`${inputClass} w-[120px] font-mono`}
            value={draft.quiet_end ?? ""}
            onChange={(e) => edit("quiet_end", e.target.value || null)}
            onBlur={commit}
          />
        </span>
      </Card>
    </>
  );
}
