"use client";

import { useState } from "react";

import { Button } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { useCurrentUser } from "@/lib/current-user";

type Plan = { to_add: string[]; to_remove: string[]; failed: string[] };
type Mode = "dry-run" | "apply";

/** Admin-only switch between dry-run and apply; going to apply first shows what the DHCP provider would receive. */
export function EnforcementSwitch({ mode, hasDhcp, onChanged }: { mode: Mode; hasDhcp: boolean; onChanged: () => Promise<void> | void }) {
  const user = useCurrentUser();
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  if (user?.role !== "admin") return null;

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(undefined);
    try {
      await action();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const review = () => run(async () => setPlan(await api.get<Plan>("/sync/plan")));
  const switchTo = (next: Mode) =>
    run(async () => {
      await api.post("/sync/mode", { mode: next });
      setPlan(null);
      await onChanged();
    });

  return (
    <div className="flex flex-col gap-2 pb-3">
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      {mode === "apply" ? (
        <div>
          <Button className="h-9" disabled={busy} onClick={() => void switchTo("dry-run")}>
            Switch to dry-run
          </Button>
        </div>
      ) : plan ? (
        <div className="flex flex-col gap-2 rounded-lg border border-line2 p-3 text-sm">
          <span>
            Apply now: {plan.to_add.length} to add · {plan.to_remove.length} to remove · {plan.failed.length} failed
          </span>
          <span className="text-xs text-muted">Janus will write these reservations to the DHCP provider and keep it in sync.</span>
          <div className="flex gap-2">
            <Button variant="primary" className="h-9" disabled={busy} onClick={() => void switchTo("apply")}>
              Confirm apply
            </Button>
            <Button className="h-9" disabled={busy} onClick={() => setPlan(null)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div>
          <Button className="h-9" disabled={busy || !hasDhcp} onClick={() => void review()}>
            Switch to apply…
          </Button>
        </div>
      )}
    </div>
  );
}
