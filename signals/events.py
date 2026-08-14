"""Build the event panel: one row per (symbol, earnings date).

The single most important thing in this file is the definition of t0.

An earnings print is not a daily bar. If a company reports after the close on
day D, the last price that does not know the result is D's close, and the
reaction shows up in D+1. If it reports before the open on day D, the last
clean price is D-1's close and the reaction is D itself. Get this wrong by one
day and every backtest downstream is measuring the reaction it is trying to
predict — which is the classic way earnings strategies come out looking
spectacular and then lose money.

So: t0 = last trading session whose close precedes the announcement.
    t1 = the next session, i.e. the reaction bar.

Features are computed on data up to and including t0. Returns are measured from
t0 onward. Nothing else is allowed to touch the event row.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

import config

log = logging.getLogger("pricedin.events")


def infer_session(report_ts: str | None, fallback: str = "post") -> str:
    """Yahoo timestamps carry the announcement hour; use it when present."""
    if not report_ts:
        return fallback
    try:
        h = pd.Timestamp(report_ts).hour
    except Exception:  # noqa: BLE001
        return fallback
    if h >= 15:
        return "post"
    if h <= 10:
        return "pre"
    return fallback


def _safe_ret(a: float, b: float) -> float | None:
    if a is None or b is None or not np.isfinite(a) or not np.isfinite(b) or a <= 0:
        return None
    return float(b / a - 1.0)


def build_events(history: pd.DataFrame, prices: pd.DataFrame,
                 bench: pd.DataFrame | None = None,
                 min_history_days: int = 250) -> pd.DataFrame:
    """Join earnings history to prices and compute point-in-time features.

    history : symbol, report_date, report_ts, eps_estimate, eps_actual, surprise_pct
    prices  : symbol, date, open, high, low, close, volume
    bench   : date, close  (SPY, for relative strength) — optional
    """
    if history.empty or prices.empty:
        return pd.DataFrame()

    bench_ret = None
    if bench is not None and not bench.empty:
        b = bench.sort_values("date").set_index("date")["close"]
        bench_ret = b

    out: list[dict] = []
    px_by_sym = {s: g.reset_index(drop=True) for s, g in prices.groupby("symbol")}
    hist_by_sym = {s: g.reset_index(drop=True) for s, g in history.groupby("symbol")}

    for sym, ev in hist_by_sym.items():
        px = px_by_sym.get(sym)
        if px is None or len(px) < min_history_days:
            continue

        dates = px["date"].values
        close = px["close"].to_numpy(dtype=float)
        vol = px["volume"].to_numpy(dtype=float)
        n = len(px)

        # Prior events for this symbol, used to build reaction history.
        ev = ev.sort_values("report_date").reset_index(drop=True)

        # First pass: locate t0/t1 and the realised reaction for every event.
        locs: list[dict] = []
        for _, r in ev.iterrows():
            D = pd.Timestamp(r["report_date"])
            sess = infer_session(r.get("report_ts"))
            cutoff = D - pd.Timedelta(days=1) if sess == "pre" else D
            idx = np.searchsorted(dates, np.datetime64(cutoff), side="right") - 1
            if idx < min_history_days or idx + 1 >= n:
                continue
            locs.append({
                "t0": int(idx),
                "session": sess,
                "report_date": D,
                "eps_estimate": r.get("eps_estimate"),
                "eps_actual": r.get("eps_actual"),
                "surprise_pct": r.get("surprise_pct"),
                "reaction": _safe_ret(close[idx], close[idx + 1]),
            })

        if len(locs) < 2:
            continue

        for k, L in enumerate(locs):
            t0, t1 = L["t0"], L["t0"] + 1

            # ---- prior-event features (strictly earlier prints only) -----
            prior = locs[:k]
            prior_surp = [p["surprise_pct"] for p in prior
                          if p["surprise_pct"] is not None]
            prior_reac = [p["reaction"] for p in prior if p["reaction"] is not None]

            def tail_mean(xs, m):
                xs = xs[-m:]
                return float(np.mean(xs)) if xs else None

            beat_rate = (float(np.mean([s > 0 for s in prior_surp[-8:]]))
                         if prior_surp else None)
            realised_med = (float(np.median([abs(x) for x in prior_reac[-8:]]))
                            if prior_reac else None)
            realised_max = (float(np.max([abs(x) for x in prior_reac[-8:]]))
                            if prior_reac else None)

            # Does this stock actually reward beats? Slope of reaction on
            # surprise across its own history. Flat or negative slope means
            # the beat/miss question is the wrong question for this name.
            slope = None
            pairs = [(p["surprise_pct"], p["reaction"]) for p in prior
                     if p["surprise_pct"] is not None and p["reaction"] is not None]
            if len(pairs) >= 6:
                xs = np.array([p[0] for p in pairs[-12:]], dtype=float)
                ys = np.array([p[1] for p in pairs[-12:]], dtype=float)
                if xs.std() > 1e-9:
                    slope = float(np.polyfit(xs, ys, 1)[0])

            # ---- price features, all ending at t0 ------------------------
            w = config.RUNUP_WINDOW
            runup_10 = _safe_ret(close[t0 - w], close[t0]) if t0 >= w else None
            runup_60 = _safe_ret(close[t0 - 60], close[t0]) if t0 >= 60 else None
            mom_252 = _safe_ret(close[t0 - 252], close[t0]) if t0 >= 252 else None

            rets = np.diff(close[max(0, t0 - 21): t0 + 1]) / close[max(0, t0 - 21): t0]
            vol20 = float(np.std(rets) * np.sqrt(252)) if len(rets) > 5 else None

            dollar_vol = (float(np.nanmean(close[t0 - 20: t0 + 1] *
                                           vol[t0 - 20: t0 + 1]))
                          if t0 >= 20 else None)

            rel_60 = None
            if bench_ret is not None and runup_60 is not None:
                try:
                    d0 = pd.Timestamp(dates[t0 - 60])
                    d1 = pd.Timestamp(dates[t0])
                    b0 = bench_ret.asof(d0)
                    b1 = bench_ret.asof(d1)
                    br = _safe_ret(b0, b1)
                    if br is not None:
                        rel_60 = runup_60 - br
                except Exception:  # noqa: BLE001
                    pass

            # ---- forward returns (the targets) ---------------------------
            fwd = {}
            for h in config.DRIFT_WINDOWS:
                j = t1 + h - 1
                fwd[f"ret_{h}d"] = _safe_ret(close[t0], close[j]) if j < n else None
            # Drift measured from the reaction close, i.e. what is left on the
            # table for someone who did not hold through the print.
            for h in (5, 20):
                j = t1 + h
                fwd[f"drift_{h}d"] = _safe_ret(close[t1], close[j]) if j < n else None

            out.append({
                "symbol": sym,
                "report_date": L["report_date"],
                "session": L["session"],
                "t0_date": pd.Timestamp(dates[t0]),
                "price_t0": float(close[t0]),
                "eps_estimate": L["eps_estimate"],
                "eps_actual": L["eps_actual"],
                "surprise_pct": L["surprise_pct"],
                "n_prior": len(prior),
                # features
                "surp_mean_4": tail_mean(prior_surp, 4),
                "surp_mean_8": tail_mean(prior_surp, 8),
                "beat_rate_8": beat_rate,
                "reac_mean_8": tail_mean(prior_reac, 8),
                "realised_move_med_8": realised_med,
                "realised_move_max_8": realised_max,
                "reaction_slope": slope,
                "runup_10d": runup_10,
                "runup_60d": runup_60,
                "mom_252d": mom_252,
                "vol_20d": vol20,
                "dollar_vol_20d": dollar_vol,
                "rel_strength_60d": rel_60,
                **fwd,
            })

    df = pd.DataFrame(out)
    if df.empty:
        return df
    df["abs_ret_1d"] = df["ret_1d"].abs()
    df["year"] = df["report_date"].dt.year
    return df.sort_values(["report_date", "symbol"]).reset_index(drop=True)
