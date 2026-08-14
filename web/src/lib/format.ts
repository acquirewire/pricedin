/**
 * Formatting helpers.
 *
 * Every one of these returns an em dash for a missing value rather than "0",
 * "N/A" or an empty cell. On a research screen the difference between "we
 * measured zero" and "we have no measurement" is the whole point, and
 * collapsing the two is how a dashboard quietly starts lying.
 */

export const DASH = "—";

export function num(
  v: number | null | undefined,
  digits = 1,
  suffix = "",
): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  return v.toFixed(digits) + suffix;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  return `${v.toFixed(digits)}%`;
}

/** Signed, for values where direction carries meaning. */
export function signed(v: number | null | undefined, digits = 1, suffix = "%") {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}${suffix}`;
}

export function ratio(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  return `${v.toFixed(digits)}×`;
}

export function share(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  return `${Math.round(v * 100)}%`;
}

export function marketCap(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  if (v >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${Math.round(v / 1e6)}M`;
  return v.toFixed(0);
}

export function money(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  const sign = v < 0 ? "−" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function bps(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  return `${v > 0 ? "+" : ""}${v.toFixed(0)}`;
}

/** Tailwind class for a value whose sign should be read. */
export function toneOf(v: number | null | undefined, flip = false): string {
  if (v === null || v === undefined || !Number.isFinite(v) || v === 0)
    return "text-muted-foreground";
  const positive = flip ? v < 0 : v > 0;
  return positive ? "text-pos" : "text-neg";
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

export function longDate(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function sessionLabel(s: string | null | undefined): string {
  if (s === "pre") return "Pre-market";
  if (s === "post") return "After close";
  return "Unscheduled";
}

/** T−4, T−0 … reads as a countdown rather than an arbitrary integer. */
export function countdown(days: number | null | undefined): string {
  if (days === null || days === undefined) return DASH;
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  return `T−${days}`;
}
