import clsx from "clsx";
import type { CSSProperties, ReactNode } from "react";

export function InfoCard({ title, children, footer, className }: { title: string; children: ReactNode; footer?: ReactNode; className?: string }) {
  return (
    <section className={clsx("flex flex-col rounded-[14px] border border-line bg-card px-6 py-5", className)}>
      <h2 className="mb-1.5 font-display text-[19px] font-bold">{title}</h2>
      {children}
      {footer && <p className="mt-auto pt-3 text-xs text-faint">{footer}</p>}
    </section>
  );
}

export function InfoRow({ label, value, source, mono = false, labelWidth = 150 }: {
  label: string;
  value: ReactNode;
  source?: string;
  mono?: boolean;
  labelWidth?: number;
}) {
  // Phones stack the label above the value so the value gets the full width; from sm up the label sits in its own column.
  return (
    <div
      className={clsx(
        "grid items-center gap-x-3 gap-y-1 border-b border-row py-[11px] sm:gap-3",
        source === undefined ? "grid-cols-1 sm:grid-cols-[var(--label-w)_1fr]" : "grid-cols-[1fr_auto] sm:grid-cols-[var(--label-w)_1fr_auto]",
      )}
      style={{ "--label-w": `${labelWidth}px` } as CSSProperties}
    >
      <span className={clsx("text-[13px] text-faint", source !== undefined && "col-span-2 sm:col-span-1")}>{label}</span>
      {/* Addresses and other mono tokens wrap only at spaces on phones, never inside the token. */}
      <span className={clsx("min-w-0 text-sm", mono ? "font-mono break-normal sm:break-words" : "break-words")}>{value}</span>
      {source !== undefined && (
        <span className="whitespace-nowrap rounded-full border border-line2 px-2 py-0.5 text-[11px] text-muted">{source}</span>
      )}
    </div>
  );
}

export function StatCard({ label, value, note, tone }: { label: string; value: ReactNode; note?: ReactNode; tone?: string }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-[14px] border border-line bg-card px-5 py-[18px]">
      <span className="text-[13px] text-muted">{label}</span>
      <span className={clsx("font-display text-[30px] font-bold leading-none", tone)}>{value}</span>
      {note && <span className="text-xs text-faint">{note}</span>}
    </div>
  );
}
