import { EarningsTable } from "@/components/earnings-table";
import { Notice, PageHeading, Stat, StatRow } from "@/components/primitives";
import { events, meta, backtest } from "@/lib/data";
import { longDate } from "@/lib/format";

export default function CalendarPage() {
  const withImplied = events.filter((e) => e.implied_move_pct != null).length;
  const mispriced = events.filter(
    (e) => (e.implied_vs_realised ?? 0) >= 1.3,
  ).length;
  const thisWeek = events.filter((e) => e.days_to_report <= 7).length;
  const mm = backtest.move_model;

  return (
    <div>
      <PageHeading
        title="Earnings calendar"
        lede={
          <>
            Every tracked US company reporting in the next 21 days, with what the
            options market is charging for the event set against what the stock
            has actually done on its last eight prints.
          </>
        }
      />

      <StatRow>
        <Stat label="Reporting" value={events.length} sub="next 21 days" />
        <Stat label="Within a week" value={thisWeek} sub="sooner decisions" />
        <Stat
          label="Option coverage"
          value={withImplied}
          sub="have a chain spanning the print"
        />
        <Stat
          label="Expensive events"
          value={mispriced}
          sub="implied ≥ 1.3× realised"
        />
        <Stat
          label="Consensus history"
          value={meta.snapshot_rows.toLocaleString("en-GB")}
          sub={`snapshots since ${meta.snapshot_span.start ?? "—"}`}
        />
      </StatRow>

      <div className="pt-6">
        <EarningsTable events={events} />
      </div>

      <div className="grid gap-5 pt-10 lg:grid-cols-2">
        <Notice title="The reading is not a recommendation">
          Fifteen directional strategies were tested over 83,366 prints against a
          random-entry control. None beat it across training, validation and
          holdout. The Reading column summarises the panels transparently — it is
          context, not a signal, and the{" "}
          <a href="/methodology" className="underline underline-offset-2">
            methodology
          </a>{" "}
          sets out exactly how each one failed.
        </Notice>

        <Notice title="What does hold up" tone="muted">
          Move <em>size</em> is predictable where direction is not. A stock&rsquo;s
          own reaction history forecasts its next reaction with correlation{" "}
          {mm ? mm.corr_validate.toFixed(2) : "0.40"} out of sample, and the
          quietest quartile of names goes on to move roughly half as much as a
          random pick. That relationship is what the Implied ÷ Realised column
          rests on.
        </Notice>
      </div>

      <p className="pt-8 text-[11.5px] text-muted-foreground">
        Data generated {longDate(meta.generated.slice(0, 10))}. Consensus
        snapshots run from {meta.snapshot_span.start} to{" "}
        {meta.snapshot_span.end}, of which{" "}
        {meta.snapshot_observed.toLocaleString("en-GB")} were observed live and
        the remainder reconstructed from a 90-day lookback on first contact with
        each ticker.
      </p>
    </div>
  );
}
