"use client";

import { useState } from "react";

import { Button, Field, Notice, inputClass } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { useFeatures } from "@/lib/features";
import { useSettings } from "@/lib/settings-context";
import type { ProviderKind, ProviderRole, ProvidersList } from "@/lib/types";
import { useResource } from "@/lib/use-resource";
import { GenericConfigForm } from "@/providers/generic-config-form";
import { PROVIDER_UI } from "@/providers/registry";

const NONE = "none";
const SAME = "same"; // DNS served by the DHCP provider's own connection

const ROWS: { role: ProviderRole; title: string }[] = [
  { role: "dhcp", title: "DHCP & access" },
  { role: "dns", title: "DNS" },
];

type NoticeState = { tone: "success" | "error"; text: string };

function defined(patch: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(patch).filter(([, v]) => v !== undefined));
}

export function ProvidersSection() {
  const { data, error, reload } = useResource<ProvidersList>("/providers");
  const { reload: reloadFeatures } = useFeatures();
  const { reload: reloadSettings } = useSettings();

  if (!data) {
    return <div id="providers">{error ? <Notice tone="error">{error}</Notice> : <p className="text-sm text-muted">Loading…</p>}</div>;
  }

  async function saved() {
    // A new DHCP provider puts Janus back in dry-run, and the menu and pages follow the providers.
    await Promise.all([reload(), reloadFeatures(), reloadSettings()]);
  }

  return (
    <div id="providers" className="flex flex-col gap-6">
      {ROWS.map(({ role, title }) => (
        <RoleRow key={role} role={role} title={title} list={data} onSaved={saved} />
      ))}
    </div>
  );
}

function RoleRow({ role, title, list, onSaved }: { role: ProviderRole; title: string; list: ProvidersList; onSaved: () => Promise<void> }) {
  const view = list.roles[role];
  const dhcp = list.roles.dhcp;
  const dhcpSpec = list.available.find((k) => k.kind === dhcp?.kind);
  const canShare = role === "dns" && Boolean(dhcp && dhcpSpec?.roles.includes("dns"));
  const savedChoice = view ? (role === "dns" && view.shared ? SAME : view.kind) : NONE;

  const [choice, setChoice] = useState<string>();
  const [patch, setPatch] = useState<Record<string, unknown>>({});
  const [saves, setSaves] = useState(0);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<NoticeState>();

  const selected = choice ?? savedChoice;
  const kinds = list.available.filter((k) => k.roles.includes(role));
  const spec: ProviderKind | undefined = kinds.find((k) => k.kind === selected);
  const config = defined(patch);
  const dirty = selected !== savedChoice || Object.keys(config).length > 0;
  // The saved values only describe the provider that is saved; a newly picked one starts from its defaults.
  const base = view && selected === view.kind && savedChoice !== SAME ? view.config : {};
  const Form = (spec && PROVIDER_UI[spec.kind]?.SettingsForm) ?? GenericConfigForm;

  function pick(next: string) {
    setChoice(next);
    setPatch({});
    setNotice(undefined);
  }

  async function save() {
    setBusy(true);
    try {
      const body = selected === SAME ? { same_as: "dhcp" } : selected === NONE ? { kind: null } : { kind: selected, config };
      await api.put(`/providers/${role}`, body);
      setChoice(undefined);
      setPatch({});
      setSaves((n) => n + 1);
      await onSaved();
      setNotice({ tone: "success", text: "Saved" });
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    try {
      const result = await api.post<{ ok: boolean; detail: string }>(`/providers/${role}/test`);
      setNotice({ tone: result.ok ? "success" : "error", text: result.detail });
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3.5">
      <h3 className="text-[15px] font-semibold">{title}</h3>
      {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
      <Field
        label={`${title} provider`}
        hint={spec?.description || (view && selected === savedChoice && view.source === "env" ? "Configured from environment variables" : undefined)}
      >
        <select className={inputClass} value={selected} onChange={(e) => pick(e.target.value)}>
          {canShare && <option value={SAME}>Same as DHCP ({dhcp?.label})</option>}
          <option value={NONE}>None</option>
          {kinds.map((k) => (
            <option key={k.kind} value={k.kind}>
              {k.label}
            </option>
          ))}
        </select>
      </Field>
      {role === "dhcp" && selected !== savedChoice && <Notice>Changing the DHCP provider switches Janus back to dry-run.</Notice>}
      {selected === SAME && <p className="text-sm text-muted">Uses the {dhcp?.label} connection set above.</p>}
      {spec && selected !== SAME && (
        <Form
          key={`${spec.kind}-${saves}`}
          schema={spec.schema}
          secretFields={spec.secret_fields}
          value={{ ...base, ...config }}
          onChange={(next) => setPatch((p) => ({ ...p, ...next }))}
        />
      )}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" disabled={!dirty || busy} onClick={() => void save()}>
          Save {title}
        </Button>
        <Button disabled={busy || dirty || !view} title={dirty ? "Save first: the test uses the saved settings" : undefined} onClick={() => void test()}>
          Test connection
        </Button>
      </div>
    </div>
  );
}
