"""Walk-forward backtest harness.

This is the gate. No signal is allowed into the advisory layer until it has
been through here and survived on data it was not chosen on.

Three periods, split by config:
    train     used to look around and form hypotheses
    validate  used to check them
    holdout   looked at once, at the end, and never tuned against

Every strategy is also compared to a random-entry control drawn from the same
events. A strategy that cannot beat coin-flipping on the same universe in the
same period is not a strategy, it is a description of the market's drift.

Costs are charged explicitly. Earnings trades cross a spread twice, often in a
fast tape, and a signal that only works gross is not a signal.
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config

log = logging.getLogger("pricedin.backtest")

DEFAULT_COST_BPS = 20.0   # round-trip, liquid large cap. Raise for small caps.


# ------------------------------------------------------------------ metrics
@dataclass
class Result:
    name: str
    period: str
    target: str
    n: int
    mean_bps: float
    median_bps: float
    hit_rate: float
    std_bps: float
    t_stat: float
    sharpe: float
    net_mean_bps: float
    worst_bps: float
    best_bps: float
    control_mean_bps: float = float("nan")
    control_hit: float = float("nan")
    excess_bps: float = float("nan")      # strategy minus random control
    t_vs_control: float = float("nan")
    kind: str = "directional"

    def row(self) -> dict:
        return self.__dict__.copy()


def evaluate(returns: pd.Series, name: str, period: str, target: str,
             cost_bps: float = DEFAULT_COST_BPS,
             control: pd.Series | None = None,
             events_per_year: float = 4.0,
             kind: str = "directional") -> Result:
    r = returns.dropna().astype(float)
    n = len(r)
    if n == 0:
        return Result(name, period, target, 0, *([float("nan")] * 9))

    bps = r * 10_000
    mean = float(bps.mean())
    std = float(bps.std(ddof=1)) if n > 1 else float("nan")
    t = float(mean / (std / np.sqrt(n))) if n > 1 and std > 0 else float("nan")

    # Per-trade Sharpe scaled by how often a given name presents a trade.
    sharpe = float((mean / std) * np.sqrt(events_per_year)) if std > 0 else float("nan")

    res = Result(
        name=name, period=period, target=target, n=n,
        mean_bps=mean, median_bps=float(bps.median()),
        hit_rate=float((r > 0).mean()), std_bps=std, t_stat=t, sharpe=sharpe,
        net_mean_bps=mean - cost_bps,
        worst_bps=float(bps.min()), best_bps=float(bps.max()),
        kind=kind,
    )

    # The control is the whole point. A strategy that returns 130bps where a
    # random pick from the same pool in the same window returns 126bps has
    # found the market's drift, not an edge. Welch's t on the difference,
    # because the two samples have different sizes and variances.
    if control is not None and len(control.dropna()) > 1:
        c = control.dropna().astype(float) * 10_000
        res.control_mean_bps = float(c.mean())
        res.control_hit = float((c > 0).mean())
        res.excess_bps = mean - res.control_mean_bps
        v1, v2 = bps.var(ddof=1), c.var(ddof=1)
        se = np.sqrt(v1 / n + v2 / len(c))
        res.t_vs_control = float(res.excess_bps / se) if se > 0 else float("nan")
    return res


# --------------------------------------------------------------- strategies
@dataclass
class Strategy:
    """A strategy picks events and takes a signed position in a target return.

    select : df -> boolean mask of events to trade
    side   : df -> +1 / -1 per selected event (or a constant)
    target : which return column is being harvested
    """
    name: str
    target: str
    select: callable
    side: callable = field(default=lambda df: pd.Series(1.0, index=df.index))
    note: str = ""
    # 'magnitude' strategies predict how big a move will be, not its direction.
    # Their mean is not a P&L and their hit rate is meaningless (an absolute
    # return is almost always positive), so they are judged only against the
    # control and reported separately.
    kind: str = "directional"

    def run(self, df: pd.DataFrame) -> pd.Series:
        mask = self.select(df)
        if mask is None or not mask.any():
            return pd.Series(dtype=float)
        sub = df[mask]
        side = self.side(sub)
        return (sub[self.target] * side).dropna()


def _q(df: pd.DataFrame, col: str, lo: float | None = None,
       hi: float | None = None) -> pd.Series:
    """Mask on a column's cross-sectional quantiles, NaN-safe."""
    s = df[col]
    ok = s.notna()
    m = ok.copy()
    if lo is not None:
        m &= s >= s[ok].quantile(lo)
    if hi is not None:
        m &= s <= s[ok].quantile(hi)
    return m


