"use client";

import { useState } from "react";

import { Button, Field, Notice, SCROLL_TARGET, inputClass } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { useFeatures } from "@/lib/features";
import { SecretInput } from "@/lib/secret-input";
import type { ChannelsView, EmailValues, GotifyValues } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

type Draft = {
  gotify: { url?: string; token?: string };
  email: { host?: string; port?: string; security?: EmailValues["security"]; user?: string; password?: string; sender?: string };
};

const EMPTY: Draft = { gotify: {}, email: {} };

function Heading({ name, ready }: { name: string; ready: boolean }) {
  return <h3 className="text-[15px] font-semibold">{`${name} · ${ready ? "ready" : "not configured"}`}</h3>;
}

// Drop keys the user left untouched (or set back to the stored value), so only real edits are sent.
function changed<V extends object>(draft: Partial<Record<keyof V, string | number | undefined>>, current: V) {
  const out: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(draft)) {
    if (value === undefined) continue;
    if ((current as Record<string, unknown>)[key] === value) continue;
    out[key] = value as string | number;
  }
  return out;
}

export function IntegrationsSection() {
  const { data, error, setData } = useResource<ChannelsView>("/notifications/channels");
  const { reload: reloadFeatures } = useFeatures();
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [saves, setSaves] = useState(0);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string }>();

  if (!data) {
    return (
      <div id="integrations" className={SCROLL_TARGET}>
        {error ? <Notice tone="error">{error}</Notice> : <p className="text-sm text-muted">Loading…</p>}
      </div>
    );
  }

  const g = data.gotify.values;
  const e = data.email.values;
  const setG = (patch: Draft["gotify"]) => setDraft((d) => ({ ...d, gotify: { ...d.gotify, ...patch } }));
  const setE = (patch: Draft["email"]) => setDraft((d) => ({ ...d, email: { ...d.email, ...patch } }));

  const gotify = changed<GotifyValues>(draft.gotify, g);
  // An emptied port counts as untouched rather than 0.
  const { port, ...emailRest } = draft.email;
  const email = changed<EmailValues>({ ...emailRest, port: port?.trim() ? Number(port) : undefined }, e);
  const body = {
    ...(Object.keys(gotify).length ? { gotify } : {}),
    ...(Object.keys(email).length ? { email } : {}),
  };
  const dirty = Object.keys(body).length > 0;

  async function save() {
    setBusy(true);
    try {
      setData(await api.put<ChannelsView>("/notifications/channels", body));
      setDraft(EMPTY);
      setSaves((n) => n + 1);
      await reloadFeatures();
      setNotice({ tone: "success", text: "Saved" });
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div id="integrations" className={`flex flex-col gap-5 ${SCROLL_TARGET}`}>
      {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
      <div className="flex flex-col gap-3.5">
        <Heading name="Gotify" ready={data.gotify.ready} />
        <Field label="Gotify URL">
          <input className={`${inputClass} font-mono`} spellCheck={false} value={draft.gotify.url ?? g.url} onChange={(ev) => setG({ url: ev.target.value })} />
        </Field>
        <SecretInput key={`g-${saves}`} label="Gotify token" isSet={g.token} onChange={(token) => setG({ token })} />
      </div>
      <div className="flex flex-col gap-3.5">
        <Heading name="E-mail" ready={data.email.ready} />
        <div className="grid gap-3.5 sm:grid-cols-2">
          <Field label="SMTP host">
            <input className={`${inputClass} font-mono`} spellCheck={false} value={draft.email.host ?? e.host} onChange={(ev) => setE({ host: ev.target.value })} />
          </Field>
          <Field label="SMTP port">
            <input
              type="number"
              min={1}
              max={65535}
              className={`${inputClass} font-mono`}
              value={draft.email.port ?? String(e.port)}
              onChange={(ev) => setE({ port: ev.target.value })}
            />
          </Field>
          <Field label="Security">
            <select
              className={inputClass}
              value={draft.email.security ?? e.security}
              onChange={(ev) => setE({ security: ev.target.value as EmailValues["security"] })}
            >
              <option value="ssl">SSL/TLS</option>
              <option value="starttls">STARTTLS</option>
              <option value="none">None</option>
            </select>
          </Field>
          <Field label="SMTP user">
            <input className={`${inputClass} font-mono`} spellCheck={false} value={draft.email.user ?? e.user} onChange={(ev) => setE({ user: ev.target.value })} />
          </Field>
          <SecretInput key={`e-${saves}`} label="SMTP password" isSet={e.password} onChange={(password) => setE({ password })} />
          <Field label="Sender address">
            <input className={`${inputClass} font-mono`} spellCheck={false} value={draft.email.sender ?? e.sender} onChange={(ev) => setE({ sender: ev.target.value })} />
          </Field>
        </div>
      </div>
      <div>
        <Button variant="primary" disabled={!dirty || busy} onClick={() => void save()}>
          Save integrations
        </Button>
      </div>
    </div>
  );
}
