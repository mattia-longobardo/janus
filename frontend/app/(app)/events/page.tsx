"use client";

import clsx from "clsx";
import { Search } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { TONE_DOT, eventTone } from "@/components/event-tone";
import { Button, Card, Notice, PageHeader, inputClass } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { EVENT_TYPES, describeEvent } from "@/lib/events";
import { formatDateTime } from "@/lib/format";
import { useSettings } from "@/lib/settings-context";
import type { EventItem } from "@/lib/types";

const PAGE = 50;

export default function EventsPage() {
  const { settings } = useSettings();
  const [type, setType] = useState("");
  const [mac, setMac] = useState("");
  const [events, setEvents] = useState<EventItem[]>([]);
  const [error, setError] = useState<string>();
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);

  const query = useCallback(
    (beforeId?: number) => {
      const params = new URLSearchParams({ limit: String(PAGE) });
      if (type) params.set("type", type);
      if (mac.trim()) params.set("mac", mac.trim().toUpperCase());
      if (beforeId) params.set("before_id", String(beforeId));
      return `/events?${params}`;
    },
    [type, mac],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      api
        .get<EventItem[]>(query())
        .then((page) => {
          if (cancelled) return;
          setEvents(page);
          setMore(page.length === PAGE);
          setError(undefined);
        })
        .catch((err) => !cancelled && setError(errorText(err)))
        .finally(() => !cancelled && setLoading(false));
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  async function loadMore() {
    const last = events.at(-1);
    if (!last) return;
    try {
      const page = await api.get<EventItem[]>(query(last.id));
      setEvents((current) => [...current, ...page]);
      setMore(page.length === PAGE);
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <>
      <PageHeader title="Event log" subtitle="everything Janus noticed or changed, newest first" />
      {error && <Notice tone="error">{error}</Notice>}
      <Card className="px-6 py-[22px]">
        <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="font-display text-[19px] font-bold">Events</h2>
          <div className="flex flex-col gap-3 sm:flex-row">
            <label className="sm:w-60">
              <span className="sr-only">Event type</span>
              <select className={inputClass} value={type} onChange={(e) => setType(e.target.value)}>
                <option value="">All events</option>
                {EVENT_TYPES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex h-11 items-center gap-2 rounded-lg border border-line2 bg-bg px-3 sm:w-72">
              <Search className="size-4 text-faint" aria-hidden />
              <span className="sr-only">MAC address</span>
              <input className="w-full bg-transparent font-mono text-sm outline-none" placeholder="Filter by MAC" value={mac} onChange={(e) => setMac(e.target.value)} />
            </label>
          </div>
        </div>
        {!loading && events.length === 0 ? (
          <p className="py-6 text-sm text-muted">No events match.</p>
        ) : (
          <ol className="flex flex-col">
            {events.map((event) => (
              <li key={event.id} className="grid grid-cols-[14px_1fr] items-start gap-x-3 gap-y-0.5 border-b border-row py-[9px] last:border-0 sm:grid-cols-[110px_14px_1fr_auto] sm:gap-3">
                {/* On phones the timestamp sits on its own line above the message. */}
                <span className="col-start-2 font-mono text-xs text-faint sm:col-start-auto">{formatDateTime(event.ts, settings.timezone, settings.time_format)}</span>
                <span aria-hidden className={clsx("mt-[5px] size-2 rounded-full", TONE_DOT[eventTone(event.type)])} />
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="text-sm text-text2">{describeEvent(event)}</span>
                  <span className="font-mono text-[11px] text-faint">{event.type}</span>
                </span>
                {event.mac ? (
                  <button
                    type="button"
                    title="Show only this device"
                    onClick={() => setMac(event.mac ?? "")}
                    className="col-start-2 justify-self-start font-mono text-xs text-muted hover:text-text sm:col-start-auto sm:justify-self-end"
                  >
                    {event.mac}
                  </button>
                ) : (
                  <span className="hidden sm:block" />
                )}
              </li>
            ))}
          </ol>
        )}
        {more && (
          <Button className="mt-4" onClick={() => void loadMore()}>
            Load older events
          </Button>
        )}
      </Card>
    </>
  );
}
