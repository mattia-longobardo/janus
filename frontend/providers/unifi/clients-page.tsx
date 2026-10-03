"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge, Card, Notice, PageHeader, StatusDot } from "@/components/ui";
import { ipSortKey } from "@/lib/format";
import { useResource } from "@/lib/use-resource";

interface UnifiClient {
  mac: string;
  name: string;
  ip: string | null;
  online: boolean;
  uplink: string | null;
  ssid: string | null;
  signal: number | null;
  uptime_s: number | null;
  device_id: string | null;
}

// lib/filter.ts only knows Devices, so the search is the same case-insensitive substring match over a client's fields.
function filterClients(clients: UnifiClient[], query: string): UnifiClient[] {
  const q = query.trim().toLowerCase();
  return clients
    .filter((c) => !q || [c.name, c.ip, c.mac, c.uplink, c.ssid].filter(Boolean).some((v) => String(v).toLowerCase().includes(q)))
    .sort((a, b) => Number(b.online) - Number(a.online) || ipSortKey(a.ip) - ipSortKey(b.ip) || a.mac.localeCompare(b.mac));
}

function uptime(seconds: number | null): string {
  if (seconds === null) return "";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h`;
  return `${Math.floor(seconds / 86400)} d`;
}

export function ClientsPage() {
  const { data, error, loading } = useResource<UnifiClient[]>("/providers/unifi/clients", { refreshMs: 15_000 });
  const [query, setQuery] = useState("");
  const rows = useMemo(() => filterClients(data ?? [], query), [data, query]);

  return (
    <>
      <PageHeader title="UniFi clients" subtitle="Known and connected clients · refreshed every 15 seconds" />
      {error && <Notice tone="error">{error}</Notice>}
      <Card className="overflow-hidden">
        <div className="px-5 py-4">
          <input
            type="search"
            aria-label="Search clients"
            placeholder="Name, IP, MAC or uplink"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="h-11 w-full rounded-lg border border-line2 bg-bg px-3.5 text-sm text-text outline-none placeholder:text-faint focus:border-accent"
          />
        </div>
        {loading && <p className="px-5 pb-4 text-sm text-muted">Loading…</p>}
        {!loading && data && rows.length === 0 && <p className="px-5 pb-4 text-sm text-muted">No clients.</p>}
        {rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead className="text-xs text-faint">
                <tr>
                  <th className="px-5 py-2 font-medium">Client</th>
                  <th className="px-3 py-2 font-medium">IP</th>
                  <th className="px-3 py-2 font-medium">Uplink</th>
                  <th className="px-3 py-2 font-medium">Wi-Fi</th>
                  <th className="px-3 py-2 font-medium">Uptime</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.mac} className="border-t border-row">
                    <td className="px-5 py-2">
                      <span className="flex items-center gap-2">
                        <StatusDot online={c.online} />
                        {c.device_id ? (
                          <Link href={`/devices/${c.device_id}`} className="font-medium text-accent-text">
                            {c.name || c.mac}
                          </Link>
                        ) : (
                          <>
                            <span className="font-medium">{c.name || c.mac}</span>
                            <Badge>not in Janus</Badge>
                          </>
                        )}
                      </span>
                      <span className="block font-mono text-xs text-faint">{c.mac}</span>
                    </td>
                    <td className="px-3 py-2 font-mono">{c.ip ?? ""}</td>
                    <td className="px-3 py-2">{c.uplink ?? ""}</td>
                    <td className="px-3 py-2">{c.ssid ? `${c.ssid}${c.signal !== null ? ` · ${c.signal} dBm` : ""}` : ""}</td>
                    <td className="px-3 py-2">{uptime(c.uptime_s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
