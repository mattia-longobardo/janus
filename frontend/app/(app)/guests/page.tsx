"use client";

import { Plus } from "lucide-react";
import { Fragment, useState, type FormEvent } from "react";

import { GuestExpiry } from "@/components/guest-expiry";
import { Badge, Button, Card, Field, Notice, PageHeader, StatusDot, inputClass } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { useFeatures } from "@/lib/features";
import { formatDateTime } from "@/lib/format";
import { describeExpiry, newGuestExpiry, sortGuests } from "@/lib/guests";
import { hasCapability } from "@/lib/provider-status";
import { useSettings } from "@/lib/settings-context";
import type { ExpiryInput, Guest, GuestRules } from "@/lib/types";
import { useNow } from "@/lib/use-now";
import { useResource } from "@/lib/use-resource";

type Message = { tone: "success" | "error"; text: string };

export default function GuestsPage() {
  const { settings } = useSettings();
  const { features } = useFeatures();
  const guestsRes = useResource<Guest[]>("/guests", { refreshMs: 30_000 });
  const rulesRes = useResource<GuestRules>("/guests/settings");
  const now = useNow(30_000);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [notice, setNotice] = useState<Message>();
  const guests = sortGuests(guestsRes.data ?? []);
  const online = guests.filter((g) => g.online).length;
  // Without a pool a provider with a quarantine range hands guests a quarantine address, which has no gateway.
  const poolMissing = features?.guests?.pool === false && hasCapability(features, "dhcp", "quarantine");

  async function remove(g: Guest) {
    if (!window.confirm(`Remove ${g.name}? If it is still connected it will show up again in Pending.`)) return;
    try {
      await api.del(`/guests/${g.id}`);
      setNotice({ tone: "success", text: `${g.name} removed.` });
      await guestsRes.reload();
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err) });
    }
  }

  async function done(text: string) {
    setNotice({ tone: "success", text });
    setAdding(false);
    setEditing(null);
    await guestsRes.reload();
  }

  return (
    <>
      <PageHeader
        title="Guests"
        subtitle={`${guests.length} guest${guests.length === 1 ? "" : "s"} · ${online} online · no fixed IP, removed when they expire`}
        actions={
          <Button variant="primary" onClick={() => setAdding(true)}>
            <Plus className="size-4" aria-hidden />
            Add guest
          </Button>
        }
      />
      {poolMissing && <Notice>Set a guest pool in Settings → Guests, otherwise guests get quarantine addresses without internet.</Notice>}
      {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
      {guestsRes.error && <Notice tone="error">{guestsRes.error}</Notice>}
      {adding && (
        <AddGuest rules={rulesRes.data} onDone={done} onCancel={() => setAdding(false)} onError={(text) => setNotice({ tone: "error", text })} />
      )}
      <Card className="overflow-hidden">
        {!guestsRes.loading && guests.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted">No guests. Add one by MAC, or approve a pending device as a guest.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-sm [&_td]:whitespace-nowrap">
              <thead>
                <tr className="border-b border-line text-left text-xs uppercase tracking-[.06em] text-faint">
                  {["Name", "MAC", "Last IP", "Online", "Guest since", "Expires"].map((label) => (
                    <th key={label} scope="col" className="px-4 py-3 font-medium">
                      {label}
                    </th>
                  ))}
                  <th scope="col" className="px-4 py-3">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {guests.map((g) => (
                  <Fragment key={g.id}>
                    <tr className="border-b border-row">
                      <td className="px-4 py-2.5 font-medium">{g.name}</td>
                      <td className="px-4 py-2.5 font-mono text-[13px] text-muted">{g.mac ?? "—"}</td>
                      <td className="px-4 py-2.5 font-mono text-[13px]">{g.last_ip ?? "—"}</td>
                      <td className="px-4 py-2.5">
                        <span className="flex items-center gap-2 text-text2">
                          <StatusDot online={g.online} />
                          {g.online ? "Online" : "Offline"}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 font-mono text-xs text-faint">{formatDateTime(g.guest_since, settings.timezone, settings.time_format)}</td>
                      <td className="px-4 py-2.5">
                        <span
                          className="flex items-center gap-2"
                          title={g.effective_expires_at ? formatDateTime(g.effective_expires_at, settings.timezone, settings.time_format) : undefined}
                        >
                          {describeExpiry(g, new Date(now), settings.time_format, settings.timezone)}
                          {g.expiry_source === "global" && <Badge>default</Badge>}
                          {g.expiry_source === "inactive" && <Badge>if idle</Badge>}
                        </span>
                      </td>
                      <td className="px-4 py-1.5 text-right">
                        <span className="inline-flex gap-2">
                          <Button
                            className="h-9"
                            aria-label={`Change expiry for ${g.name}`}
                            aria-expanded={editing === g.id}
                            onClick={() => setEditing(editing === g.id ? null : g.id)}
                          >
                            Change expiry
                          </Button>
                          <Button variant="danger" className="h-9" aria-label={`Remove ${g.name}`} onClick={() => void remove(g)}>
                            Remove
                          </Button>
                        </span>
                      </td>
                    </tr>
                    {editing === g.id && (
                      <tr className="border-b border-row bg-card2">
                        <td colSpan={7} className="px-4 py-3">
                          <ChangeExpiry
                            guest={g}
                            rules={rulesRes.data}
                            onDone={done}
                            onCancel={() => setEditing(null)}
                            onError={(text) => setNotice({ tone: "error", text })}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {guests.some((g) => g.expiry_source === "inactive") && (
        <p className="mt-3 text-xs text-faint">&ldquo;if idle&rdquo;: the date moves forward while the guest stays active.</p>
      )}
    </>
  );
}

function AddGuest({
  rules,
  onDone,
  onCancel,
  onError,
}: {
  rules?: GuestRules;
  onDone: (text: string) => Promise<void>;
  onCancel: () => void;
  onError: (text: string) => void;
}) {
  const [mac, setMac] = useState("");
  const [name, setName] = useState("");
  const [expiry, setExpiry] = useState<ExpiryInput>({});
  const [busy, setBusy] = useState(false);

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.post("/guests", { mac: mac.trim(), name: name.trim(), ...newGuestExpiry(expiry) });
      await onDone(`${name.trim()} added as a guest.`);
    } catch (err) {
      onError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-5 p-6">
      <form onSubmit={save} className="flex flex-col gap-4">
        <h2 className="font-display text-[19px] font-bold">Add guest</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="MAC address">
            <input className={`${inputClass} font-mono`} spellCheck={false} value={mac} onChange={(e) => setMac(e.target.value)} required />
          </Field>
          <Field label="Name">
            <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required maxLength={64} />
          </Field>
        </div>
        <div className="flex flex-col gap-2">
          <span className="text-[13px] font-medium text-text2">Expires</span>
          <GuestExpiry rules={rules} onChange={setExpiry} />
        </div>
        <div className="flex flex-wrap justify-end gap-3 border-t border-line pt-4">
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" aria-label="Save guest" disabled={busy}>
            Add guest
          </Button>
        </div>
      </form>
    </Card>
  );
}

function ChangeExpiry({
  guest,
  rules,
  onDone,
  onCancel,
  onError,
}: {
  guest: Guest;
  rules?: GuestRules;
  onDone: (text: string) => Promise<void>;
  onCancel: () => void;
  onError: (text: string) => void;
}) {
  const [expiry, setExpiry] = useState<ExpiryInput>({});
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      await api.patch(`/guests/${guest.id}`, expiry);
      await onDone(`Expiry updated for ${guest.name}.`);
    } catch (err) {
      onError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <GuestExpiry value={guest} rules={rules} onChange={setExpiry} />
      <span className="flex gap-2">
        <Button variant="ghost" className="h-9" onClick={onCancel}>
          Cancel
        </Button>
        <Button variant="primary" className="h-9" aria-label="Save expiry" disabled={busy || Object.keys(expiry).length === 0} onClick={() => void save()}>
          Save
        </Button>
      </span>
    </div>
  );
}
