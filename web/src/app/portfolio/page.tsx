import { EquityChart } from "@/components/equity-chart";
import { Notice, PageHeading, Section, Stat, StatRow } from "@/components/primitives";
import { BOOK_COLOURS, portfolio } from "@/lib/data";
import { cn } from "@/lib/utils";
import { DASH, longDate, money, num, pct, share, signed } from "@/lib/format";

export const metadata = { title: "Paper portfolio" };

const ROLE_LABEL: Record<string, string> = {
  control: "Control",
  benchmark: "Benchmark",
};

export default function PortfolioPage() {
  const { books, curves, blotter, open, period, settings } = portfolio;
  const control = books.find((b) => b.role === "control");
  const bench = books.find((b) => b.role === "benchmark");
  const strategies = books.filter((b) => b.role === "strategy");
  const best = [...strategies].sort(
    (a, b) => (b.return_pct ?? -Infinity) - (a.return_pct ?? -Infinity),
  )[0];

  const strategyCosts = strategies.reduce((s, b) => s + (b.costs_paid ?? 0), 0);
  const worst = [...strategies].sort(
    (a, b) => (b.costs_paid ?? 0) - (a.costs_paid ?? 0),
  )[0];

  return (
    <div>
      <PageHeading
        title="Paper portfolio"
        lede={
          <>
            Six books trade the same events with the same sizing and the same
            costs. Two of them exist only as yardsticks, because a book that is
            up has proven nothing until it beats them.
          </>
        }
      />

      <StatRow>
        <Stat
          label="Best strategy"
          value={
            <span className={cn((best?.return_pct ?? 0) > 0 ? "text-pos" : "text-neg")}>
              {signed(best?.return_pct, 1)}
            </span>
          }
          sub={best?.book.replace(/_/g, " ")}
        />
        <Stat
          label="Random control"
          value={
            <span className={cn((control?.return_pct ?? 0) > 0 ? "text-pos" : "text-neg")}>
              {signed(control?.return_pct, 1)}
            </span>
          }
          sub="same pool, chosen blind"
        />
        <Stat
          label="SPY held"
          value={
            <span className={cn((bench?.return_pct ?? 0) > 0 ? "text-pos" : "text-neg")}>
              {signed(bench?.return_pct, 1)}
            </span>
          }
          sub="bought once, never traded"
        />
        <Stat
          label="Costs paid"
          value={money(strategyCosts)}
          sub={`across ${strategies.length} strategy books, each starting on ${money(settings.starting_cash)}`}
        />
        <Stat
          label="Open now"
          value={open.length}
          sub={`max ${settings.max_concurrent} concurrent`}
        />
      </StatRow>

      <div className="pt-7">
        <EquityChart curves={curves} startingCash={settings.starting_cash} />
      </div>

      <Section
        title="Books"
        description={`${longDate(period.start)} to ${longDate(period.end)}. Every rule was fixed on data before the holdout period, so this replay is genuinely out of sample.`}
      >
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full min-w-[860px] border-collapse">
            <thead>
              <tr className="border-b bg-card">
                {[
                  "Book",
                  "Trades",
                  "Hit rate",
                  "Avg / trade",
                  "Costs",
                  "Net P&L",
                  "Return",
                  "Sharpe",
                  "Max DD",
                ].map((h, i) => (
                  <th
                    key={h}
                    className={cn(
                      "label px-3 py-2.5 font-medium",
                      i === 0 ? "text-left" : "text-right",
                    )}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {books.map((b) => (
                <tr
                  key={b.book}
                  className={cn(
                    "border-b border-border/60 last:border-0",
                    b.role !== "strategy" && "bg-muted/35",
                  )}
                >
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <span
                        className="size-2 shrink-0 rounded-[2px]"
                        style={{ background: BOOK_COLOURS[b.book] }}
                        aria-hidden
                      />
                      <span className="text-[13px] font-medium">
                        {b.book.replace(/_/g, " ")}
                      </span>
                      {ROLE_LABEL[b.role] && (
                        <span className="rounded-sm border px-1.5 py-px text-[10px] uppercase tracking-wide text-muted-foreground">
                          {ROLE_LABEL[b.role]}
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 max-w-[420px] text-[11.5px] leading-snug text-muted-foreground">
                      {b.description}
                    </p>
                  </td>
                  <td className="num px-3 py-2.5 text-right">
                    {b.trades.toLocaleString("en-GB")}
                  </td>
                  <td className="num px-3 py-2.5 text-right">
                    {share(b.hit_rate)}
                  </td>
                  <td className="num px-3 py-2.5 text-right">
                    {num(b.avg_ret_pct, 3, "%")}
                  </td>
                  <td className="num px-3 py-2.5 text-right text-muted-foreground">
                    {money(b.costs_paid)}
                  </td>
                  <td
                    className={cn(
                      "num px-3 py-2.5 text-right",
                      (b.net_pnl ?? 0) > 0 ? "text-pos" : "text-neg",
                    )}
                  >
                    {money(b.net_pnl)}
                  </td>
                  <td
                    className={cn(
                      "num px-3 py-2.5 text-right font-medium",
                      (b.return_pct ?? 0) > 0 ? "text-pos" : "text-neg",
                    )}
                  >
                    {signed(b.return_pct, 1)}
                  </td>
                  <td className="num px-3 py-2.5 text-right">
                    {num(b.sharpe, 2)}
                  </td>
                  <td className="num px-3 py-2.5 text-right text-muted-foreground">
                    {num(b.max_dd_pct, 1, "%")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="grid gap-5 pt-6 lg:grid-cols-2">
          <Notice title="Turnover is what kills these books">
            The <span className="font-mono">{worst?.book.replace(/_/g, " ")}</span>{" "}
            book paid {money(worst?.costs_paid)} in costs on{" "}
            {money(settings.starting_cash)} of capital. Run the same replay with
            costs set to zero and it returns roughly +48% against the
            control&rsquo;s +13% — an eighty-point swing that lives entirely in
            the spread. At {settings.cost_bps + 2 * settings.slippage_bps}bps a
            round trip, a signal has to be very good before it survives being
            traded this often.
          </Notice>
          <Notice title="Where the gross edge comes from" tone="muted">
            The hit rate is 48%, the same coin flip as the control. What differs
            is that positions are sized by the validated move model — small in
            volatile names, large in quiet ones. The picking does not work; the
            sizing does. That is one path over one period and has not been
            through the survivor gate, so treat it as a lead worth testing
            rather than a result.
          </Notice>
        </div>
      </Section>

      {open.length > 0 && (
        <Section title="Open positions">
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full min-w-[560px] border-collapse">
              <thead>
                <tr className="border-b bg-card">
                  {["Symbol", "Book", "Side", "Opened", "Entry", "Quantity"].map(
                    (h, i) => (
                      <th
                        key={h}
                        className={cn(
                          "label px-3 py-2.5 font-medium",
                          i > 2 ? "text-right" : "text-left",
                        )}
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {open.map((p, i) => (
                  <tr key={i} className="border-b border-border/60 last:border-0">
                    <td className="px-3 py-2 text-[13px] font-semibold">
                      {p.symbol}
                    </td>
                    <td className="px-3 py-2 text-[12.5px] text-muted-foreground">
                      {p.book.replace(/_/g, " ")}
                    </td>
                    <td className="px-3 py-2 text-[12.5px]">{p.side}</td>
                    <td className="num px-3 py-2 text-right">{p.entry_date}</td>
                    <td className="num px-3 py-2 text-right">
                      {money(p.entry_price, 2)}
                    </td>
                    <td className="num px-3 py-2 text-right text-muted-foreground">
                      {num(p.qty, 1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      <Section
        title="Recent closed trades"
        description="Exit reason distinguishes a stop that worked from one the price gapped straight through."
      >
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full min-w-[760px] border-collapse">
            <thead>
              <tr className="border-b bg-card">
                {[
                  "Exit",
                  "Symbol",
                  "Book",
                  "Side",
                  "Entry",
                  "Exit px",
                  "Reason",
                  "P&L",
                  "Return",
                ].map((h, i) => (
                  <th
                    key={h}
                    className={cn(
                      "label px-3 py-2.5 font-medium",
                      i > 3 ? "text-right" : "text-left",
                    )}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {blotter.slice(0, 25).map((t, i) => (
                <tr key={i} className="border-b border-border/60 last:border-0">
                  <td className="num px-3 py-2">{t.exit_date}</td>
                  <td className="px-3 py-2 text-[13px] font-semibold">
                    {t.symbol}
                  </td>
                  <td className="px-3 py-2 text-[12.5px] text-muted-foreground">
                    {t.book.replace(/_/g, " ")}
                  </td>
                  <td className="px-3 py-2 text-[12.5px]">{t.side}</td>
                  <td className="num px-3 py-2 text-right">
                    {money(t.entry_price, 2)}
                  </td>
                  <td className="num px-3 py-2 text-right">
                    {money(t.exit_price, 2)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span
                      className={cn(
                        "rounded-sm border px-1.5 py-px text-[10.5px]",
                        t.exit_reason.startsWith("gap")
                          ? "border-neg/35 text-neg"
                          : "border-border text-muted-foreground",
                      )}
                    >
                      {t.exit_reason}
                    </span>
                  </td>
                  <td
                    className={cn(
                      "num px-3 py-2 text-right",
                      t.pnl > 0 ? "text-pos" : "text-neg",
                    )}
                  >
                    {money(t.pnl)}
                  </td>
                  <td
                    className={cn(
                      "num px-3 py-2 text-right",
                      t.ret_pct > 0 ? "text-pos" : "text-neg",
                    )}
                  >
                    {signed(t.ret_pct, 2)}
                  </td>
                </tr>
              ))}
              {blotter.length === 0 && (
                <tr>
                  <td
                    colSpan={9}
                    className="px-3 py-14 text-center text-[13px] text-muted-foreground"
                  >
                    No closed trades yet. {DASH}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Section>

      <p className="pt-8 text-[11.5px] leading-relaxed text-muted-foreground">
        {money(settings.starting_cash)} per book · maximum{" "}
        {settings.max_concurrent} concurrent positions · {settings.cost_bps}bps
        round-trip cost plus {settings.slippage_bps}bps slippage per side. Stops
        are simulated against the bar&rsquo;s open when the price gaps through
        the level, so an earnings gap costs what it really costs rather than the
        stop price. Not investment advice.
      </p>
    </div>
  );
}
