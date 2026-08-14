import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

/** Page title block. One per page, no decoration. */
export function PageHeading({
  title,
  lede,
  aside,
}: {
  title: string;
  lede?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 pb-5">
      <div className="max-w-2xl">
        <h1 className="text-[22px] font-semibold">{title}</h1>
        {lede && (
          <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">
            {lede}
          </p>
        )}
      </div>
      {aside}
    </div>
  );
}

/** A figure with a label. Used in rows, never as a floating card grid. */
export function Stat({
  label,
  value,
  sub,
  className,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="label">{label}</div>
      <div className="mt-1 font-mono text-[19px] leading-none tabular-nums">
        {value}
      </div>
      {sub && (
        <div className="mt-1.5 text-[11.5px] leading-snug text-muted-foreground">
          {sub}
        </div>
      )}
    </div>
  );
}

export function StatRow({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-5 border-y py-4 sm:grid-cols-3 lg:grid-cols-5">
      {children}
    </div>
  );
}

/** Section with a rule and a small caps heading. */
export function Section({
  title,
  description,
  children,
  action,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="pt-9">
      <div className="flex items-end justify-between gap-4 pb-3">
        <div className="max-w-2xl">
          <h2 className="text-[13px] font-semibold">{title}</h2>
          {description && (
            <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
              {description}
            </p>
          )}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

/**
 * A caveat that must not be skimmable-past. Used for the backtest result and
 * the not-advice notice — the two things a reader most needs and least wants.
 */
export function Notice({
  title,
  children,
  tone = "warn",
}: {
  title?: string;
  children: ReactNode;
  tone?: "warn" | "muted";
}) {
  return (
    <aside
      className={cn(
        "border-l-2 py-2.5 pl-4 text-[13px] leading-relaxed",
        tone === "warn"
          ? "border-l-foreground/40 text-foreground/90"
          : "border-l-border text-muted-foreground",
      )}
    >
      {title && <div className="mb-1 font-semibold">{title}</div>}
      {children}
    </aside>
  );
}

/** Definition row for the detail panels. */
export function Row({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border/60 py-[7px] last:border-0">
      <span className="text-[12.5px] text-muted-foreground" title={hint}>
        {label}
      </span>
      <span className="num shrink-0">{value}</span>
    </div>
  );
}