def build_strategies() -> list[Strategy]:
    liquid = lambda df: df["dollar_vol_20d"].fillna(0) > 5e6   # noqa: E731
    seasoned = lambda df: df["n_prior"] >= config.REACTION_MIN_QUARTERS  # noqa: E731

    return [
        # --- baselines: is there anything here at all? -------------------
        Strategy("baseline_long_all", "ret_1d",
                 lambda df: liquid(df),
                 note="Hold every liquid name through its print. Tests whether "
                      "an earnings risk premium exists at all."),
        Strategy("baseline_long_1d_after", "drift_5d",
                 lambda df: liquid(df),
                 note="Buy after every print, hold 5d. Baseline for drift."),

        # --- post-earnings announcement drift ----------------------------
        Strategy("pead_long_beat", "drift_5d",
                 lambda df: liquid(df) & (df["surprise_pct"] > 5),
                 note="Classic PEAD: buy the beat after the gap, hold 5d."),
        Strategy("pead_long_beat_20d", "drift_20d",
                 lambda df: liquid(df) & (df["surprise_pct"] > 5),
                 note="Same, held 20d."),
        Strategy("pead_short_miss", "drift_5d",
                 lambda df: liquid(df) & (df["surprise_pct"] < -5),
                 lambda df: pd.Series(-1.0, index=df.index),
                 note="Short the miss after the gap, hold 5d."),
        Strategy("pead_longshort", "drift_5d",
                 lambda df: liquid(df) & (df["surprise_pct"].abs() > 5),
                 lambda df: np.sign(df["surprise_pct"]),
                 note="Signed by surprise direction, hold 5d."),
        Strategy("pead_confirmed_by_gap", "drift_5d",
                 lambda df: liquid(df) & (df["surprise_pct"] > 5) & (df["ret_1d"] > 0),
                 note="Only take the drift when the market agreed with the beat "
                      "on the day. Filters the 'beat and fell' trap."),

        # --- run-up: is the news already in the price? --------------------
        Strategy("runup_fade", "ret_1d",
                 lambda df: liquid(df) & seasoned(df) & _q(df, "runup_10d", lo=0.9),
                 lambda df: pd.Series(-1.0, index=df.index),
                 note="Short names in the top decile of 10d run-up into the "
                      "print. The 'already priced in' trade."),
        Strategy("runup_momentum", "ret_1d",
                 lambda df: liquid(df) & seasoned(df) & _q(df, "runup_10d", lo=0.9),
                 note="The opposite: momentum carries through the print."),
        Strategy("runup_weak_long", "ret_1d",
                 lambda df: liquid(df) & seasoned(df) & _q(df, "runup_10d", hi=0.1),
                 note="Long names sold off into the print — low expectations."),

        # --- per-stock reaction history ----------------------------------
        Strategy("serial_beater", "ret_1d",
                 lambda df: liquid(df) & seasoned(df) & (df["beat_rate_8"] >= 0.875),
                 note="Long names that beat in 7+ of the last 8 quarters."),
        Strategy("serial_beater_rewarded", "ret_1d",
                 lambda df: (liquid(df) & seasoned(df) & (df["beat_rate_8"] >= 0.75)
                             & (df["reaction_slope"] > 0) & (df["reac_mean_8"] > 0)),
                 note="Beats often AND historically gets paid for beating. The "
                      "reaction-slope filter is the point of this one."),
        Strategy("serial_beater_punished", "ret_1d",
                 lambda df: (liquid(df) & seasoned(df) & (df["beat_rate_8"] >= 0.75)
                             & (df["reac_mean_8"] < 0)),
                 lambda df: pd.Series(-1.0, index=df.index),
                 note="Beats often but the stock falls anyway. Short it."),

        # --- momentum / relative strength context -------------------------
        Strategy("strong_stock_into_print", "ret_1d",
                 lambda df: liquid(df) & seasoned(df) & _q(df, "rel_strength_60d", lo=0.8),
                 note="Long names outperforming the index into the print."),
        Strategy("weak_stock_into_print", "ret_1d",
                 lambda df: liquid(df) & seasoned(df) & _q(df, "rel_strength_60d", hi=0.2),
                 lambda df: pd.Series(-1.0, index=df.index),
                 note="Short the laggards."),

        # --- magnitude, not direction -------------------------------------
        Strategy("quiet_names_stay_quiet", "abs_ret_1d",
                 lambda df: liquid(df) & seasoned(df) & _q(df, "realised_move_med_8", hi=0.25),
                 note="Not a directional trade. Tests whether a stock's own "
                      "history of small moves predicts another small move — "
                      "the input to any straddle-selling view. Judge on the "
                      "control ratio, not on the mean or hit rate.",
                 kind="magnitude"),
        Strategy("loud_names_stay_loud", "abs_ret_1d",
                 lambda df: liquid(df) & seasoned(df) & _q(df, "realised_move_med_8", lo=0.75),
                 note="The other tail: do historically volatile reactors keep "
                      "reacting big?",
                 kind="magnitude"),
    ]


