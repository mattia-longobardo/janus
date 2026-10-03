"use client";

import { ListOrdered } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import type { Group } from "@/lib/types";

interface Move {
  device_id: string;
  name: string;
  from: string;
  to: string;
}

interface CompactResult {
  moves: Move[];
  unchanged: number;
  pinned: { name: string; ip: string }[];
}

export function CompactGroup({ group, onDone, onError }: { group: Group; onDone: (text: string) => void; onError: (text: string) => void }) {
  const [preview, setPreview] = useState<CompactResult>();
  const [busy, setBusy] = useState(false);

  async function load() {
    setBusy(true);
    try {
      setPreview(await api.post<CompactResult>(`/groups/${group.id}/compact?dry_run=true`));
    } catch (err) {
      onError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    setBusy(true);
    try {
      const result = await api.post<CompactResult>(`/groups/${group.id}/compact?dry_run=false`);
      setPreview(undefined);
      onDone(`${group.name}: ${result.moves.length} address${result.moves.length === 1 ? "" : "es"} renumbered. Devices switch at their next renewal or restart.`);
    } catch (err) {
      onError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  if (!preview) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line px-3.5 py-2.5">
        <span className="text-[13px] text-muted">Renumber the members from the start of the range, keeping their order.</span>
        <Button onClick={() => void load()} disabled={busy}>
          <ListOrdered className="size-4" aria-hidden />
          Close gaps
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-accent-line bg-accent-soft px-3.5 py-3" aria-label="Close gaps preview">
      {preview.moves.length === 0 ? (
        <p className="text-sm text-text2">No gaps: every member already sits in order from the start of the range.</p>
      ) : (
        <>
          <p className="text-sm font-semibold text-text">
            {preview.moves.length} device{preview.moves.length === 1 ? "" : "s"} will get a new address
          </p>
          <ul className="flex flex-col gap-1 font-mono text-[13px] text-text2">
            {preview.moves.map((move) => (
              <li key={move.device_id} className="grid grid-cols-[1fr_auto] gap-3">
                <span className="truncate font-sans">{move.name}</span>
                <span>
                  {move.from} → <span className="text-accent-text">{move.to}</span>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {preview.pinned.length > 0 && (
        <p className="text-xs text-muted">
          Kept in place: {preview.pinned.map((p) => `${p.name} (${p.ip})`).join(", ")} — the gateway and this server never move.
        </p>
      )}
      {preview.moves.length > 0 && (
        <p className="text-xs text-muted">The DHCP provider gets the new reservations at once; each device switches at its next DHCP renewal or restart.</p>
      )}
      <div className="flex justify-end gap-2">
        <Button onClick={() => setPreview(undefined)} disabled={busy}>
          {preview.moves.length ? "Cancel" : "Close"}
        </Button>
        {preview.moves.length > 0 && (
          <Button variant="primary" onClick={() => void apply()} disabled={busy}>
            Apply
          </Button>
        )}
      </div>
    </div>
  );
}
