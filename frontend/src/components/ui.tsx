// Shared instrument-panel UI primitives for TerraTrace AI.

import type { ReactNode } from "react";
import { AlertTriangle, Inbox, Loader2, RefreshCw } from "lucide-react";

export type Tone =
  | "accent"
  | "steel"
  | "steel2"
  | "amber"
  | "danger"
  | "success"
  | "muted"
  | "raised";

const TONE_CLASSES: Record<Tone, string> = {
  accent: "border-accent/45 text-accent bg-accent/10",
  steel: "border-steel/55 text-steel2 bg-steel/12",
  steel2: "border-steel2/45 text-steel2 bg-steel2/10",
  amber: "border-amber/50 text-amber bg-amber/10",
  danger: "border-danger/50 text-danger bg-danger/10",
  success: "border-success/45 text-success bg-success/10",
  muted: "border-line text-muted bg-raised",
  raised: "border-line2 text-paper bg-raised",
};

export function Badge({
  tone = "muted",
  children,
  className = "",
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium leading-4 whitespace-nowrap ${TONE_CLASSES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

/** Panel with a small-caps header row. */
export function Panel({
  title,
  right,
  children,
  className = "",
  bodyClassName = "",
}: {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`panel flex min-w-0 flex-col ${className}`}>
      {title !== undefined && (
        <header className="flex min-h-[44px] items-center justify-between gap-4 border-b border-line px-4 py-2">
          <div className="label truncate">{title}</div>
          <div className="flex shrink-0 items-center gap-2">{right}</div>
        </header>
      )}
      <div className={`min-w-0 flex-1 ${bodyClassName}`}>{children}</div>
    </section>
  );
}

export function EmptyState({
  title,
  hint,
  icon,
  compact = false,
}: {
  title: string;
  hint?: string;
  icon?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-1.5 text-center ${
        compact ? "px-6 py-8" : "px-8 py-14"
      }`}
    >
      <div className="text-muted/70">{icon ?? <Inbox size={compact ? 18 : 22} strokeWidth={1.5} />}</div>
      <p className="max-w-md text-[14px] leading-6 text-paper/85">{title}</p>
      {hint && <p className="max-w-md text-[13px] leading-6 text-muted">{hint}</p>}
    </div>
  );
}

export function ErrorBanner({
  message,
  onRetry,
  className = "",
}: {
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      className={`flex items-start justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 ${className}`}
      role="alert"
    >
      <div className="flex min-w-0 items-start gap-2">
        <AlertTriangle size={15} className="mt-0.5 shrink-0 text-danger" />
        <div className="min-w-0">
          <p className="text-[13px] leading-6 text-paper">{message}</p>
        </div>
      </div>
      {onRetry && (
        <button className="btn shrink-0" onClick={onRetry}>
          <RefreshCw size={12} /> Retry
        </button>
      )}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse bg-raised ${className}`} />;
}

export function LoadingRows({ rows = 4, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-2 p-3">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-3">
          {Array.from({ length: cols }).map((__, c) => (
            <Skeleton
              key={c}
              className={`h-3 ${c === 0 ? "w-40" : "flex-1"} ${r % 2 ? "opacity-60" : ""}`}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function Spinner({ size = 14, className = "" }: { size?: number; className?: string }) {
  return <Loader2 size={size} className={`animate-spin ${className}`} />;
}

/** Loading placeholder for a whole panel body. */
export function PanelLoading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-3 py-4 text-[12px] text-muted">
      <Spinner /> {label}
    </div>
  );
}

/** Label / value pair with monospace numerals. */
export function KV({
  label,
  value,
  mono = false,
  title,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
  title?: string;
}) {
  return (
    <div className="min-w-0" title={title}>
      <div className="label">{label}</div>
      <div className={`mt-1 break-words text-[14px] leading-6 text-paper ${mono ? "num" : ""}`}>
        {value}
      </div>
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
  tone = "paper",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "paper" | "accent" | "muted" | "amber" | "danger";
}) {
  const toneClass =
    tone === "accent"
      ? "text-accent"
      : tone === "muted"
        ? "text-muted"
        : tone === "amber"
          ? "text-amber"
          : tone === "danger"
            ? "text-danger"
            : "text-paper";
  return (
    <div className="min-w-0 rounded-xl border border-line bg-white px-4 py-3">
      <div className="label">{label}</div>
      <div className={`num mt-1 break-words text-[24px] leading-7 ${toneClass}`}>{value}</div>
      {sub !== undefined && <div className="mt-1 text-[12.5px] leading-5 text-muted">{sub}</div>}
    </div>
  );
}

export function Chip({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className="inline-block rounded-full border border-line bg-raised px-2.5 py-1 font-mono text-[11px] leading-4 text-slate-600"
    >
      {children}
    </span>
  );
}

/** Vertical key/value list used in detail side panels. */
export function DataList({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="divide-y divide-line/70">
      {items.map((item, i) => (
        <div key={i} className="flex items-baseline justify-between gap-4 px-4 py-2.5">
          <dt className="label shrink-0">{item.label}</dt>
          <dd className="min-w-0 break-words text-right text-[13.5px] leading-6 text-paper">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Pager({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-2.5">
      <span className="num text-[12px] text-muted">
        page {page} / {pages} · {total} records
      </span>
      <div className="flex gap-2">
        <button className="btn" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Prev
        </button>
        <button className="btn" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </button>
      </div>
    </div>
  );
}

export function SectionHeading({
  title,
  sub,
  right,
}: {
  title: string;
  sub?: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 pb-3">
      <div className="min-w-0">
        <h1 className="text-[20px] font-semibold leading-7 tracking-tight">{title}</h1>
        {sub && <p className="mt-1 max-w-2xl text-[13.5px] leading-6 text-muted">{sub}</p>}
      </div>
      {right && <div className="flex items-center gap-2">{right}</div>}
    </div>
  );
}
