"use client";

import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Badge, Notice, Pagination, Segmented } from "@/components/ui";
import { busiest, filterDomains, sortDomains, type DnsAnalysis, type DnsBucket, type DomainSortKey } from "@/lib/dns-types";
import { useFeatures } from "@/lib/features";
import { formatDateTime } from "@/lib/format";
import { hasCapability } from "@/lib/provider-status";
import { useSettings } from "@/lib/settings-context";
import type { Device } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

const PERIODS = [
  { value: "1", label: "1 h" },
  { value: "6", label: "6 h" },
  { value: "24", label: "24 h" },
  { value: "72", label: "3 d" },
  { value: "168", label: "7 d" },
] as const;
type Period = (typeof PERIODS)[number]["value"];

const COLUMNS: { key: DomainSortKey; label: string; className?: string }[] = [
  { key: "domain", label: "Domain" },
  { key: "base", label: "Base domain", className: "hidden md:table-cell" },
  { key: "count", label: "Queries", className: "text-right" },
  { key: "last_seen", label: "Last seen", className: "hidden sm:table-cell" },
];

function Stat({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: string }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-[14px] border border-line bg-card p-5">
      <span className="text-[13px] text-muted">{label}</span>
      <span className={`font-display text-[32px] font-bold leading-none ${tone ?? "text-text"}`}>{value}</span>
      {note && <span className="font-mono text-xs text-faint">{note}</span>}
    </div>
  );
}

function Timeline({ buckets, bucketSeconds, tz, timeFormat }: { buckets: DnsBucket[]; bucketSeconds: number; tz: string; timeFormat: "24h" | "12h" }) {
  const max = Math.max(1, ...buckets.map((b) => b.total));
  const label = (iso: string) => {
    const full = formatDateTime(iso, tz, timeFormat);
    return buckets.length > 30 && bucketSeconds >= 3600 ? full : full.slice(6);
  };
  const ticks = buckets.length > 1 ? [0, Math.floor(buckets.length / 2), buckets.length - 1] : [0];
  return (
    <div className="flex flex-col gap-2">
      <div className="flex h-40 items-end gap-px" role="img" aria-label="Queries over time">
        {buckets.map((b) => (
          <div
            key={b.start}
            title={`${formatDateTime(b.start, tz, timeFormat)} · ${b.total} queries · ${b.blocked} blocked`}
            className="flex h-full min-w-0 flex-1 flex-col justify-end"
          >
            <div className="flex w-full flex-col justify-end overflow-hidden rounded-t-sm" style={{ height: `${(b.total / max) * 100}%` }}>
              <div className="w-full bg-ok/70" style={{ flexGrow: Math.max(0, b.total - b.blocked) }} />
              <div className="w-full bg-bad" style={{ flexGrow: b.blocked }} />
            </div>
          </div>
        ))}
      </div>
      <div className="flex justify-between font-mono text-[11px] text-faint">
        {ticks.map((i) => (
          <span key={i}>{buckets[i] ? label(buckets[i].start) : ""}</span>
        ))}
      </div>
      <div className="flex gap-4 text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm bg-ok/70" /> allowed
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm bg-bad" /> blocked
        </span>
        <span className="ml-auto font-mono">{bucketSeconds >= 3600 ? "per hour" : "per 10 min"}</span>
      </div>
    </div>
  );
}

