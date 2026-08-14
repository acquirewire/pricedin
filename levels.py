"""Entry, take-profit and stop-loss geometry.

Two things have to stay separate here, because only one of them has evidence:

  SIZE of the move    predictable. A linear model on the stock's own reaction
                      history scores corr 0.40 / 0.40 / 0.42 across train /
                      validate / holdout, monotonic across all ten deciles,
                      with a 4.8x spread between the top and bottom decile.

  DIRECTION of it     not predictable. Fifteen strategies, zero survivors.

So every level in this module is derived from predicted move size, and the
expected value of the resulting trade is computed with an honest directional
hit rate rather than an optimistic one. When that expectancy is negative the
plan says so instead of dressing it up.

The other thing this module refuses to pretend about: a stop-loss does not work
through an earnings print. The stock gaps at the open and fills you far past
your level — a 5% stop on a name that gaps 12% is a 12% loss. For a trade held
through the announcement the position size is the only risk control that
actually functions, so `through_print` plans carry no stop and say why.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

import config
import sizing

log = logging.getLogger("pricedin.levels")

MOVE_MODEL = config.RESULTS / "move_model.json"

FEATS = ["realised_move_med_8", "realised_move_max_8", "vol_20d"]

# Round-trip cost assumption, matching backtest.py.
COST_BPS = 20.0


# ---------------------------------------------------------------- the model
def fit_move_model(events: pd.DataFrame) -> dict:
    """Least squares on train only. Returns coefficients + honest diagnostics.

    Also fits a calibration factor from the validate period, because realised
    volatility drifts: the raw model under-predicted by ~9% out of sample, and
    under-predicting move size is the dangerous direction for a stop.
    """
    ev = events[events["dollar_vol_20d"].fillna(0) > 5e6]
    tr = ev[ev["report_date"] <= config.BACKTEST_TRAIN_END]
    va = ev[(ev["report_date"] > config.BACKTEST_TRAIN_END) &
            (ev["report_date"] <= config.BACKTEST_VALIDATE_END)]

    d = tr[FEATS + ["abs_ret_1d"]].dropna()
    if len(d) < 500:
        raise RuntimeError("not enough training rows to fit the move model")

    X = d[FEATS].to_numpy(float)
    y = d["abs_ret_1d"].to_numpy(float)
    A = np.column_stack([np.ones(len(X)), X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)

    def predict(df):
        s = df[FEATS].dropna()
        P = np.column_stack([np.ones(len(s)), s.to_numpy(float)]) @ coef
        return s.index, P

    idx, pv = predict(va)
    actual = va.loc[idx, "abs_ret_1d"].to_numpy(float)
    calib = float(actual.mean() / pv.mean()) if pv.mean() > 0 else 1.0

    corr_tr = float(np.corrcoef(A @ coef, y)[0, 1])
    corr_va = float(np.corrcoef(pv, actual)[0, 1])

    # Empirical directional odds, by predicted-move decile, from train+validate.
    # This is what stops the EV calculation from assuming a coin flip is a coin
    # flip weighted in our favour.
    both = pd.concat([tr, va])
    bi, bp = predict(both)
    b = both.loc[bi].copy()
    b["pred"] = bp * calib
    b = b.dropna(subset=["ret_1d"])
    b["dec"] = pd.qcut(b["pred"], 10, labels=False, duplicates="drop")

    odds = {}
    for dec, g in b.groupby("dec"):
        up = g[g["ret_1d"] > 0]["ret_1d"]
        dn = g[g["ret_1d"] <= 0]["ret_1d"]
        if len(g) < 100:
            continue
        odds[int(dec)] = {
            "p_up": float((g["ret_1d"] > 0).mean()),
            "mean_up": float(up.mean()) if len(up) else 0.0,
            "mean_down": float(dn.mean()) if len(dn) else 0.0,
            "n": int(len(g)),
        }

    return {
        "coef": [float(c) for c in coef],
        "feats": FEATS,
        "calibration": calib,
        "corr_train": corr_tr,
        "corr_validate": corr_va,
        "n_train": int(len(d)),
        "odds_by_decile": odds,
        "decile_edges": [float(x) for x in
                         np.quantile(b["pred"].dropna(), np.linspace(0, 1, 11))],
        "fitted_through": config.BACKTEST_VALIDATE_END,
    }


def load_move_model() -> dict | None:
    if MOVE_MODEL.exists():
        return json.loads(MOVE_MODEL.read_text())
    return None


def predict_move(model: dict, realised_med: float | None,
                 realised_max: float | None, vol20: float | None,
                 implied: float | None = None) -> float | None:
    """Predicted absolute one-day move, in percent.

    If the options market has a view, take the larger of the two. The model is
    fitted on history and cannot know about a pending lawsuit or a guidance
    pre-announcement; the straddle can.
    """
    vals = [realised_med, realised_max, vol20]
    if any(v is None or not np.isfinite(v) for v in vals):
        model_pred = None
    else:
        c = model["coef"]
        # Model was fitted on fractions; inputs here arrive as percentages.
        x = [realised_med / 100.0, realised_max / 100.0, vol20 / 100.0]
        model_pred = (c[0] + sum(ci * xi for ci, xi in zip(c[1:], x))) * 100.0
        model_pred *= model.get("calibration", 1.0)

    if model_pred is None and implied is None:
        return None
    if model_pred is None:
        return implied
    if implied is None or not np.isfinite(implied):
        return model_pred
    return max(model_pred, implied)


def _decile(model: dict, pred_pct: float) -> int:
    edges = model.get("decile_edges")
    if not edges:
        return 5
    return int(np.clip(np.searchsorted(edges, pred_pct / 100.0, "right") - 1, 0, 9))


# ------------------------------------------------------------------- plans
@dataclass
class TradePlan:
    symbol: str
    style: str                    # through_print | post_print_drift | premium_sell
    direction: str                # long | short | none
    tradeable: bool
    predicted_move_pct: float | None = None
    implied_move_pct: float | None = None
    entry_rule: str = ""
    entry_ref: float | None = None
    tp_price: float | None = None
    sl_price: float | None = None
    tp_pct: float | None = None
    sl_pct: float | None = None
    hold_days: int | None = None
    size_pct: float | None = None
    ev_bps: float | None = None
    p_win: float | None = None
    risk_note: str = ""
    reasons: list = field(default_factory=list)

    def dict(self):
        return asdict(self)


def _ev_bps(model: dict, pred_pct: float, direction: str,
            tp_pct: float | None, sl_pct: float | None,
            cost_bps: float = COST_BPS) -> tuple[float, float]:
    """Expected value in bps, using empirical directional odds.

    Returns (ev_bps, p_win). No optimism is applied: p_up comes from what
    actually happened to names with a similar predicted move.
    """
    o = model.get("odds_by_decile", {}).get(str(_decile(model, pred_pct))) \
        or model.get("odds_by_decile", {}).get(_decile(model, pred_pct))
    if not o:
        p_up, mean_up, mean_dn = 0.5, pred_pct / 100.0, -pred_pct / 100.0
    else:
        p_up, mean_up, mean_dn = o["p_up"], o["mean_up"], o["mean_down"]

    if direction == "long":
        p_win, win, loss = p_up, mean_up, mean_dn
    else:
        p_win, win, loss = 1 - p_up, -mean_dn, -mean_up

    # Cap the outcomes at the exit levels where levels actually bind.
    if tp_pct:
        win = min(win, tp_pct / 100.0)
    if sl_pct:
        loss = max(loss, -abs(sl_pct) / 100.0)

    ev = (p_win * win + (1 - p_win) * loss) * 10_000 - cost_bps
    return float(ev), float(p_win)


def plan_through_print(model: dict, row: dict,
                       direction: str = "long",
                       risk_budget_pct: float = config.DEFAULT_RISK_BUDGET_PCT
                       ) -> TradePlan:
    """Hold across the announcement. Size is the risk control; stops are not."""
    sym = row.get("symbol", "?")
    price = row.get("price") or row.get("spot")
    pred = predict_move(model, row.get("realised_move_med_8"),
                        row.get("realised_move_max_8"), row.get("vol_20d"),
                        row.get("implied_move_pct"))

    if not price or not pred:
        return TradePlan(sym, "through_print", "none", False,
                         reasons=["no price or no move estimate available"])

    session = (row.get("session") or "unknown").lower()
    when = ("the close on the session before the report"
            if session == "pre" else "the close on report day")
    verb = "Buy" if direction == "long" else "Short"

    # Informational only: the exit is time-based, at the reaction close. This
    # is where the move is expected to land, not an order resting in the book.
    tp_pct = pred * 1.0
    tp = price * (1 + tp_pct / 100) if direction == "long" else price * (1 - tp_pct / 100)

    s = sizing.vol_target_size(pred, risk_budget_pct=risk_budget_pct)
    ev, p_win = _ev_bps(model, pred, direction, None, None)

    reasons = [
        f"predicted move {pred:.1f}% (model corr {model['corr_validate']:.2f} "
        f"out of sample)",
        f"empirical p({direction[0:4]} wins) at this move size: {p_win:.0%}",
    ]
    if row.get("implied_move_pct"):
        reasons.append(f"options imply {row['implied_move_pct']:.1f}%")

    return TradePlan(
        symbol=sym, style="through_print", direction=direction,
        tradeable=ev > 0,
        predicted_move_pct=round(pred, 2),
        implied_move_pct=row.get("implied_move_pct"),
        entry_rule=f"{verb} at {when} ({row.get('report_date', '')}, {session}). "
                   f"Exit at the following close — the exit is time-based, not "
                   f"level-based.",
        entry_ref=round(float(price), 2),
        tp_price=round(tp, 2), tp_pct=round(tp_pct, 2),
        sl_price=None, sl_pct=None,
        hold_days=1,
        size_pct=s.position_pct,
        ev_bps=round(ev, 1), p_win=round(p_win, 3),
        risk_note=(
            "NO STOP-LOSS. The price gaps at the open, so a stop fills far "
            f"past its level — budget for the full {pred:.1f}% (and the tail "
            "beyond it) as the real downside. Size is the only working control: "
            f"{s.position_pct:.1f}% of portfolio puts {s.risk_pct:.2f}% at risk "
            "on a stress move."),
        reasons=reasons,
    )


def plan_post_print_drift(model: dict, row: dict,
                          direction: str = "long",
                          hold_days: int = 5,
                          risk_budget_pct: float = config.DEFAULT_RISK_BUDGET_PCT
                          ) -> TradePlan:
    """Enter after the gap has happened. Here a stop genuinely works."""
    sym = row.get("symbol", "?")
    price = row.get("price") or row.get("spot")
    pred = predict_move(model, row.get("realised_move_med_8"),
                        row.get("realised_move_max_8"), row.get("vol_20d"),
                        row.get("implied_move_pct"))
    if not price or not pred:
        return TradePlan(sym, "post_print_drift", "none", False,
                         reasons=["no price or no move estimate available"])

    # Post-announcement daily vol is far below event-day vol. Scale the event
    # move down to a per-day figure and set levels over the holding period.
    daily = pred / 2.5
    horizon = daily * np.sqrt(hold_days)
    tp_pct, sl_pct = horizon * 1.5, horizon * 1.0

    tp_pct, sl_pct = round(tp_pct, 2), round(sl_pct, 2)
    sgn = 1 if direction == "long" else -1
    tp = price * (1 + sgn * tp_pct / 100)
    sl = price * (1 - sgn * sl_pct / 100)

    s = sizing.vol_target_size(sl_pct, risk_budget_pct=risk_budget_pct,
                               stress_multiple=1.0)
    ev, p_win = _ev_bps(model, pred, direction, tp_pct, sl_pct)
    verb = "Buy" if direction == "long" else "Short"

    return TradePlan(
        symbol=sym, style="post_print_drift", direction=direction,
        tradeable=ev > 0,
        predicted_move_pct=round(pred, 2),
        implied_move_pct=row.get("implied_move_pct"),
        entry_rule=(f"{verb} at the close of the reaction day, i.e. after the "
                    f"gap has already happened."),
        entry_ref=round(float(price), 2),
        tp_price=round(tp, 2), tp_pct=tp_pct,
        sl_price=round(sl, 2), sl_pct=sl_pct,
        hold_days=hold_days,
        size_pct=s.position_pct,
        ev_bps=round(ev, 1), p_win=round(p_win, 3),
        risk_note=(f"Stop works here — the gap is behind you. Risking "
                   f"{sl_pct:.1f}% to make {tp_pct:.1f}% at a {p_win:.0%} hit "
                   f"rate. Backtest note: post-earnings drift did NOT beat a "
                   f"random control out of sample, so treat this geometry as "
                   f"risk management, not as an edge."),
        reasons=[f"predicted event move {pred:.1f}%, scaled to "
                 f"{horizon:.1f}% over {hold_days} sessions"],
    )


def plan_premium_sell(model: dict, row: dict) -> TradePlan:
    """The one setup with a validated edge behind it — and it needs options.

    If the straddle is charging materially more than the stock's own history
    says it will move, that gap is the edge the magnitude finding actually
    supports. Included for completeness; it requires options permissions and
    carries uncapped risk if done naked.
    """
    sym = row.get("symbol", "?")
    imp = row.get("implied_move_pct")
    pred = predict_move(model, row.get("realised_move_med_8"),
                        row.get("realised_move_max_8"), row.get("vol_20d"))
    if not imp or not pred:
        return TradePlan(sym, "premium_sell", "none", False,
                         reasons=["needs both an implied and a predicted move"])

    ratio = imp / pred
    edge = imp - pred
    return TradePlan(
        symbol=sym, style="premium_sell", direction="short_vol",
        tradeable=ratio >= 1.25,
        predicted_move_pct=round(pred, 2), implied_move_pct=round(imp, 2),
        entry_rule="Sell the ATM straddle/iron condor on the first expiry after "
                   "the print; close the morning after.",
        ev_bps=round(edge * 100, 1),
        risk_note=("Uncapped loss if sold naked — define the risk with spreads. "
                   "This is the only style backed by a finding that survived "
                   "holdout, but it needs options permissions."),
        reasons=[f"implied {imp:.1f}% vs predicted {pred:.1f}% ({ratio:.2f}x)",
                 f"theoretical edge {edge:+.1f} percentage points of move"],
    )


def plan_all(model: dict, row: dict, direction: str = "long") -> list[TradePlan]:
    return [
        plan_through_print(model, row, direction),
        plan_post_print_drift(model, row, direction),
        plan_premium_sell(model, row),
    ]


# ------------------------------------------------------------------ driver
def main():
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--refit", action="store_true")
    ap.add_argument("--symbol", type=str, default="")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    model = load_move_model()
    if model is None or args.refit:
        ev = pd.read_pickle(config.DATA / "events.pkl")
        model = fit_move_model(ev)
        MOVE_MODEL.write_text(json.dumps(model, indent=2))
        log.info("fitted move model -> %s", MOVE_MODEL)

    print(f"\nMove model: corr {model['corr_train']:.3f} train / "
          f"{model['corr_validate']:.3f} validate, "
          f"calibration x{model['calibration']:.3f}, n={model['n_train']:,}")

    sc = pd.read_pickle(config.RESULTS / "scorecard.pkl")
    if args.symbol:
        sc = sc[sc["symbol"] == args.symbol.upper()]
    else:
        sc = sc.sort_values("market_cap", ascending=False).head(args.top)

    for _, r in sc.iterrows():
        row = r.to_dict()
        v = row.get("verdict") or {}
        direction = "short" if v.get("score", 0) < 0 else "long"
        print(f"\n{'=' * 74}")
        print(f"{row['symbol']}  reports {row['report_date']} ({row['session']})"
              f"   stance: {v.get('stance', '?')}  ->  bias {direction}")
        for p in plan_all(model, row, direction):
            flag = "TRADEABLE" if p.tradeable else "negative expectancy"
            print(f"\n  [{p.style}]  {p.direction}   EV {p.ev_bps:+.0f} bps   ({flag})")
            if p.entry_rule:
                print(f"    entry : {p.entry_rule}")
            if p.entry_ref:
                print(f"    ref   : {p.entry_ref}")
            if p.tp_price:
                label = "target" if p.style == "through_print" else "TP"
                print(f"    {label:<6}: {p.tp_price}  "
                      f"({p.tp_pct:+.1f}% profit if reached)")
            print(f"    SL    : "
                  + (f"{p.sl_price}  ({p.sl_pct:.1f}% loss)" if p.sl_price
                     else "none — see risk note"))
            if p.size_pct:
                print(f"    size  : {p.size_pct:.1f}% of portfolio")
            print(f"    risk  : {p.risk_note}")


if __name__ == "__main__":
    main()