# ------------------------------------------------------------- walk forward
def split_periods(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    d = df["report_date"]
    return {
        "train": df[d <= config.BACKTEST_TRAIN_END],
        "validate": df[(d > config.BACKTEST_TRAIN_END) & (d <= config.BACKTEST_VALIDATE_END)],
        "holdout": df[d > config.BACKTEST_VALIDATE_END],
    }


def run_backtest(events: pd.DataFrame, cost_bps: float = DEFAULT_COST_BPS,
                 seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    strategies = build_strategies()
    periods = split_periods(events)

    rows = []
    for strat in strategies:
        for pname, pdf in periods.items():
            if pdf.empty:
                continue
            rets = strat.run(pdf)
            if len(rets) == 0:
                continue

            # Control: same number of events, same period, chosen at random
            # from the liquid pool, same target column. For a strategy that
            # selects most of the pool the control converges on the strategy
            # itself, which is the correct answer — it means the selection
            # rule is not selecting anything.
            pool = pdf[pdf["dollar_vol_20d"].fillna(0) > 5e6][strat.target].dropna()
            ctrl = None
            if len(pool) > 1 and len(rets) > 0:
                size = min(len(rets), len(pool))
                idx = rng.choice(len(pool), size=size, replace=False)
                ctrl = pool.iloc[idx]

            res = evaluate(rets, strat.name, pname, strat.target,
                           cost_bps=cost_bps, control=ctrl, kind=strat.kind)
            row = res.row()
            row["note"] = strat.note
            rows.append(row)

    return pd.DataFrame(rows)


def summarise(results: pd.DataFrame, min_n: int = 200, min_t: float = 2.0,
              min_t_control: float = 1.5) -> pd.DataFrame:
    """Which directional strategies held up across train AND validate?

    Four conditions, all required in both periods:
      1. enough trades to say anything
      2. positive after costs
      3. statistically distinguishable from zero
      4. statistically distinguishable from a RANDOM PICK in the same window

    Condition 4 is the one that matters. Most earnings "edges" are long
    exposure to a market that drifts up, and they fail here while sailing
    through the first three.

    The holdout column is reported but never used to select — that is the
    entire point of holding it out.
    """
    if results.empty:
        return results

    directional = results[results["kind"] == "directional"]
    if directional.empty:
        return pd.DataFrame()

    piv = directional.pivot_table(
        index="name", columns="period",
        values=["net_mean_bps", "t_stat", "n", "excess_bps", "t_vs_control"])

    keep = []
    for name in piv.index:
        def g(field, period):
            try:
                v = piv[(field, period)][name]
                return float(v)
            except (KeyError, TypeError, ValueError):
                return float("nan")

        n_tr, n_va = g("n", "train"), g("n", "validate")
        t_tr, t_va = g("t_stat", "train"), g("t_stat", "validate")
        m_tr, m_va = g("net_mean_bps", "train"), g("net_mean_bps", "validate")
        x_tr, x_va = g("excess_bps", "train"), g("excess_bps", "validate")
        c_tr, c_va = g("t_vs_control", "train"), g("t_vs_control", "validate")

        beats_zero = (n_tr >= min_n and n_va >= min_n
                      and m_tr > 0 and m_va > 0
                      and abs(t_tr) >= min_t and abs(t_va) >= min_t)
        beats_control = (x_tr > 0 and x_va > 0
                         and c_tr >= min_t_control and c_va >= min_t_control)

        keep.append({
            "name": name,
            "survived": bool(beats_zero and beats_control),
            "beats_zero": bool(beats_zero),
            "beats_control": bool(beats_control),
            "n_train": n_tr, "n_validate": n_va,
            "net_bps_train": m_tr, "net_bps_validate": m_va,
            "excess_train": x_tr, "excess_validate": x_va,
            "t_ctrl_train": c_tr, "t_ctrl_validate": c_va,
        })

    return (pd.DataFrame(keep)
            .sort_values(["survived", "beats_control", "excess_validate"],
                         ascending=False)
            .reset_index(drop=True))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default=str(config.DATA / "events.pkl"))
    ap.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS)
    ap.add_argument("--show-holdout", action="store_true",
                    help="reveal holdout results (do this once)")
    args = ap.parse_args()

    path = args.events
    events = pd.read_pickle(path) if path.endswith(".pkl") else pd.read_parquet(path)
    log.info("loaded %d events, %s .. %s", len(events),
             events["report_date"].min().date(), events["report_date"].max().date())

    results = run_backtest(events, cost_bps=args.cost_bps)
    results.to_csv(config.RESULTS / "backtest_results.csv", index=False)

    surv = summarise(results)
    surv.to_csv(config.RESULTS / "backtest_survivors.csv", index=False)

    pd.set_option("display.width", 220, "display.max_columns", 50)
    view = results if args.show_holdout else results[results["period"] != "holdout"]

    print("\n=== DIRECTIONAL STRATEGIES ===")
    d = view[view["kind"] == "directional"]
    print(d[["name", "period", "n", "net_mean_bps", "hit_rate", "t_stat",
             "control_mean_bps", "excess_bps", "t_vs_control"]]
          .round(2).to_string(index=False))

    m = view[view["kind"] == "magnitude"]
    if not m.empty:
        m = m.copy()
        m["ratio_vs_control"] = m["mean_bps"] / m["control_mean_bps"]
        print("\n=== MAGNITUDE TESTS (not P&L — read the ratio) ===")
        print(m[["name", "period", "n", "mean_bps", "control_mean_bps",
                 "ratio_vs_control"]].round(2).to_string(index=False))

    print("\n=== SURVIVORS (train + validate only; holdout never consulted) ===")
    print(surv.round(2).to_string(index=False))
    n_surv = int(surv["survived"].sum()) if not surv.empty else 0
    print(f"\n{n_surv} of {len(surv)} directional strategies cleared the gate.")


if __name__ == "__main__":
    main()
