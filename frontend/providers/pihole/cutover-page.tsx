"use client";

import clsx from "clsx";
import { CheckCircle2, CircleHelp, XCircle } from "lucide-react";
import { useState } from "react";

import { Button, Card, PageHeader } from "@/components/ui";
import { api, errorText } from "@/lib/api";

export interface PreflightCheck {
  name: string;
  ok: boolean | null;
  detail: string;
  blocking: boolean;
}

export interface PreflightReport {
  ready: boolean;
  checks: PreflightCheck[];
  plan: { to_add?: number; to_remove?: number; unmanaged?: number };
}

const LABELS: Record<string, string> = {
  pihole_is_dhcp_provider: "DHCP role",
  pihole_reachable: "Pi-hole API",
  pihole_dhcp: "Pi-hole DHCP",
  write_access: "Write access",
  quarantine_rules: "Quarantine rules",
  dhcp_range: "DHCP range",
  approved_devices_complete: "Approved devices",
  no_duplicates: "Duplicates",
  sync_plan: "Reservations",
  backup: "Backup",
};

export function CutoverPage() {
  const [report, setReport] = useState<PreflightReport>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setError(undefined);
    try {
      setReport(await api.get<PreflightReport>("/providers/pihole/preflight"));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="DHCP cutover" subtitle="Pi-hole · readiness checks" />
      <Card className="flex flex-col gap-3 px-6 py-[22px]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="flex flex-col gap-0.5">
            <span className="text-[15px] font-semibold">Cutover readiness</span>
            <span className="text-[13px] text-muted">Read-only checks before Pi-hole takes over DHCP. The cutover itself runs from the runbook.</span>
          </span>
          <Button onClick={() => void run()} disabled={busy}>
            {busy ? "Checking…" : "Run checks"}
          </Button>
        </div>
        {error && (
          <p role="alert" className="text-sm text-bad">
            {error}
          </p>
        )}
        {report && (
          <>
            <p className={clsx("text-sm font-semibold", report.ready ? "text-ok" : "text-bad")}>
              {report.ready ? "Ready for the cutover" : "Not ready yet"}
            </p>
            <ul className="flex flex-col">
              {report.checks.map((check) => {
                const Icon = check.ok === true ? CheckCircle2 : check.ok === false ? XCircle : CircleHelp;
                return (
                  <li key={check.name} className="grid grid-cols-[20px_140px_1fr] items-start gap-2 border-b border-row py-2 text-[13px] last:border-0">
                    <Icon
                      aria-label={check.ok === true ? "passed" : check.ok === false ? "failed" : "unknown"}
                      className={clsx(
                        "mt-px size-4",
                        check.ok === true ? "text-ok" : check.ok === false ? (check.blocking ? "text-bad" : "text-accent-text") : "text-faint",
                      )}
                    />
                    <span className="font-medium text-text2">{LABELS[check.name] ?? check.name}</span>
                    <span className="text-muted">{check.detail}</span>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </Card>
    </>
  );
}
