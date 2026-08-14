import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { StanceBadge } from "@/components/stance-badge";
import { SparkBars } from "@/components/sparkbars";
import { TradePlans } from "@/components/trade-plans";
import { Notice, Row, Section } from "@/components/primitives";
import { allSymbols, getEvent } from "@/lib/data";
import { cn } from "@/lib/utils";
import {
  DASH,
  countdown,
  longDate,
  marketCap,
  money,
  num,
  pct,
  ratio,
  sessionLabel,
  share,
  signed,
  toneOf,
} from "@/lib/format";

export function generateStaticParams() {
  return allSymbols().map((symbol) => ({ symbol }));
}

export async function generateMetadata(props: PageProps<"/s/[symbol]">) {
  const { symbol } = await props.params;
  const e = getEvent(symbol);
  if (!e) return { title: symbol };
  return {
    title: `${e.symbol} — ${e.name ?? "earnings"}`,
    description: `${e.symbol} reports ${e.report_date}. Implied move ${pct(
      e.implied_move_pct,
    )} against ${pct(e.realised_move_med_8)} median realised.`,
  };
}

export default async function SymbolPage(props: PageProps<"/s/[symbol]">) {
  const { symbol } = await props.params;
  const e = getEvent(symbol);
  if (!e) notFound();

  const v = e.verdict;

  return (
    <div>
      <Link
        href="/"
        className="mb-5 inline-flex items-center gap-1.5 text-[12.5px] text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        Calendar
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4 border-b pb-5">
        <div>
          <div className="flex items-baseline gap-3">
            <h1 className="text-[26px] font-semibold">{e.symbol}</h1>
            {v && <StanceBadge stance={v.stance} tone={v.tone} />}
          </div>
          <p className="mt-1 text-[13.5px] text-muted-foreground">{e.name}</p>
        </div>

        <dl className="flex flex-wrap gap-x-8 gap-y-3">
          <div>
            <dt className="label">Reports</dt>
            <dd className="mt-1 font-mono text-[13px]">
              {longDate(e.report_date)}
            </dd>
            <dd className="text-[11.5px] text-muted-foreground">
              {sessionLabel(e.session)} · {countdown(e.days_to_report)}
            </dd>
          </div>
          <div>
            <dt className="label">Price</dt>
            <dd className="mt-1 font-mono text-[13px]">
              {e.price != null ? money(e.price, 2) : DASH}
            </dd>
          </div>
          <div>
            <dt className="label">Market cap</dt>
            <dd className="mt-1 font-mono text-[13px]">
              {marketCap(e.market_cap)}
            </dd>
          </div>
          <div>
            <dt className="label">Consensus EPS</dt>
            <dd className="mt-1 font-mono text-[13px]">
              {e.eps_forecast != null ? e.eps_forecast.toFixed(2) : DASH}
            </dd>
            <dd className="text-[11.5px] text-muted-foreground">
              {e.n_analysts ?? e.n_estimates ?? DASH} analysts
            </dd>
          </div>
        </dl>
      </div>

      {/* The three panels stay separate deliberately: a single blended score
          would hide which question is driving the reading. */}
      <div className="grid gap-x-10 gap-y-8 pt-7 lg:grid-cols-3">
        <div>
          <h2 className="text-[13px] font-semibold">Expectation</h2>
          <p className="mb-3 mt-1 text-[12px] leading-relaxed text-muted-foreground">
            Will they beat?
          </p>
          <Row
            label="Historical beat frequency"
            value={
              <>
                {share(e.p_beat)}
                <span className="ml-1.5 text-muted-foreground">
                  {e.p_beat_n ? `n=${e.p_beat_n}` : "base"}
                </span>
              </>
            }
            hint="Frequency with which similar-looking names beat, fitted on training data only"
          />
          <Row label="Beat rate, last 8" value={share(e.beat_rate_8)} />
          <Row
            label="Mean surprise, last 4"
            value={
              <span className={toneOf(e.surp_mean_4)}>
                {signed(e.surp_mean_4)}
              </span>
            }
          />
          <Row
            label="Consensus revision 30d"
            value={
              <span className={toneOf(e.rev_chg_30d)}>
                {signed(e.rev_chg_30d)}
              </span>
            }
          />
          <Row
            label="Consensus revision 90d"
            value={
              <span className={toneOf(e.rev_chg_90d)}>
                {signed(e.rev_chg_90d)}
              </span>
            }
          />
          <Row
            label="Revision breadth 30d"
            value={
              e.up_30d != null
                ? `${e.up_30d} up / ${e.down_30d ?? 0} down`
                : DASH
            }
          />
        </div>

        <div>
          <h2 className="text-[13px] font-semibold">Asymmetry</h2>
          <p className="mb-3 mt-1 text-[12px] leading-relaxed text-muted-foreground">
            Is it worth it? The panel with evidence behind it.
          </p>
          <Row
            label="Implied move (straddle)"
            value={pct(e.implied_move_pct)}
            hint="ATM straddle mid on the first expiry after the print, as a percentage of spot"
          />
          <Row
            label="Median realised, last 8"
            value={pct(e.realised_move_med_8)}
          />
          <Row
            label="Largest realised, last 8"
            value={pct(e.realised_move_max_8)}
          />
          <Row
            label="Implied ÷ realised"
            value={
              <span
                className={cn(
                  e.implied_vs_realised == null
                    ? ""
                    : e.implied_vs_realised >= 1.3
                      ? "text-neg"
                      : e.implied_vs_realised <= 0.85
                        ? "text-pos"
                        : "",
                )}
              >
                {ratio(e.implied_vs_realised)}
              </span>
            }
          />
          <Row
            label="Run-up, 10 sessions"
            value={
              <span className={toneOf(e.runup_10d)}>{signed(e.runup_10d)}</span>
            }
          />
          <Row
            label="Run-up, 60 sessions"
            value={
              <span className={toneOf(e.runup_60d)}>{signed(e.runup_60d)}</span>
            }
          />
          <Row label="Realised vol, 20d" value={pct(e.vol_20d, 0)} />
        </div>

        <div>
          <h2 className="text-[13px] font-semibold">Reaction</h2>
          <p className="mb-3 mt-1 text-[12px] leading-relaxed text-muted-foreground">
            Does beating actually help?
          </p>
          <Row
            label="Mean reaction, last 8"
            value={
              <span className={toneOf(e.reac_mean_8)}>
                {signed(e.reac_mean_8)}
              </span>
            }
          />
          <Row
            label="Median reaction, last 8"
            value={
              <span className={toneOf(e.reac_median_8)}>
                {signed(e.reac_median_8)}
              </span>
            }
          />
          <Row
            label="Reaction / surprise slope"
            value={num(e.reaction_slope, 4)}
            hint="Regression slope of past reactions on past surprises. Flat or negative means beating does not get rewarded."
          />
          <Row label="Beat but fell" value={share(e.beat_and_fell_rate)} />
          <Row
            label="Last 4 reactions"
            value={<SparkBars values={e.last_reactions} />}
          />
          <Row label="Quarters of history" value={num(e.n_quarters, 0)} />
        </div>
      </div>

      {v && (v.supports.length > 0 || v.against.length > 0) && (
        <Section
          title="How this reading was reached"
          description="Every clause names the figure that produced it, so you can argue with the input rather than the conclusion."
        >
          <ul className="max-w-3xl space-y-1.5">
            {v.supports.map((s, i) => (
              <li key={`s${i}`} className="flex gap-2.5 text-[13px]">
                <span className="mt-px font-mono text-pos">+</span>
                <span>{s}</span>
              </li>
            ))}
            {v.against.map((s, i) => (
              <li key={`a${i}`} className="flex gap-2.5 text-[13px]">
                <span className="mt-px font-mono text-neg">−</span>
                <span>{s}</span>
              </li>
            ))}
            {v.neutral.map((s, i) => (
              <li
                key={`n${i}`}
                className="flex gap-2.5 text-[13px] text-muted-foreground"
              >
                <span className="mt-px font-mono">·</span>
                <span>{s}</span>
              </li>
            ))}
          </ul>
          {v.caveat && (
            <div className="max-w-3xl pt-4">
              <Notice tone="muted">{v.caveat}</Notice>
            </div>
          )}
        </Section>
      )}

      {e.plans && e.plans.length > 0 && <TradePlans plans={e.plans} />}
    </div>
  );
}
