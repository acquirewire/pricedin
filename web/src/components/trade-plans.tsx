import { Section } from "@/components/primitives";
import { cn } from "@/lib/utils";
import type { TradePlan } from "@/lib/types";
import { DASH, bps, money, pct, share, signed } from "@/lib/format";

const STYLE_LABEL: Record<string, string> = {
  through_print: "Hold through the print",
  post_print_drift: "Enter after the gap",
  premium_sell: "Sell the event premium",
};

const STYLE_NOTE: Record<string, string> = {
  through_print:
    "Position is open across the announcement, so the exit is time-based.",
  post_print_drift:
    "Entry is the reaction close, once the gap has already happened.",
  premium_sell:
    "Requires options permissions. The only style backed by a finding that survived holdout.",
};

function Field({
  label,
  value,
  className,
}: {
  label: string;
  value: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="label">{label}</div>
      <div className="mt-1 font-mono text-[13px] tabular-nums">{value}</div>
    </div>
  );
}

export function TradePlans({ plans }: { plans: TradePlan[] }) {
  return (
    <Section
      title="Trade geometry"
      description="Levels are derived from predicted move size, which is measurable. Expected value uses the empirical hit rate for that move size, which is why most of these come back negative — that is the honest answer, not a broken calculation."
    >
      <div className="grid gap-4 lg:grid-cols-3">
        {plans.map((p) => (
          <article
            key={p.style}
            className={cn(
              "rounded-md border p-4",
              p.tradeable ? "border-foreground/25" : "border-border",
            )}
          >
            <header className="flex items-start justify-between gap-3 pb-3">
              <div>
                <h3 className="text-[13px] font-semibold">
                  {STYLE_LABEL[p.style] ?? p.style}
                </h3>
                <p className="mt-0.5 text-[11.5px] leading-snug text-muted-foreground">
                  {STYLE_NOTE[p.style]}
                </p>
              </div>
              <span
                className={cn(
                  "shrink-0 rounded-sm border px-1.5 py-0.5 text-[10.5px] font-medium whitespace-nowrap",
                  p.tradeable
                    ? "border-pos/35 bg-pos-subtle text-pos"
                    : "border-border text-muted-foreground",
                )}
              >
                {p.tradeable ? "Positive EV" : "Negative EV"}
              </span>
            </header>

            <div className="grid grid-cols-3 gap-3 border-y py-3">
              <Field
                label="Expected value"
                value={
                  <span
                    className={
                      p.ev_bps == null
                        ? ""
                        : p.ev_bps > 0
                          ? "text-pos"
                          : "text-neg"
                    }
                  >
                    {bps(p.ev_bps)} bps
                  </span>
                }
              />
              <Field label="Direction" value={p.direction} />
              <Field
                label={p.style === "premium_sell" ? "Edge" : "Hit rate"}
                value={
                  p.style === "premium_sell"
                    ? `${signed(p.ev_bps ? p.ev_bps / 100 : null, 1, "pp")}`
                    : share(p.p_win)
                }
              />
            </div>

            <div className="grid grid-cols-3 gap-3 py-3">
              <Field
                label={p.style === "through_print" ? "Target" : "Take profit"}
                value={p.tp_price != null ? money(p.tp_price, 2) : DASH}
              />
              <Field
                label="Stop"
                value={
                  p.sl_price != null ? (
                    money(p.sl_price, 2)
                  ) : (
                    <span className="text-muted-foreground">None</span>
                  )
                }
              />
              <Field
                label="Size"
                value={p.size_pct != null ? pct(p.size_pct) : DASH}
              />
            </div>

            {p.entry_rule && (
              <p className="border-t pt-3 text-[12px] leading-relaxed text-muted-foreground">
                {p.entry_rule}
              </p>
            )}
            {p.risk_note && (
              <p className="mt-2 text-[12px] leading-relaxed">{p.risk_note}</p>
            )}
          </article>
        ))}
      </div>
    </Section>
  );
}
