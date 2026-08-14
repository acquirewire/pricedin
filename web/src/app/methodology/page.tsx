import { Fragment } from "react";

import { Notice, PageHeading, Section, Stat, StatRow } from "@/components/primitives";
import { backtest, meta } from "@/lib/data";
import { cn } from "@/lib/utils";
import { DASH, bps, num, share } from "@/lib/format";

export const metadata = { title: "Methodology" };

const PERIODS = ["train", "validate", "holdout"] as const;

function byName<T extends { name: string; period: string }>(rows: T[]) {
  const map = new Map<string, Record<string, T>>();
  for (const r of rows) {
    const e = map.get(r.name) ?? {};
    e[r.period] = r;
    map.set(r.name, e);
  }
  return map;
}

export default function MethodologyPage() {
  const strategies = byName(backtest.strategies);
  const magnitude = byName(backtest.magnitude);
  const survivors = backtest.survivors ?? [];
  const mm = backtest.move_model;

  // `survived` in the CSV means "cleared train AND validate" — the holdout is
  // deliberately not consulted when selecting. Reporting that number alone
  // would overstate the result, because the one strategy that got that far
  // then failed out of sample. So compute both, and show the honest one.
  const clearedGate = survivors.filter((s) => s.survived);
  const holdoutExcess = new Map(
    backtest.strategies
      .filter((r) => r.period === "holdout")
      .map((r) => [r.name, r] as const),
  );
  const survivedEndToEnd = clearedGate.filter((s) => {
    const h = holdoutExcess.get(s.name);
    return (h?.excess_bps ?? 0) > 0 && (h?.t_vs_control ?? 0) >= 1.5;
  });

  return (
    <div className="max-w-[1100px]">
      <PageHeading
        title="Methodology"
        lede={
          <>
            What was tested, what survived, and what did not. The negative
            results are the point of this page — a screen that only published
            its wins would not be worth reading.
          </>
        }
      />

      <StatRow>
        <Stat
          label="Events tested"
          value={meta.historical_prints.toLocaleString("en-GB")}
          sub="US prints, 2016–2026"
        />
        <Stat label="Strategies" value={survivors.length} sub="directional rules" />
        <Stat
          label="Survived"
          value={
            <span className={survivedEndToEnd.length ? "text-pos" : "text-neg"}>
              {survivedEndToEnd.length}
            </span>
          }
          sub={
            <>
              {clearedGate.length} cleared train and validate, then failed the
              holdout
            </>
          }
        />
        <Stat
          label="Move model"
          value={mm ? mm.corr_validate.toFixed(2) : DASH}
          sub="out-of-sample correlation"
        />
        <Stat
          label="Universe"
          value={meta.universe.toLocaleString("en-GB")}
          sub="above $500m with options"
        />
      </StatRow>

      <Section
        title="How a strategy has to prove itself"
        description="Four conditions, all required in both the training and validation periods. The holdout is opened once, at the end, and is never used to select."
      >
        <ol className="max-w-3xl space-y-2 text-[13.5px] leading-relaxed">
          <li className="flex gap-3">
            <span className="font-mono text-muted-foreground">1</span>
            <span>Enough trades to say anything at all.</span>
          </li>
          <li className="flex gap-3">
            <span className="font-mono text-muted-foreground">2</span>
            <span>Positive after 20bps of round-trip costs.</span>
          </li>
          <li className="flex gap-3">
            <span className="font-mono text-muted-foreground">3</span>
            <span>Statistically distinguishable from zero.</span>
          </li>
          <li className="flex gap-3">
            <span className="font-mono text-muted-foreground">4</span>
            <span>
              Statistically distinguishable from a{" "}
              <strong className="font-semibold">random pick</strong> in the same
              window, from the same universe.
            </span>
          </li>
        </ol>
        <div className="max-w-3xl pt-4">
          <Notice title="Condition four is the one that matters">
            Most earnings &ldquo;edges&rdquo; are long exposure to a market that
            drifts upward. They sail through the first three conditions and fail
            the fourth. Without the control, four strategies here looked like
            winners; the best posted a t-statistic of 12.5 and would have gone
            straight into production.
          </Notice>
        </div>
      </Section>

      <Section
        title="Directional strategies"
        description="Excess is the strategy's mean return minus the random control's, in basis points, over the same period and pool. Positive numbers in every column are what a real edge looks like."
      >
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full min-w-[820px] border-collapse">
            <thead>
              <tr className="border-b bg-card">
                <th className="label px-3 py-2.5 text-left font-medium">
                  Strategy
                </th>
                {PERIODS.map((p) => (
                  <th
                    key={p}
                    colSpan={2}
                    className="label border-l px-3 py-2.5 text-center font-medium capitalize"
                  >
                    {p}
                  </th>
                ))}
                <th className="label border-l px-3 py-2.5 text-right font-medium">
                  Verdict
                </th>
              </tr>
              <tr className="border-b bg-card">
                <th />
                {PERIODS.map((p) => (
                  <Fragment key={p}>
                    <th className="label border-l px-3 pb-2 text-right font-normal">
                      n
                    </th>
                    <th className="label px-3 pb-2 text-right font-normal">
                      excess
                    </th>
                  </Fragment>
                ))}
                <th className="border-l" />
              </tr>
            </thead>
            <tbody>
              {[...strategies.entries()].map(([name, periods]) => {
                const surv = survivors.find((s) => s.name === name);
                const isBaseline = name.startsWith("baseline");
                return (
                  <tr
                    key={name}
                    className="border-b border-border/60 last:border-0"
                  >
                    <td className="px-3 py-2.5">
                      <span className="font-mono text-[12.5px]">
                        {name.replace(/_/g, " ")}
                      </span>
                      {isBaseline && (
                        <span className="ml-2 rounded-sm border px-1.5 py-px text-[10px] uppercase tracking-wide text-muted-foreground">
                          baseline
                        </span>
                      )}
                    </td>
                    {PERIODS.map((p) => {
                      const r = periods[p];
                      const excess = r?.excess_bps as number | undefined;
                      return (
                        <Fragment key={`${name}-${p}`}>
                          <td className="num border-l px-3 py-2.5 text-right text-muted-foreground">
                            {r ? r.n.toLocaleString("en-GB") : DASH}
                          </td>
                          <td
                            className={cn(
                              "num px-3 py-2.5 text-right",
                              excess == null || isBaseline
                                ? "text-muted-foreground"
                                : excess > 0
                                  ? "text-pos"
                                  : "text-neg",
                            )}
                          >
                            {isBaseline ? DASH : bps(excess ?? null)}
                          </td>
                        </Fragment>
                      );
                    })}
                    <td className="border-l px-3 py-2.5 text-right">
                      <span
                        className={cn(
                          "text-[12px]",
                          surv?.survived
                            ? "text-pos"
                            : surv?.beats_control
                              ? "text-muted-foreground"
                              : "text-muted-foreground",
                        )}
                      >
                        {surv?.survived
                          ? "cleared gate"
                          : surv?.beats_zero && !surv?.beats_control
                            ? "lost to control"
                            : isBaseline
                              ? "reference"
                              : "failed"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="max-w-3xl pt-5">
          <Notice title="Nothing survived end to end">
            One strategy cleared training and validation: buy a beat greater than
            5% and hold twenty days, the classic post-earnings drift. In the
            holdout it returned 159bps against a control of 173bps — it
            underperformed a coin flip. Gross returns looked strong in all three
            periods. The edge over random was never there.
          </Notice>
        </div>
      </Section>

      <Section
        title="Magnitude — what did hold up"
        description="These are not profit-and-loss figures. The ratio is how much a selected name moved relative to a random name in the same window, so 0.54 means it moved roughly half as much."
      >
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full min-w-[560px] border-collapse">
            <thead>
              <tr className="border-b bg-card">
                <th className="label px-3 py-2.5 text-left font-medium">Test</th>
                {PERIODS.map((p) => (
                  <th
                    key={p}
                    className="label px-3 py-2.5 text-right font-medium capitalize"
                  >
                    {p}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...magnitude.entries()].map(([name, periods]) => (
                <tr key={name} className="border-b border-border/60 last:border-0">
                  <td className="px-3 py-2.5 font-mono text-[12.5px]">
                    {name.replace(/_/g, " ")}
                  </td>
                  {PERIODS.map((p) => {
                    const r = periods[p] as { ratio?: number } | undefined;
                    return (
                      <td
                        key={`${name}-${p}`}
                        className="num px-3 py-2.5 text-right font-medium"
                      >
                        {r?.ratio ? `${r.ratio.toFixed(2)}×` : DASH}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="grid max-w-4xl gap-5 pt-5 lg:grid-cols-2">
          <Notice title="Stable across a decade">
            The quietest quartile of past reactors moved 0.54× / 0.58× / 0.54× a
            random name across the three periods; the loudest moved 1.55× /
            1.47× / 1.56×. Three independent samples spanning ten years, and the
            numbers barely move. This is the finding the product is built on.
          </Notice>
          <Notice title="Turned into a usable forecast" tone="muted">
            A linear model on a stock&rsquo;s own reaction history predicts its
            next absolute move with correlation{" "}
            {mm ? `${mm.corr_train.toFixed(2)} / ${mm.corr_validate.toFixed(2)}` : "0.40 / 0.40"}{" "}
            in and out of sample, monotonic across all ten deciles, with a 4.8×
            spread between the top and bottom. It sets position size and the
            distance to every level on the site.
          </Notice>
        </div>
      </Section>

      <Section
        title="Mistakes that were avoided, and one that was not"
        description="Earnings backtests fail in a small number of well-known ways."
      >
        <dl className="max-w-3xl space-y-4 text-[13.5px] leading-relaxed">
          <div>
            <dt className="font-semibold">Announcement timing</dt>
            <dd className="text-muted-foreground">
              A print after Tuesday&rsquo;s close reacts in Wednesday&rsquo;s
              bar; one before Tuesday&rsquo;s open reacts in Tuesday&rsquo;s. Out
              by a day and the backtest measures the reaction it is trying to
              predict. Entry is pinned to the last session whose close precedes
              the announcement, with the session inferred from the announcement
              hour.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">Gap-through stops</dt>
            <dd className="text-muted-foreground">
              A stop-loss does not survive an earnings gap. Fills are taken at
              the bar&rsquo;s open when it opens through the level, not at the
              level. Plans held across a print therefore carry no stop at all —
              position size is the only risk control that functions.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">Survivorship bias</dt>
            <dd className="text-muted-foreground">
              The universe is today&rsquo;s listed names. Companies that
              delisted after a catastrophic print are absent, so realised-move
              statistics are optimistic. This is not fixable on free data, and
              is stated rather than hidden.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">
              Revision momentum is deliberately excluded
            </dt>
            <dd className="text-muted-foreground">
              There are {meta.snapshot_rows.toLocaleString("en-GB")} consensus
              snapshots but only since {meta.snapshot_span.start}, against a
              decade of price history. Including revisions in the beat model
              would mean fitting on a few months and presenting it as a decade.
              They appear on the Expectation panel as context and nowhere in the
              scoring.
            </dd>
          </div>
        </dl>
      </Section>

      <Section title="Data">
        <dl className="grid max-w-3xl gap-x-10 gap-y-3 text-[13px] sm:grid-cols-2">
          <div className="flex justify-between gap-4 border-b border-border/60 py-1.5">
            <dt className="text-muted-foreground">Universe</dt>
            <dd className="num">
              {meta.universe.toLocaleString("en-GB")} US names
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-b border-border/60 py-1.5">
            <dt className="text-muted-foreground">Historical prints</dt>
            <dd className="num">
              {meta.historical_prints.toLocaleString("en-GB")}
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-b border-border/60 py-1.5">
            <dt className="text-muted-foreground">Consensus snapshots</dt>
            <dd className="num">
              {meta.snapshot_rows.toLocaleString("en-GB")}
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-b border-border/60 py-1.5">
            <dt className="text-muted-foreground">Observed live</dt>
            <dd className="num">
              {share(meta.snapshot_observed / meta.snapshot_rows)}
            </dd>
          </div>
          <div className="flex justify-between gap-4 border-b border-border/60 py-1.5">
            <dt className="text-muted-foreground">Training through</dt>
            <dd className="num">{backtest.splits.train_end}</dd>
          </div>
          <div className="flex justify-between gap-4 border-b border-border/60 py-1.5">
            <dt className="text-muted-foreground">Validation through</dt>
            <dd className="num">{backtest.splits.validate_end}</dd>
          </div>
        </dl>

        <p className="max-w-3xl pt-5 text-[12.5px] leading-relaxed text-muted-foreground">
          Everything is built on free, unofficial sources: Nasdaq&rsquo;s
          screener and earnings calendar, and Yahoo Finance for consensus
          estimates, surprise history, prices and option chains. Yahoo&rsquo;s
          own implied-volatility field is unreliable on short-dated contracts,
          so implied move is derived from the at-the-money straddle mid instead.
          A single-analyst consensus is shown but should not be trusted, which
          is why analyst counts are displayed alongside every estimate.
        </p>
      </Section>
    </div>
  );
}
