"use client";

import clsx from "clsx";
import { Bell, BellOff } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { InfoCard, InfoRow, StatCard } from "@/components/device-info";
import { HealthBanner } from "@/components/health";
import { adviceList, riskLevel, sortServices } from "@/components/device-security";
import { EventList } from "@/components/event-list";
import { Button, Card, Field, IconTile, Notice, StatusDot, inputClass } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { deleteDevice } from "@/lib/delete-device";
import { useFeatures } from "@/lib/features";
import { ACCESS_LABELS, formatDateTime, relativeTime } from "@/lib/format";
import { deviceLook, guestLook } from "@/lib/group-icons";
import { hasCapability, lanOnlyAllowed } from "@/lib/provider-status";
import { useSettings } from "@/lib/settings-context";
import type { Access, Approval, Device, DnsActivity, EventItem, Facts, Group, ServiceItem } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

const IDENTITY_FIELDS: [string, string, boolean][] = [
  ["vendor", "Vendor", false],
  ["model", "Model", false],
  ["hostname", "Hostname", true],
  ["type", "Device type", false],
  ["os", "OS", false],
  ["services", "mDNS services", true],
  ["ssdp_server", "UPnP server", true],
];

function sourceLabel(field: string, source: string): string {
  if (source === "oui") return "OUI registry";
  if (source === "dhcp") return field === "hostname" ? "DHCP opt 12" : "DHCP fingerprint";
  if (source === "mdns") return "mDNS";
  if (source === "netbios") return "NetBIOS";
  if (source === "ssdp") return "SSDP";
  return source;
}

const RISK_TONE = { High: "text-bad", Medium: "text-accent-text", Low: "text-text", None: "text-ok" } as const;