function BarList({ rows, tone = "bg-ok/60" }: { rows: { label: string; count: number }[]; tone?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  if (rows.length === 0) return <p className="text-sm text-muted">Nothing in this period.</p>;
  return (
    <ul className="flex flex-col gap-2">
      {rows.map((r) => (
        <li key={r.label} className="flex flex-col gap-1">
          <span className="flex justify-between gap-3 text-[13px]">
            <span className="truncate font-mono">{r.label}</span>
            <span className="shrink-0 font-mono text-muted">{r.count}</span>
          </span>
          <span className="h-1.5 rounded-full bg-row">
            <span className={`block h-full rounded-full ${tone}`} style={{ width: `${(r.count / max) * 100}%` }} />
          </span>
        </li>
      ))}
    </ul>
  );
}

export default function DnsAnalysisPage() {
  const { id } = useParams<{ id: string }>();
  const { settings } = useSettings();
  const [period, setPeriod] = useState<Period>("24");
  const [query, setQuery] = useState("");
  const [onlyBlocked, setOnlyBlocked] = useState(false);
  const [sort, setSort] = useState<{ key: DomainSortKey; dir: "asc" | "desc" }>({ key: "count", dir: "desc" });
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(25);
  const { features } = useFeatures();
  const dnsLog = hasCapability(features, "dns", "dns_query_log");
  const dnsLabel = features?.providers?.dns?.label ?? "DNS";
  const deviceRes = useResource<Device>(`/devices/${id}`);
  const dnsRes = useResource<DnsAnalysis>(dnsLog && deviceRes.data?.last_ip ? `/devices/${id}/dns/analysis?hours=${period}` : null);
  const data = dnsRes.data;
  const device = deviceRes.data;

  const rows = useMemo(
    () => (data ? sortDomains(filterDomains(data.domains, query, onlyBlocked), sort.key, sort.dir) : []),
    [data, query, onlyBlocked, sort],
  );
  const shown = rows.slice(page * pageSize, (page + 1) * pageSize);
  const peak = data ? busiest(data.timeline) : null;
  const tz = settings.timezone;
  const tf = settings.time_format;

  function toggle(key: DomainSortKey) {
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "count" || key === "last_seen" ? "desc" : "asc" }));
    setPage(0);
  }

  return (
    <div className="flex flex-col gap-5">
      <Link href={`/devices/${id}`} className="self-start text-sm no-underline">
        <span className="text-ok hover:text-text">← {device?.name ?? "Device"}</span>
      </Link>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h1 className="font-display text-[32px] font-bold tracking-[-0.02em] lg:text-4xl">DNS activity</h1>
          <p className="font-mono text-[13px] text-faint">
            {device ? `${device.name} · ${device.last_ip ?? "no IP"}` : "…"} · from {dnsLabel} query log
          </p>
        </div>
        <Segmented
          label="Period"
          value={period}
          options={PERIODS.map((p) => ({ value: p.value, label: p.label }))}
          onChange={(value) => {
            setPeriod(value);
            setPage(0);
          }}
        />
      </header>

      {deviceRes.error && <Notice tone="error">{deviceRes.error}</Notice>}
      {features && !dnsLog && <Notice>No DNS provider with a query log is configured. Pick one in Settings → Network providers.</Notice>}
      {dnsLog && device && !device.last_ip && <Notice>This device has no known IP address yet, so there is no DNS activity to show.</Notice>}
      {dnsRes.error && <Notice tone="error">{dnsRes.error}</Notice>}
      {data?.totals.truncated && (
        <Notice>
          {dnsLabel} logged {data.totals.total} queries in this period; the breakdown below uses the latest {data.totals.sampled}.
        </Notice>
      )}
      {dnsRes.loading && device?.last_ip && !data && <p className="text-sm text-muted">Loading…</p>}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="Queries" value={String(data.totals.total)} note={data.totals.truncated ? `${data.totals.sampled} analysed` : "all analysed"} />
            <Stat label="Blocked" value={String(data.totals.blocked)} note={`${data.totals.blocked_pct}% of analysed`} tone="text-bad" />
            <Stat label="Unique domains" value={String(data.totals.unique_domains)} note={`${data.base_domains.length} base domains`} />
            <Stat
              label="Busiest"
              value={peak ? String(peak.total) : "—"}
              note={peak ? formatDateTime(peak.start, tz, tf) : "no queries"}
              tone="text-ok"
            />
          </div>

          <section className="rounded-[14px] border border-line bg-card px-6 py-5">
            <h2 className="mb-4 font-display text-[19px] font-bold">Over time</h2>
            <Timeline buckets={data.timeline} bucketSeconds={data.bucket_seconds} tz={tz} timeFormat={tf} />
          </section>

          <div className="grid items-stretch gap-5 lg:grid-cols-[1.6fr_1fr]">
            <section className="overflow-hidden rounded-[14px] border border-line bg-card">
              <div className="flex flex-wrap items-center gap-3 px-5 py-4">
                <h2 className="mr-auto font-display text-[19px] font-bold">Domains</h2>
                <input
                  type="search"
                  aria-label="Search domains"
                  placeholder="Search domain"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setPage(0);
                  }}
                  className="h-10 w-full rounded-lg border border-line2 bg-bg px-3 text-sm text-text outline-none placeholder:text-faint focus:border-accent sm:w-56"
                />
                <label className="flex items-center gap-2 text-sm text-text2">
                  <input
                    type="checkbox"
                    className="size-4 accent-[var(--accent)]"
                    checked={onlyBlocked}
                    onChange={(e) => {
                      setOnlyBlocked(e.target.checked);
                      setPage(0);
                    }}
                  />
                  Blocked only
                </label>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-y border-line text-left text-xs uppercase tracking-[.06em] text-faint">
                      {COLUMNS.map((c) => {
                        const active = sort.key === c.key;
                        const Arrow = !active ? ArrowUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown;
                        return (
                          <th
                            key={c.key}
                            scope="col"
                            aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
                            className={`px-4 py-1.5 font-medium ${c.className ?? ""}`}
                          >
                            <button type="button" onClick={() => toggle(c.key)} className={`inline-flex h-8 items-center gap-1.5 uppercase tracking-[.06em] hover:text-text ${active ? "text-text" : ""}`}>
                              {c.label}
                              <Arrow aria-hidden className={`size-3.5 ${active ? "" : "opacity-40"}`} />
                            </button>
                          </th>
                        );
                      })}
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((r) => (
                      <tr key={r.domain} className="border-b border-row hover:bg-card2">
                        <td className="max-w-[260px] px-4 py-2.5">
                          <span className="flex items-center gap-2">
                            <span className="truncate font-mono text-[13px]" title={r.domain}>
                              {r.domain}
                            </span>
                            {r.blocked && <Badge tone="bad">blocked</Badge>}
                          </span>
                        </td>
                        <td className="hidden px-4 py-2.5 font-mono text-[13px] text-muted md:table-cell">{r.base}</td>
                        <td className="px-4 py-2.5 text-right font-mono text-[13px]">{r.count}</td>
                        <td className="hidden whitespace-nowrap px-4 py-2.5 font-mono text-xs text-faint sm:table-cell">{formatDateTime(r.last_seen, tz, tf)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {rows.length === 0 && <p className="px-5 py-8 text-center text-sm text-muted">No domains match.</p>}
              </div>
              {rows.length > 0 && (
                <Pagination
                  page={page}
                  pageSize={pageSize}
                  total={rows.length}
                  onPage={setPage}
                  onPageSize={(size) => {
                    setPageSize(size);
                    setPage(0);
                  }}
                />
              )}
              {data.domains.length >= 200 && (
                <p className="border-t border-line px-5 py-2.5 text-xs text-faint">Showing the 200 most queried domains.</p>
              )}
            </section>

            <div className="flex flex-col gap-5">
              <section className="rounded-[14px] border border-line bg-card px-6 py-5">
                <h2 className="mb-3 font-display text-[19px] font-bold">Blocked domains</h2>
                <BarList rows={data.blocked_domains.slice(0, 10).map((d) => ({ label: d.domain, count: d.count }))} tone="bg-bad" />
              </section>
              <section className="rounded-[14px] border border-line bg-card px-6 py-5">
                <h2 className="mb-3 font-display text-[19px] font-bold">Top base domains</h2>
                <BarList rows={data.base_domains.slice(0, 8).map((d) => ({ label: d.domain, count: d.count }))} />
              </section>
              <section className="rounded-[14px] border border-line bg-card px-6 py-5">
                <h2 className="mb-3 font-display text-[19px] font-bold">Query types</h2>
                <BarList rows={data.query_types.map((t) => ({ label: t.type, count: t.count }))} tone="bg-accent" />
                {data.statuses.length > 0 && (
                  <>
                    <h3 className="mb-2 mt-5 text-[13px] font-semibold text-text2">How {dnsLabel} answered</h3>
                    <BarList rows={data.statuses.map((s) => ({ label: s.status.toLowerCase(), count: s.count }))} tone="bg-line2" />
                  </>
                )}
              </section>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
