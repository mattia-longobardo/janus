"use client";

import clsx from "clsx";
import { useEffect, useState, type FormEvent } from "react";

import { GuestExpiry } from "@/components/guest-expiry";
import { Button, inputClass } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { useFeatures } from "@/lib/features";
import { newGuestExpiry } from "@/lib/guests";
import { lanOnlyAllowed } from "@/lib/provider-status";
import type { Access, Approval, Device, ExpiryInput, Group, Guest, GuestRules } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

type Choice = Extract<Access, "authorized" | "lan_only" | "blocked">;

const CHOICES: { value: Choice; label: string; hint: string }[] = [
  { value: "authorized", label: "Full network", hint: "Static DHCP reservation, normal DNS and gateway" },
  { value: "lan_only", label: "LAN only", hint: "No gateway: reaches home devices, never the internet" },
  { value: "blocked", label: "Block", hint: "No valid lease; every attempt is logged" },
];

function octet(ip: string): string {
  return `.${ip.split(".")[3]}`;
}

export function ApproveForm({
  device,
  groups,
  onApproved,
  onBlocked,
  onGuest,
}: {
  device: Device;
  groups: Group[];
  onApproved: (result: Approval) => void;
  onBlocked?: (result: Approval) => void;
  onGuest?: (guest: Guest) => void;
}) {
  const [name, setName] = useState(device.dhcp_hostname ?? device.name);
  const [groupId, setGroupId] = useState<number | "">("");
  const [ip, setIp] = useState("");
  const [access, setAccess] = useState<Choice | null>(null);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const { features } = useFeatures();
  const [asGuest, setAsGuest] = useState(false);
  const [expiry, setExpiry] = useState<ExpiryInput>({});
  const rules = useResource<GuestRules>(asGuest ? "/guests/settings" : null).data;
  const lanOnly = lanOnlyAllowed(features);
  const choices = CHOICES.filter((c) => c.value !== "lan_only" || lanOnly);
  const group = groups.find((g) => g.id === groupId);
  const fallback: Choice = group?.default_access === "lan_only" && lanOnly ? "lan_only" : "authorized";
  const choice: Choice = access && choices.some((c) => c.value === access) ? access : fallback;

  async function nextFree(id: number) {
    try {
      const result = await api.get<{ ip: string | null }>(`/groups/${id}/next-free-ip`);
      setIp(result.ip ?? "");
      if (!result.ip) setError("No free address left in this group's range.");
    } catch (err) {
      setError(errorText(err));
    }
  }

  useEffect(() => {
    if (groupId === "") return;
    setError(undefined);
    void nextFree(groupId);
  }, [groupId]);

  async function block() {
    setBusy(true);
    setError(undefined);
    try {
      const result = await api.post<Approval>(`/devices/${device.id}/block`);
      (onBlocked ?? onApproved)(result);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  // The panel always starts from the default: a choice made before Cancel must not be sent later.
  function openGuest(open: boolean) {
    setExpiry({});
    setAsGuest(open);
  }

  async function admitGuest() {
    if (!name.trim()) return setError("Enter a name for the guest.");
    setBusy(true);
    setError(undefined);
    try {
      const guest = await api.post<Guest>(`/devices/${device.id}/guest`, { name: name.trim(), ...newGuestExpiry(expiry) });
      onGuest?.(guest);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (choice === "blocked") return block();
    if (groupId === "") return;
    setBusy(true);
    setError(undefined);
    try {
      const body: Record<string, unknown> = { name: name.trim(), group_id: groupId, access: choice };
      if (ip.trim()) body.static_ip = ip.trim();
      onApproved(await api.post<Approval>(`/devices/${device.id}/approve`, body));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-5 rounded-[14px] border border-line bg-card p-6">
      <h2 className="font-display text-[19px] font-bold">Approve and register</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-2">
          <span className="text-[13px] font-medium text-text2">Name</span>
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required maxLength={64} />
        </label>
        <label className="flex flex-col gap-2">
          <span className="text-[13px] font-medium text-text2">Group</span>
          <select className={inputClass} value={groupId} onChange={(e) => setGroupId(Number(e.target.value))} required={choice !== "blocked"}>
            <option value="" disabled>
              Choose a group…
            </option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor={`ip-${device.id}`} className="text-[13px] font-medium text-text2">
          Static IP
        </label>
        <div className="flex gap-2">
          <input
            id={`ip-${device.id}`}
            className={`${inputClass} font-mono`}
            value={ip}
            onChange={(e) => setIp(e.target.value)}
            inputMode="decimal"
            placeholder={group ? "next free address" : "choose a group first"}
          />
          <Button className="shrink-0 whitespace-nowrap" disabled={groupId === ""} onClick={() => groupId !== "" && void nextFree(groupId)}>
            Next free
          </Button>
        </div>
        <span className="text-xs text-faint">
          {group
            ? `${group.name} range ${octet(group.range_start)}–${octet(group.range_end)} · ${group.device_count} device${group.device_count === 1 ? "" : "s"} in the group`
            : "The address comes from the group's range."}
        </span>
      </div>
      <fieldset className="flex flex-col gap-2.5">
        <legend className="mb-2.5 text-[13px] font-medium text-text2">Access</legend>
        {choices.map((option) => (
          <label
            key={option.value}
            className={clsx(
              "flex cursor-pointer items-start gap-3 rounded-[10px] border p-[13px]",
              choice === option.value ? "border-accent bg-accent-soft" : "border-line2",
            )}
          >
            <input
              type="radio"
              name={`access-${device.id}`}
              className="mt-[3px] size-[18px] accent-[var(--accent)]"
              checked={choice === option.value}
              onChange={() => setAccess(option.value)}
              aria-label={option.label}
            />
            <span className="flex flex-col gap-[3px]">
              <span className="text-[15px] font-semibold">{option.label}</span>
              <span className="text-[13px] text-muted">{option.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {asGuest && (
        <div className="flex flex-col gap-3 rounded-[10px] border border-accent bg-accent-soft p-[13px]">
          <span className="flex flex-col gap-[3px]">
            <span className="text-[15px] font-semibold">Guest</span>
            <span className="text-[13px] text-muted">Internet access from the guest pool, no fixed IP. Removed when it expires.</span>
          </span>
          <GuestExpiry rules={rules} onChange={setExpiry} />
          <div className="flex flex-wrap justify-end gap-3">
            <Button variant="ghost" disabled={busy} onClick={() => openGuest(false)}>
              Cancel
            </Button>
            <Button variant="primary" disabled={busy} onClick={() => void admitGuest()}>
              Add as guest
            </Button>
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="rounded-lg border border-bad px-3 py-2 text-sm text-bad">
          {error}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-3 border-t border-line pt-5">
        <Button variant="danger" disabled={busy} onClick={() => void block()}>
          Reject and block
        </Button>
        {features?.guests?.enabled && !asGuest && (
          <Button disabled={busy} onClick={() => openGuest(true)}>
            Approve as guest
          </Button>
        )}
        <Button type="submit" variant="primary" disabled={busy || (choice !== "blocked" && groupId === "")}>
          {choice === "blocked" ? "Block device" : "Approve and assign IP"}
        </Button>
      </div>
    </form>
  );
}