export default function DevicePage() {
  const { id } = useParams<{ id: string }>();
  const [fromMap, setFromMap] = useState(false);
  useEffect(() => setFromMap(new URLSearchParams(window.location.search).get("from") === "map"), []);
  const { settings } = useSettings();
  const { features } = useFeatures();
  const dnsLog = hasCapability(features, "dns", "dns_query_log");
  const dnsLabel = features?.providers?.dns?.label ?? "DNS";
  const deviceRes = useResource<Device>(`/devices/${id}`, { refreshMs: 15_000 });
  const groupsRes = useResource<Group[]>("/groups");
  const factsRes = useResource<Facts>(`/devices/${id}/facts`);
  const servicesRes = useResource<ServiceItem[]>(`/devices/${id}/services`, { refreshMs: 15_000 });
  const device = deviceRes.data;
  const dnsDayRes = useResource<DnsActivity>(dnsLog && device?.last_ip ? `/devices/${id}/dns?hours=24` : null);
  const eventsRes = useResource<EventItem[]>(device?.mac ? `/events?mac=${encodeURIComponent(device.mac)}&limit=20` : null);
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string }>();
  const groups = groupsRes.data ?? [];

  if (deviceRes.error) return <Notice tone="error">{deviceRes.error}</Notice>;
  if (!device) return <p className="text-muted">Loading…</p>;
  const group = groups.find((g) => g.id === device.group_id);
  const { Icon, color } = deviceLook(device, groups, guestLook(features));
  const services = sortServices(servicesRes.data ?? []);
  const risky = services.filter((s) => s.risk !== "none" && !s.muted);
  const mutedCount = services.filter((s) => s.risk !== "none" && s.muted).length;
  const mismatch = device.issues.some((issue) => issue.kind === "ip_mismatch");

  async function toggleMute(service: ServiceItem) {
    try {
      await api.patch(`/devices/${id}/services/${service.port}/${service.proto}`, { muted: !service.muted });
      setNotice({
        tone: "success",
        text: service.muted
          ? `Alerts for port ${service.port}/${service.proto} are back on.`
          : `Port ${service.port}/${service.proto} muted: it will not raise alerts.`,
      });
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err) });
    }
  }
  const risk = riskLevel(services);
  const summary = factsRes.data?.summary ?? {};
  const when = (iso: string | null) => formatDateTime(iso, settings.timezone, settings.time_format);

  async function scan() {
    try {
      await api.post(`/devices/${id}/scan`);
      setNotice({ tone: "success", text: `Scan queued — results appear here within a few minutes (scans run ${settings.scan_window.start}–${settings.scan_window.end}).` });
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err) });
    }
  }

  async function block() {
    if (!device || !window.confirm(`Block ${device.name}? It will get no network.`)) return;
    try {
      const result = await api.post<Approval>(`/devices/${id}/block`);
      setNotice({ tone: "success", text: `Blocked — ${result.enforcement}` });
      await deviceRes.reload();
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err) });
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <Link href={fromMap ? "/map" : "/devices"} className="self-start text-sm no-underline">
        <span className="text-ok hover:text-text">{fromMap ? "← Network map" : "← All devices"}</span>
      </Link>
      <header className="flex flex-wrap items-end justify-between gap-6">
        <div className="flex min-w-0 items-center gap-4">
          <IconTile Icon={Icon} color={color} size={56} />
          <div className="flex min-w-0 flex-col gap-1.5">
            <h1 className="break-words font-display text-[30px] font-bold tracking-[-0.02em] lg:text-[34px]">{device.name}</h1>
            <div className="flex flex-wrap items-center gap-2.5 text-[13px] text-muted">
              <span className="flex items-center gap-1.5">
                <StatusDot online={device.online} />
                {device.online ? "Online" : `Offline · seen ${relativeTime(device.last_seen)}`}
              </span>
              <span className={clsx("font-mono", mismatch && "text-bad")}>{(mismatch ? device.last_ip : device.static_ip ?? device.last_ip) ?? "no IP"}</span>
              <span className="font-mono">{device.mac ?? "no MAC"}</span>
              <span
                className={clsx(
                  "rounded-full border px-2.5 py-0.5",
                  device.access === "blocked" ? "border-bad text-bad" : device.access === "pending" ? "border-accent-line text-accent-text" : "border-line2",
                )}
              >
                {group?.name ?? "No group"} · {ACCESS_LABELS[device.access]}
              </span>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-3">
          {device.access === "pending" ? (
            <Link
              href={`/pending#${device.id}`}
              className="inline-flex h-11 items-center rounded-lg border border-accent bg-accent px-[18px] text-sm font-semibold text-accent-ink"
            >
              Approve…
            </Link>
          ) : (
            <Button onClick={() => setEditing((v) => !v)}>{editing ? "Close editor" : "Edit"}</Button>
          )}
          <Button onClick={() => void scan()} disabled={!device.last_ip}>
            Scan now
          </Button>
          {device.access !== "blocked" && (
            <Button variant="danger" onClick={() => void block()}>
              Block
            </Button>
          )}
        </div>
      </header>
      <HealthBanner device={device} />
      <hr className="border-line" />
      {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
      {editing && (
        <EditDevice
          device={device}
          groups={groups}
          onSaved={async () => {
            setEditing(false);
            setNotice({ tone: "success", text: "Saved." });
            await deviceRes.reload();
          }}
        />
      )}

      <div className="grid items-stretch gap-5 lg:grid-cols-2">
        <InfoCard
          title="Identity"
          footer="Each value shows where it came from. Passive sources only; active probes only when you press Scan now or on the group schedule."
        >
          {IDENTITY_FIELDS.filter(([field]) => summary[field]).length === 0 ? (
            <p className="py-3 text-sm text-muted">Nothing announced yet. Facts appear as the device talks on the network.</p>
          ) : (
            IDENTITY_FIELDS.filter(([field]) => summary[field]).map(([field, label, mono]) => (
              <InfoRow key={field} label={label} value={summary[field].value} source={sourceLabel(field, summary[field].source)} mono={mono} />
            ))
          )}
        </InfoCard>
        <InfoCard title="Network">
          <InfoRow
            label="Current IP"
            mono
            value={
              <span className={mismatch ? "text-bad" : undefined}>
                {device.last_ip ?? "—"}
                {mismatch ? " (wrong address)" : ""}
              </span>
            }
            source="ARP"
          />
          <InfoRow label="Reserved IP" mono value={device.static_ip ?? "none (dynamic)"} source={features?.providers?.dhcp?.label ?? "Janus"} />
          <InfoRow label="MAC" mono value={`${device.mac ?? "—"}${device.private_mac ? " (private)" : ""}`} source="ARP" />
          {device.dhcp_hostname && <InfoRow label="DHCP name" mono value={device.dhcp_hostname} source="DHCP" />}
          <InfoRow label="Access" value={ACCESS_LABELS[device.access]} source="Janus" />
          <InfoRow label="Group" value={group?.name ?? "—"} source="Janus" />
          <InfoRow label="First seen" value={when(device.first_seen)} source="Janus" />
          <InfoRow label="Last seen" value={device.online ? "now" : when(device.last_seen)} source="Sentinel" />
        </InfoCard>
      </div>

      <div className={clsx("grid grid-cols-2 gap-4", dnsLog ? "lg:grid-cols-4" : "lg:grid-cols-3")}>
        <StatCard label="Risk" value={risk} tone={RISK_TONE[risk]} note={`${risky.length} finding${risky.length === 1 ? "" : "s"}`} />
        <StatCard label="Open ports" value={services.length} note={device.last_scan_at ? `last scan ${when(device.last_scan_at)}` : "not scanned yet"} />
        <StatCard label="Risky services" value={risky.length} tone={risky.length ? "text-bad" : "text-ok"} note={mutedCount ? `${mutedCount} muted · no alerts` : "telnet, FTP, VNC, databases, UPnP…"} />
        {dnsLog && (
          <StatCard
            label="DNS queries 24 h"
            value={dnsDayRes.data ? dnsDayRes.data.total : "—"}
            tone="text-ok"
            note={dnsDayRes.data ? `${dnsDayRes.data.blocked} blocked by ${dnsLabel}` : device.last_ip ? `${dnsLabel} not reachable` : "no IP known"}
          />
        )}
      </div>

      <section className="rounded-[14px] border border-line bg-card px-6 py-5">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="font-display text-[19px] font-bold">Open ports</h2>
          <span className="font-mono text-xs text-muted">
            nmap -sV · {group?.scan_enabled ? `every ${group.scan_interval_hours} h for ${group.name}` : "manual scans only"}
          </span>
        </div>
        {services.length === 0 ? (
          <p className="mt-3 text-sm text-muted">{device.last_scan_at ? "No open ports found." : "Not scanned yet."}</p>
        ) : (
          <div className="mt-2 overflow-x-auto">
            <div className="min-w-[760px]">
              {services.map((s) => (
                <div key={`${s.port}/${s.proto}`} className={clsx("grid grid-cols-[110px_1.2fr_1.6fr_80px_120px] items-center gap-4 border-b border-row py-[11px] text-sm", s.muted && "text-muted")}>
                  <span className="font-mono">
                    {s.port}/{s.proto}
                  </span>
                  <span>
                    {s.service ?? "unknown"}
                    {s.version ? <span className="text-muted"> · {s.version}</span> : null}
                  </span>
                  <span className="text-muted">{s.risk_reason ?? (s.risk === "none" ? "No known risk" : "")}</span>
                  <span
                    className={clsx(
                      "text-xs font-semibold",
                      s.muted ? "text-faint line-through" : s.risk === "high" ? "text-bad" : s.risk === "warning" ? "text-accent-text" : "text-muted",
                    )}
                    title={s.muted ? "Muted: no alerts" : undefined}
                  >
                    {s.risk === "high" ? "High" : s.risk === "warning" ? "Warning" : "Info"}
                  </span>
                  <span className="text-right">
                    <button
                      type="button"
                      onClick={() => void toggleMute(s)}
                      aria-label={`${s.muted ? "Unmute" : "Mute alerts for"} port ${s.port}/${s.proto}`}
                      className={clsx(
                        "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium",
                        s.muted ? "border-accent-line bg-accent-soft text-accent-text" : "border-line2 text-muted hover:text-text",
                      )}
                    >
                      {s.muted ? <BellOff className="size-3.5" aria-hidden /> : <Bell className="size-3.5" aria-hidden />}
                      {s.muted ? "Muted" : "Mute alerts"}
                    </button>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <div className={clsx("grid items-stretch gap-5", dnsLog && "lg:grid-cols-[1.4fr_1fr]")}>
        {dnsLog && <DnsCard device={device} />}
        <section className="rounded-[14px] border border-line bg-card px-6 py-5">
          <h2 className="mb-3 font-display text-[19px] font-bold">What to do</h2>
          <ul className="flex flex-col gap-3">
            {adviceList(device, services, settings.scan_window).map((tip) => (
              <li key={tip} className="grid grid-cols-[14px_1fr] gap-2.5 text-sm text-text2">
                <span className="mt-1.5 size-2 rounded-full bg-accent" aria-hidden />
                {tip}
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="rounded-[14px] border border-line bg-card px-6 py-5">
        <h2 className="mb-2 font-display text-[19px] font-bold">Recent events</h2>
        <EventList events={eventsRes.data ?? []} />
      </section>
    </div>
  );
}

function DnsCard({ device }: { device: Device }) {
  const [hours, setHours] = useState(24);
  const dnsRes = useResource<DnsActivity>(device.last_ip ? `/devices/${device.id}/dns?hours=${hours}` : null);
  const dns = dnsRes.data;
  return (
    <section className="rounded-[14px] border border-line bg-card px-6 py-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <h2 className="font-display text-[19px] font-bold">DNS activity</h2>
          <Link href={`/devices/${device.id}/dns`} className="text-sm no-underline">
            <span className="text-ok hover:text-text">Analyse →</span>
          </Link>
        </div>
        <select aria-label="Period" className={`${inputClass.replace("w-full ", "")} w-40`} value={hours} onChange={(e) => setHours(Number(e.target.value))}>
          <option value={24}>Last 24 h</option>
          <option value={72}>Last 3 days</option>
          <option value={168}>Last 7 days</option>
        </select>
      </div>
      {!device.last_ip && <p className="mt-3 text-sm text-muted">No IP address known yet.</p>}
      {dnsRes.error && <p className="mt-3 text-sm text-bad">{dnsRes.error}</p>}
      {dns && (
        <>
          <p className="mt-3 font-mono text-xs text-faint">
            {dns.total} queries · {dns.blocked} blocked{dns.truncated ? ` · top domains from the latest ${dns.sampled}` : ""}
          </p>
          <ul className="mt-1">
            {dns.domains.slice(0, 15).map((d) => (
              <li key={d.domain} className="flex items-center justify-between gap-3 border-b border-row py-2 last:border-0">
                <span className="truncate font-mono text-[13px]">{d.domain}</span>
                <span className="flex shrink-0 items-center gap-2 font-mono text-xs">
                  {d.blocked && <span className="rounded-full border border-bad px-2 py-0.5 text-[11px] text-bad">blocked</span>}
                  {d.count}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function EditDevice({ device, groups, onSaved }: { device: Device; groups: Group[]; onSaved: () => Promise<void> }) {
  const [name, setName] = useState(device.name);
  const [groupId, setGroupId] = useState<number | "">(device.group_id ?? "");
  const [ip, setIp] = useState(device.static_ip ?? "");
  const [access, setAccess] = useState<Access>(device.access);
  const [error, setError] = useState<string>();
  const router = useRouter();
  const { features } = useFeatures();
  const lanOnly = lanOnlyAllowed(features);

  async function remove() {
    try {
      if (await deleteDevice(device)) router.push("/devices");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function firstFree() {
    if (groupId === "") return;
    try {
      const result = await api.get<{ ip: string | null }>(`/groups/${groupId}/next-free-ip?device_id=${device.id}`);
      if (result.ip) setIp(result.ip);
      else setError("No free address left in this group's range.");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setError(undefined);
    const body: Record<string, unknown> = {};
    if (name !== device.name) body.name = name;
    if (groupId !== "" && groupId !== device.group_id) body.group_id = groupId;
    if ((ip || null) !== device.static_ip) body.static_ip = ip || null;
    if (access !== device.access) body.access = access;
    try {
      await api.patch(`/devices/${device.id}`, body);
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Card className="p-5">
      <form onSubmit={save} className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Field label="Name">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} maxLength={64} required />
        </Field>
        <Field label="Group">
          <select className={inputClass} value={groupId} onChange={(e) => setGroupId(Number(e.target.value))}>
            {groupId === "" && <option value="">No group</option>}
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Static IP">
          <div className="flex gap-2">
            <input className={`${inputClass} font-mono`} value={ip} onChange={(e) => setIp(e.target.value)} />
            <Button className="shrink-0" disabled={groupId === ""} onClick={() => void firstFree()} title="Lowest free address in the group's range">
              First free
            </Button>
          </div>
        </Field>
        <Field label="Access">
          <select className={inputClass} value={access} onChange={(e) => setAccess(e.target.value as Access)}>
            {(["authorized", "lan_only", "blocked"] as Access[]).filter((v) => v !== "lan_only" || lanOnly || device.access === "lan_only").map((value) => (
              <option key={value} value={value}>
                {ACCESS_LABELS[value]}
              </option>
            ))}
          </select>
        </Field>
        {error && (
          <p role="alert" className="text-sm text-bad md:col-span-2 xl:col-span-4">
            {error}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-3 border-t border-line pt-4 md:col-span-2 xl:col-span-4">
          <Button variant="danger" onClick={() => void remove()}>
            Delete device
          </Button>
          <Button type="submit" variant="primary">
            Save changes
          </Button>
        </div>
      </form>
    </Card>
  );
}
