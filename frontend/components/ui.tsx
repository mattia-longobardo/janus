import clsx from "clsx";
import { Check, ChevronLeft, ChevronRight, type LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

// Below lg the sticky mobile header (h-14) covers whatever is scrolled to the top; anchor and scroll targets leave room for it.
export const SCROLL_TARGET = "scroll-mt-[72px] lg:scroll-mt-0";

export const inputClass =
  "h-11 w-full rounded-lg border border-line2 bg-bg px-3 text-[15px] text-text outline-none focus:border-accent";

// An input with its unit drawn inside, on the right (e.g. "h", "s").
export function SuffixInput({ suffix, className, ...props }: InputHTMLAttributes<HTMLInputElement> & { suffix?: string }) {
  return (
    <div className="relative">
      <input className={clsx(inputClass, suffix && "pr-8", className)} {...props} />
      {suffix && (
        <span data-suffix aria-hidden className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 font-mono text-sm text-faint">
          {suffix}
        </span>
      )}
    </div>
  );
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={clsx("rounded-[14px] border border-line bg-card", className)} {...props} />;
}

const VARIANTS = {
  primary: "border-accent bg-accent text-accent-ink font-semibold",
  secondary: "border-line2 bg-card text-text",
  danger: "border-line2 bg-card text-bad",
  ghost: "border-transparent bg-transparent text-muted hover:text-text",
} as const;

export function Button({
  variant = "secondary",
  className,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof VARIANTS }) {
  return (
    <button
      type={type}
      className={clsx(
        "inline-flex h-11 items-center justify-center gap-2 rounded-lg border px-4 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
}

export function StatusDot({ online }: { online: boolean }) {
  return <span aria-hidden className={clsx("inline-block size-2 shrink-0 rounded-full", online ? "bg-ok" : "bg-off")} />;
}

export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "accent" | "bad" | "ok"; children: ReactNode }) {
  const tones = {
    neutral: "border-line2 text-muted",
    accent: "border-accent-line text-accent-text",
    bad: "border-bad text-bad",
    ok: "border-ok text-ok",
  };
  return <span className={clsx("inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium", tones[tone])}>{children}</span>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="flex min-w-0 flex-col gap-1.5">
        <h1 className="font-display text-3xl font-bold tracking-tight lg:text-4xl">{title}</h1>
        {subtitle && <p className="font-mono text-[13px] text-faint">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-3">{actions}</div>}
    </header>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="font-display text-xl font-bold">{children}</h2>;
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <label className="flex flex-col gap-2">
        <span className="text-[13px] font-medium text-text2">{label}</span>
        {children}
      </label>
      {hint && <span className="text-xs text-faint">{hint}</span>}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "error" | "success"; children: ReactNode }) {
  const tones = { info: "border-line2 text-text2", error: "border-bad text-bad", success: "border-ok text-ok" };
  return (
    <p role={tone === "error" ? "alert" : "status"} className={clsx("mb-4 rounded-lg border bg-card px-3 py-2 text-sm", tones[tone])}>
      {children}
    </p>
  );
}

export function IconTile({ Icon, color, size = 36, muted = false }: { Icon: LucideIcon; color: string; size?: number; muted?: boolean }) {
  return (
    <span
      aria-hidden
      className={clsx("flex shrink-0 items-center justify-center rounded-lg", muted && "opacity-60")}
      style={{ width: size, height: size, background: `${color}26`, color }}
    >
      <Icon style={{ width: size * 0.5, height: size * 0.5 }} strokeWidth={1.8} />
    </span>
  );
}

export function Checkbox({ className, label, ...props }: InputHTMLAttributes<HTMLInputElement> & { label?: ReactNode }) {
  const box = (
    <span className="relative inline-flex size-[22px] shrink-0">
      <input
        type="checkbox"
        className="peer absolute inset-0 m-0 cursor-pointer appearance-none rounded-[5px] border-[1.5px] border-line2 bg-bg checked:border-accent checked:bg-accent"
        {...props}
      />
      <Check aria-hidden strokeWidth={3} className="pointer-events-none absolute inset-[3px] size-4 text-accent-ink opacity-0 peer-checked:opacity-100" />
    </span>
  );
  if (!label) return <span className={className}>{box}</span>;
  return (
    <label className={clsx("flex min-h-11 cursor-pointer items-center gap-3 text-sm text-text2", className)}>
      {box}
      <span>{label}</span>
    </label>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex gap-0.5 rounded-[10px] border border-line bg-row p-1">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={clsx(
            "h-9 rounded-md px-4 text-sm font-medium",
            value === option.value ? "bg-card text-text shadow-sm" : "text-muted hover:text-text",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Chip({ active, count, children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { active: boolean; count?: number }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={clsx(
        "inline-flex h-[34px] items-center gap-1.5 rounded-full border px-3 text-[13px]",
        active ? "border-inv-bg bg-inv-bg text-inv-fg" : "border-line2 bg-transparent text-text2 hover:text-text",
      )}
      {...props}
    >
      {children}
      {count !== undefined && <span className="font-mono opacity-70">{count}</span>}
    </button>
  );
}

export const PAGE_SIZES = [10, 25, 50, 100];

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
  onPageSize,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
  onPageSize: (size: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : page * pageSize + 1;
  const last = Math.min(total, (page + 1) * pageSize);
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3 text-[13px] text-muted">
      <label className="flex items-center gap-2">
        Rows per page
        <select
          aria-label="Rows per page"
          className="h-9 rounded-md border border-line2 bg-bg px-2 font-mono text-[13px] text-text"
          value={pageSize}
          onChange={(e) => onPageSize(Number(e.target.value))}
        >
          {PAGE_SIZES.map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
      </label>
      <div className="flex items-center gap-3">
        <span className="font-mono">
          {first}–{last} of {total}
        </span>
        <span className="flex gap-1">
          <button
            type="button"
            aria-label="Previous page"
            disabled={page === 0}
            onClick={() => onPage(page - 1)}
            className="flex size-9 items-center justify-center rounded-md border border-line2 text-text disabled:opacity-40"
          >
            <ChevronLeft className="size-4" />
          </button>
          <button
            type="button"
            aria-label="Next page"
            disabled={page >= pages - 1}
            onClick={() => onPage(page + 1)}
            className="flex size-9 items-center justify-center rounded-md border border-line2 text-text disabled:opacity-40"
          >
            <ChevronRight className="size-4" />
          </button>
        </span>
      </div>
    </div>
  );
}
