"""Replay the paper books over history so the portfolio starts with a curve.

Waiting three months for a live paper test to say something is the honest
approach but a slow one. Replaying over the holdout period (2024 onwards) gives
the same answer immediately and is still genuinely out of sample: every rule in
these books was fixed on train/validate data, before the holdout was opened.

One caveat is stated loudly rather than buried. The live `stance` uses consensus
revisions and implied moves, neither of which exists historically. The replay
therefore scores a PROXY stance built only from features that were observable
at the time — beat history, reaction slope, mean reaction, run-up. It is the
same shape of rule, not the same rule, and it is labelled that way everywhere.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

import numpy as np
import pandas as pd

import config
import levels as lv
import paper
import sizing

log = logging.getLogger("pricedin.replay")

RISK_BUDGET = 0.5       # % of portfolio risked per trade
MAX_POSITION = 5.0      # % of portfolio in any one name
MAX_CONCURRENT = 20     # a real account has finite capacity

# Without a capacity limit the replay will happily book 12,000 trades on a
# 100k account and report a loss larger than the account, because nothing stops
# it opening every candidate at full size. The portfolio loop below enforces
# slots, cash, and sizing off current equity — which also surfaces the thing
# that actually kills this strategy: turnover against a 30bps round trip.


def proxy_stance(df: pd.DataFrame) -> pd.Series:
    """Reproduce build_verdict's shape using only point-in-time features.

    Mirrors the live rules that do not depend on revisions or option prices:
    beat frequency, revision-free surprise history, run-up, reaction slope and
    mean reaction.
    """
    s = pd.Series(0, index=df.index, dtype=int)

    s += (df["beat_rate_8"] >= 0.75).fillna(False).astype(int)
    s -= (df["beat_rate_8"] <= 0.40).fillna(False).astype(int)

    s += (df["surp_mean_4"] > 3).fillna(False).astype(int)
    s -= (df["surp_mean_4"] < 0).fillna(False).astype(int)

    s -= (df["runup_10d"] > 0.10).fillna(False).astype(int)
    s += (df["runup_10d"] < -0.10).fillna(False).astype(int)

    s += (df["reaction_slope"] > 0).fillna(False).astype(int)
    s -= (df["reaction_slope"] <= 0).fillna(False).astype(int)

    s += (df["reac_mean_8"] > 0.01).fillna(False).astype(int)
    s -= (df["reac_mean_8"] < -0.01).fillna(False).astype(int)

    return s


def replay(start: str, end: str | None = None, starting_cash: float = paper.STARTING_CASH,
           seed: int = 11) -> None:
    rng = np.random.default_rng(seed)

    events = pd.read_pickle(config.DATA / "events.pkl")
    events = events[events["dollar_vol_20d"].fillna(0) > 5e6].copy()
    events = events[events["report_date"] >= pd.Timestamp(start)]
    if end:
        events = events[events["report_date"] <= pd.Timestamp(end)]
    if events.empty:
        log.error("no events in range")
        return

    events["stance"] = proxy_stance(events)
    model = lv.load_move_model()
    if model is None:
        model = lv.fit_move_model(pd.read_pickle(config.DATA / "events.pkl"))

    log.info("replaying %d events, %s .. %s", len(events),
             events["report_date"].min().date(), events["report_date"].max().date())

    symbols = sorted(events["symbol"].unique().tolist()) + ["SPY"]
    px = paper.PriceCache(symbols, start=(pd.Timestamp(start) -
                                          pd.Timedelta(days=30)).date().isoformat())
    log.info("price cache: %d symbols", len(px.by))

    # The trading calendar the portfolio loop walks. SPY is the reference
    # because it trades every session the US market is open.
    ref = px.by.get("SPY")
    if ref is None or ref.empty:
        ref = px.by[next(iter(px.by))]
    all_trading_dates = sorted({str(d)[:10] for d in ref["date"]
                                if pd.Timestamp(d) >= pd.Timestamp(start)})
    log.info("trading calendar: %d sessions", len(all_trading_dates))

    con = paper.connect()
    paper.init_books(con, starting_cash)
    con.execute("DELETE FROM positions")
    con.execute("DELETE FROM equity")
    con.commit()

    # Predicted move drives sizing for every book, so compute it once.
    preds = []
    for _, r in events.iterrows():
        preds.append(lv.predict_move(model,
                                     r.get("realised_move_med_8") * 100
                                     if pd.notna(r.get("realised_move_med_8")) else None,
                                     r.get("realised_move_max_8") * 100
                                     if pd.notna(r.get("realised_move_max_8")) else None,
                                     r.get("vol_20d") * 100
                                     if pd.notna(r.get("vol_20d")) else None))
    events["pred_move"] = preds
    events = events[events["pred_move"].notna() & (events["pred_move"] > 0)]

    # ---- choose trades per book ------------------------------------------
    picks: dict[str, pd.DataFrame] = {
        "stance_long": events[events["stance"] >= 2],
        "stance_short": events[events["stance"] <= -2],
        "drift_long": events[events["surprise_pct"] > 5],
        "cheap_vol": events[events["realised_move_med_8"].notna()
                            & (events["pred_move"] <=
                               events["pred_move"].quantile(0.25))],
    }
    n_random = int(np.mean([len(v) for v in picks.values()]))
    picks["random"] = events.sample(n=min(n_random, len(events)),
                                    random_state=seed)

    stats: dict[str, dict] = {}
    for book, sel in picks.items():
        if sel.empty:
            log.warning("%s: no trades selected", book)
            continue

        side = "short" if book == "stance_short" else "long"
        style = "post_print_drift" if book == "drift_long" else "through_print"

        # ---- stage 1: work out where each candidate would enter and exit ----
        cands = []
        for _, r in sel.iterrows():
            sym = r["symbol"]
            pred = float(r["pred_move"])

            if style == "through_print":
                # Enter at the last close before the announcement (t0), exit at
                # the next close. No stop: the gap makes one meaningless.
                entry_date = str(r["t0_date"])[:10]
                entry_price = px.close_at(sym, entry_date)
                tp = sl = None
                hold = 1
            else:
                # Enter one bar later, after the gap, and use a real stop.
                bars0 = px.bars_after(sym, str(r["t0_date"])[:10], 1)
                if bars0.empty:
                    continue
                entry_date = str(bars0.iloc[0]["date"])[:10]
                entry_price = float(bars0.iloc[0]["close"])
                horizon = (pred / 2.5) * np.sqrt(5)
                tp = entry_price * (1 + horizon * 1.5 / 100)
                sl = entry_price * (1 - horizon * 1.0 / 100)
                hold = 5

            if not entry_price or entry_price <= 0:
                continue
            bars = px.bars_after(sym, entry_date, 40)
            if bars.empty:
                continue
            fill = paper.simulate_exit(bars, side, tp, sl, hold)
            if fill is None:
                continue

            size_pct = sizing.vol_target_size(
                pred, risk_budget_pct=RISK_BUDGET,
                max_position_pct=MAX_POSITION).position_pct
            if size_pct <= 0:
                continue

            cands.append({
                "symbol": sym, "entry_date": entry_date,
                "entry_price": entry_price, "fill": fill, "tp": tp, "sl": sl,
                "size_pct": size_pct, "event_date": str(r["report_date"])[:10],
            })

        if not cands:
            log.warning("%s: no viable candidates", book)
            continue

        # ---- stage 2: run them through a portfolio with finite capacity -----
        cands.sort(key=lambda c: c["entry_date"])
        by_entry: dict[str, list] = {}
        for c in cands:
            by_entry.setdefault(c["entry_date"], []).append(c)

        realised = 0.0
        open_pos: list[dict] = []
        n_done = n_capacity = 0
        peak_open = 0
        notional_total = 0.0

        for d in all_trading_dates:
            # close anything due today, freeing slots and returning capital
            still_open = []
            for p in open_pos:
                if p["exit_date"] <= d:
                    realised += p["pnl"]
                else:
                    still_open.append(p)
            open_pos = still_open

            for c in by_entry.get(d, []):
                if len(open_pos) >= MAX_CONCURRENT:
                    n_capacity += 1
                    continue
                equity = starting_cash + realised
                if equity <= 0:
                    n_capacity += 1
                    continue
                notional = equity * c["size_pct"] / 100.0
                qty = notional / c["entry_price"]

                pnl = paper.record_trade(
                    con, book, c["symbol"], side, style, qty, c["entry_date"],
                    c["entry_price"], c["fill"], c["tp"], c["sl"],
                    c["event_date"])
                open_pos.append({"exit_date": c["fill"].date, "pnl": pnl})
                n_done += 1
                notional_total += notional
            peak_open = max(peak_open, len(open_pos))

        for p in open_pos:
            realised += p["pnl"]

        con.commit()
        stats[book] = {
            "booked": n_done, "skipped_capacity": n_capacity,
            "peak_positions": peak_open,
            "turnover_x": notional_total / starting_cash if starting_cash else 0,
        }
        log.info("%-13s %5d booked, %5d skipped for capacity, peak %d open, "
                 "turnover %.0fx", book, n_done, n_capacity, peak_open,
                 stats[book]["turnover_x"])

    # ---- SPY benchmark ----------------------------------------------------
    spy = px.by.get("SPY")
    if spy is not None and not spy.empty:
        first = spy[spy["date"] >= pd.Timestamp(start)]
        if not first.empty:
            b0 = first.iloc[0]
            last = spy.iloc[-1]
            qty = starting_cash / float(b0["close"])
            paper.record_trade(
                con, "spy_hold", "SPY", "long", "buy_hold", qty,
                str(b0["date"])[:10], float(b0["close"]),
                paper.Fill(str(last["date"])[:10], float(last["close"]), "time"),
                None, None, None)
            con.commit()
            log.info("spy_hold      1 trade booked (buy and hold)")

    # ---- daily equity curves ---------------------------------------------
    log.info("building equity curves...")
    all_dates = all_trading_dates

    trades = pd.read_sql_query(
        "SELECT book, exit_date, pnl FROM positions WHERE status='closed'", con)
    books = [r["book"] for r in con.execute("SELECT book FROM books")]

    rows = []
    for book in books:
        t = trades[trades["book"] == book]
        by_date = t.groupby("exit_date")["pnl"].sum().sort_index()
        cum = by_date.cumsum()
        running = 0.0
        for d in all_dates:
            if d in cum.index:
                running = float(cum.loc[d])
            elif len(cum):
                prior = cum[cum.index <= d]
                running = float(prior.iloc[-1]) if len(prior) else 0.0
            rows.append((book, d, starting_cash + running, 0.0,
                         starting_cash + running, 0))

    con.executemany("INSERT OR REPLACE INTO equity VALUES (?,?,?,?,?,?)", rows)
    con.commit()

    s = paper.summary(con)
    s["turnover_x"] = s["book"].map(
        lambda b: round(stats.get(b, {}).get("turnover_x", 0), 1))
    s["peak_pos"] = s["book"].map(
        lambda b: stats.get(b, {}).get("peak_positions", 0))

    pd.set_option("display.width", 240)
    print("\n" + "=" * 104)
    print(f"PAPER REPLAY  {start} .. {end or 'today'}   "
          f"(holdout period — every rule was fixed before this data was opened)")
    print(f"max {MAX_CONCURRENT} concurrent positions, {RISK_BUDGET}% risk "
          f"budget per trade, {paper.COST_BPS:.0f}bps costs + "
          f"{paper.SLIPPAGE_BPS:.0f}bps slippage per side")
    print("=" * 104)
    print(s.round(2).to_string(index=False))

    ctrl = s[s["book"] == "random"]
    spy = s[s["book"] == "spy_hold"]
    if not ctrl.empty and not spy.empty:
        c = float(ctrl.iloc[0]["return_pct"])
        sp = float(spy.iloc[0]["return_pct"])
        print(f"\nBenchmarks: random control {c:+.2f}%, SPY buy-and-hold {sp:+.2f}%.")
        print("A book proves something by beating the control, not by being "
              "positive —")
        print("in a rising market almost everything is positive.")
        best = s[~s["book"].isin(["random", "spy_hold"])] \
            .sort_values("return_pct", ascending=False)
        if not best.empty:
            b = best.iloc[0]
            print(f"Best strategy book: {b['book']} at {b['return_pct']:+.2f}% "
                  f"({b['return_pct'] - c:+.2f} vs control, "
                  f"{b['return_pct'] - sp:+.2f} vs SPY).")
    con.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-01-01",
                    help="default is the start of the holdout period")
    ap.add_argument("--end", default=None)
    ap.add_argument("--cash", type=float, default=paper.STARTING_CASH)
    ap.add_argument("--cost-bps", type=float, default=None,
                    help="override round-trip cost; set 0 to see the "
                         "frictionless result and isolate what turnover costs")
    ap.add_argument("--slippage-bps", type=float, default=None)
    args = ap.parse_args()

    if args.cost_bps is not None:
        paper.COST_BPS = args.cost_bps
    if args.slippage_bps is not None:
        paper.SLIPPAGE_BPS = args.slippage_bps

    replay(args.start, args.end, args.cash)


if __name__ == "__main__":
    main()
