"""Three-panel scoring for upcoming earnings.

The panels are kept separate on purpose. A single blended 0-100 score hides
where the view comes from, and the three questions are genuinely different:

  Expectation  Will they beat? Consensus history, revision momentum, breadth.
  Asymmetry    Is it worth it? What the options market is charging for the
               event versus what this stock actually tends to do, plus how much
               good news is already in the price via the run-up.
  Reaction     Does beating even help? Some names beat every quarter and fall
               anyway. The slope of past reaction on past surprise says so.

The advisory verdict is rules-based and shows its arithmetic. Where a rule
comes from a strategy that cleared backtest.py it says so; where it does not,
it says that too.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

import config
import db
from ingest import prices as price_mod
from signals.events import infer_session
import sizing

log = logging.getLogger("pricedin.score")

BEAT_MODEL = config.RESULTS / "beat_model.json"


# ------------------------------------------------------- empirical P(beat)
def fit_beat_model(events: pd.DataFrame) -> dict:
    """Empirical beat rate bucketed by the stock's own recent record.

    This is not a fitted classifier and does not pretend to be. It reports the
    historical frequency of a beat among past events that looked similar on the
    two features we can actually measure point-in-time across a decade. Fitted
    on training data only.

    Revision momentum is deliberately absent: we have no historical revisions
    yet, so including it would mean fitting on three months of data and calling
    it a decade. It appears in the Expectation panel as context instead.
    """
    tr = events[events["report_date"] <= config.BACKTEST_TRAIN_END]
    tr = tr[tr["surprise_pct"].notna() & tr["beat_rate_8"].notna()]
    if tr.empty:
        return {"base_rate": 0.7, "buckets": {}, "n": 0}

    base = float((tr["surprise_pct"] > 0).mean())
    buckets: dict[str, dict] = {}
    br_bins = [0, 0.5, 0.7, 0.85, 1.01]
    sm_bins = [-np.inf, 0, 3, 8, np.inf]

    tr = tr.copy()
    tr["br_b"] = pd.cut(tr["beat_rate_8"], br_bins, right=False, labels=False)
    tr["sm_b"] = pd.cut(tr["surp_mean_4"].fillna(0), sm_bins, right=False, labels=False)

    for (a, b), g in tr.groupby(["br_b", "sm_b"], observed=True):
        if len(g) < 100:      # thin buckets get the base rate, not noise
            continue
        buckets[f"{int(a)}_{int(b)}"] = {
            "p": float((g["surprise_pct"] > 0).mean()),
            "n": int(len(g)),
        }

    return {"base_rate": base, "buckets": buckets, "n": int(len(tr)),
            "br_bins": br_bins, "sm_bins": [-999, 0, 3, 8, 999],
            "fitted_through": config.BACKTEST_TRAIN_END}


def p_beat(model: dict, beat_rate: float | None, surp_mean: float | None) -> tuple[float, int]:
    if beat_rate is None or not np.isfinite(beat_rate):
        return model.get("base_rate", 0.7), 0
    br_bins = model.get("br_bins", [0, 0.5, 0.7, 0.85, 1.01])
    sm_bins = model.get("sm_bins", [-999, 0, 3, 8, 999])
    a = int(np.clip(np.searchsorted(br_bins, beat_rate, "right") - 1, 0, 3))
    sm = surp_mean if surp_mean is not None and np.isfinite(surp_mean) else 0.0
    b = int(np.clip(np.searchsorted(sm_bins, sm, "right") - 1, 0, 3))
    hit = model.get("buckets", {}).get(f"{a}_{b}")
    if hit:
        return hit["p"], hit["n"]
    return model.get("base_rate", 0.7), 0


# ------------------------------------------------------- revision momentum
def revision_momentum(con, symbols: list[str], period: str = "0q") -> dict[str, dict]:
    """Change in consensus EPS over 7/30/90d, from our own snapshot history."""
    if not symbols:
        return {}
    q = f"""
        SELECT symbol, snap_date, eps_avg, eps_n_analysts,
               up_7d, down_7d, up_30d, down_30d, source
        FROM estimate_snapshots
        WHERE period = ? AND symbol IN ({','.join('?' * len(symbols))})
        ORDER BY symbol, snap_date
    """
    df = pd.read_sql_query(q, con, params=[period, *symbols])
    if df.empty:
        return {}

    out: dict[str, dict] = {}
    for sym, g in df.groupby("symbol"):
        g = g.dropna(subset=["eps_avg"]).sort_values("snap_date")
        if g.empty:
            continue
        latest = g.iloc[-1]
        cur = float(latest["eps_avg"])
        d_latest = pd.Timestamp(latest["snap_date"])

        def chg(days: int):
            cutoff = (d_latest - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
            past = g[g["snap_date"] <= cutoff]
            if past.empty:
                return None
            prev = float(past.iloc[-1]["eps_avg"])
            # Percentage change is meaningless across a sign flip, and most
            # loss-making names sit near zero. Use magnitude as denominator and
            # flag the sign change separately.
            if abs(prev) < 1e-6:
                return None
            return 100.0 * (cur - prev) / abs(prev)

        out[sym] = {
            "eps_now": cur,
            "rev_chg_7d": chg(7),
            "rev_chg_30d": chg(30),
            "rev_chg_90d": chg(90),
            "n_analysts": (int(latest["eps_n_analysts"])
                           if pd.notna(latest["eps_n_analysts"]) else None),
            "up_30d": (int(latest["up_30d"]) if pd.notna(latest["up_30d"]) else None),
            "down_30d": (int(latest["down_30d"]) if pd.notna(latest["down_30d"]) else None),
            "snap_span_days": int((d_latest - pd.Timestamp(g.iloc[0]["snap_date"])).days),
            "n_observed": int((g["source"] == "observed").sum()),
        }
    return out


# ---------------------------------------------------------- reaction stats
def reaction_stats(history: pd.DataFrame, px: pd.DataFrame,
                   symbols: list[str]) -> dict[str, dict]:
    """Per-stock earnings reaction history, computed the same way as events.py."""
    out: dict[str, dict] = {}
    px_by = {s: g.reset_index(drop=True) for s, g in px.groupby("symbol")}
    h_by = {s: g.sort_values("report_date") for s, g in history.groupby("symbol")}

    for sym in symbols:
        p = px_by.get(sym)
        h = h_by.get(sym)
        if p is None or h is None or len(p) < 60 or h.empty:
            continue
        dates = p["date"].values
        close = p["close"].to_numpy(dtype=float)
        n = len(p)

        reacs, surps = [], []
        for _, r in h.iterrows():
            D = pd.Timestamp(r["report_date"])
            sess = infer_session(r.get("report_ts"))
            cutoff = D - pd.Timedelta(days=1) if sess == "pre" else D
            i = np.searchsorted(dates, np.datetime64(cutoff), "right") - 1
            if i < 1 or i + 1 >= n or close[i] <= 0:
                continue
            reacs.append(float(close[i + 1] / close[i] - 1.0))
            surps.append(r.get("surprise_pct"))

        if len(reacs) < 4:
            continue
        r8 = reacs[-8:]
        s8 = surps[-8:]

        slope = None
        pairs = [(s, r) for s, r in zip(surps[-12:], reacs[-12:])
                 if s is not None and np.isfinite(s)]
        if len(pairs) >= 6:
            xs = np.array([q[0] for q in pairs], float)
            ys = np.array([q[1] for q in pairs], float)
            if xs.std() > 1e-9:
                slope = float(np.polyfit(xs, ys, 1)[0])

        beat_and_fell = [
            1 for s, r in zip(s8, r8)
            if s is not None and np.isfinite(s) and s > 0 and r < 0
        ]
        n_beats = sum(1 for s in s8 if s is not None and np.isfinite(s) and s > 0)

        out[sym] = {
            "n_quarters": len(reacs),
            "reac_mean_8": float(np.mean(r8)) * 100,
            "reac_median_8": float(np.median(r8)) * 100,
            "realised_move_med_8": float(np.median([abs(x) for x in r8])) * 100,
            "realised_move_max_8": float(np.max([abs(x) for x in r8])) * 100,
            "reaction_slope": slope,
            "beat_rate_8": (float(n_beats / len([s for s in s8 if s is not None]))
                            if any(s is not None for s in s8) else None),
            "beat_and_fell_rate": (len(beat_and_fell) / n_beats) if n_beats else None,
            "last_reactions": [round(x * 100, 1) for x in reacs[-4:]],
            "surp_mean_4": (float(np.nanmean([s for s in surps[-4:] if s is not None]))
                            if any(s is not None for s in surps[-4:]) else None),
        }
    return out


# ------------------------------------------------------------- the verdict
def build_verdict(row: dict) -> dict:
    """Rules-based stance for a long held through the print, with workings.

    Every clause names the number that produced it. If you disagree with the
    verdict you should be able to see exactly which input to argue with.
    """
    pos, neg, neutral = [], [], []

    pb = row.get("p_beat")
    if pb is not None:
        (pos if pb >= 0.75 else neutral if pb >= 0.6 else neg).append(
            f"{pb:.0%} historical beat frequency for names with this record"
            + (f" (n={row['p_beat_n']})" if row.get("p_beat_n") else " (base rate)")
        )

    rev = row.get("rev_chg_30d")
    if rev is not None:
        if rev > 1:
            pos.append(f"consensus EPS revised up {rev:+.1f}% in 30d")
        elif rev < -1:
            neg.append(f"consensus EPS revised down {rev:+.1f}% in 30d")
        else:
            neutral.append(f"consensus EPS flat ({rev:+.1f}% in 30d)")

    up, dn = row.get("up_30d"), row.get("down_30d")
    if up is not None and dn is not None and (up + dn) > 0:
        if dn > up:
            neg.append(f"revision breadth negative ({up} up / {dn} down, 30d)")
        elif up > dn:
            pos.append(f"revision breadth positive ({up} up / {dn} down, 30d)")

    # --- asymmetry ---------------------------------------------------------
    imp, real = row.get("implied_move_pct"), row.get("realised_move_med_8")
    ratio = row.get("implied_vs_realised")
    if ratio is not None:
        if ratio >= 1.3:
            neg.append(f"options price a {imp:.1f}% move vs {real:.1f}% median "
                       f"realised ({ratio:.2f}x) - expensive expectations")
        elif ratio <= 0.85:
            pos.append(f"options price a {imp:.1f}% move vs {real:.1f}% median "
                       f"realised ({ratio:.2f}x) - cheap relative to history")
        else:
            neutral.append(f"implied {imp:.1f}% vs realised {real:.1f}% "
                           f"({ratio:.2f}x) - fairly priced")

    ru = row.get("runup_10d")
    if ru is not None:
        if ru > 10:
            neg.append(f"up {ru:+.1f}% in the 10 sessions into the print - "
                       f"good news partly in the price")
        elif ru < -10:
            pos.append(f"down {ru:+.1f}% into the print - low expectations")

    # --- reaction ----------------------------------------------------------
    slope = row.get("reaction_slope")
    rm = row.get("reac_mean_8")
    if slope is not None:
        if slope <= 0:
            neg.append("historically does not get paid for beating "
                       f"(reaction/surprise slope {slope:+.4f})")
        else:
            pos.append(f"historically rewards beats (slope {slope:+.4f})")
    if rm is not None:
        if rm < -1:
            neg.append(f"average reaction over last 8 prints is {rm:+.1f}%")
        elif rm > 1:
            pos.append(f"average reaction over last 8 prints is {rm:+.1f}%")

    bf = row.get("beat_and_fell_rate")
    if bf is not None and bf >= 0.5:
        neg.append(f"fell on {bf:.0%} of its recent beats")

    score = len(pos) - len(neg)
    if score >= 3:
        stance, colour = "Favourable", "pos"
    elif score >= 1:
        stance, colour = "Leaning favourable", "lean-pos"
    elif score <= -3:
        stance, colour = "Unfavourable", "neg"
    elif score <= -1:
        stance, colour = "Leaning unfavourable", "lean-neg"
    else:
        stance, colour = "Neutral", "neutral"

    return {
        "stance": stance,
        "colour": colour,
        "score": score,
        "supports": pos,
        "against": neg,
        "neutral": neutral,
        "caveat": "Rules-based summary of the panels above, and explicitly NOT "
                  "a validated edge. Fifteen directional strategies were tested "
                  "over 83,366 prints from 2016-2026; none beat a random pick "
                  "from the same universe across train, validate and holdout. "
                  "The one that cleared train+validate (buy the beat, hold 20d) "
                  "failed holdout. Treat direction here as context, not signal. "
                  "The Asymmetry panel is the part with evidence behind it: "
                  "reaction size is genuinely persistent per stock.",
    }


# ------------------------------------------------------------------ driver
def score_upcoming(days: int = 21, events_path: str | None = None) -> pd.DataFrame:
    con = db.core(init=False)
    mcon = db.market(init=False)
    try:
        today = date.today()
        end = (today + timedelta(days=days)).isoformat()
        cal = pd.read_sql_query(
            """
            SELECT c.symbol, MIN(c.report_date) report_date, c.session,
                   c.fiscal_quarter, c.eps_forecast, c.n_estimates,
                   u.name, u.market_cap
            FROM earnings_calendar c
            JOIN universe u ON u.symbol=c.symbol
            WHERE c.report_date BETWEEN ? AND ? AND u.delisted=0
            GROUP BY c.symbol
            ORDER BY report_date
            """,
            con, params=(today.isoformat(), end),
        )
        if cal.empty:
            return pd.DataFrame()

        symbols = cal["symbol"].tolist()

        hist = pd.read_sql_query(
            f"""SELECT symbol, report_date, report_ts, surprise_pct, eps_actual
                FROM earnings_history
                WHERE eps_actual IS NOT NULL
                  AND symbol IN ({','.join('?' * len(symbols))})""",
            con, params=symbols)
        if not hist.empty:
            hist["report_date"] = pd.to_datetime(hist["report_date"])

        px = price_mod.load_prices(
            symbols, start=(today - timedelta(days=900)).isoformat())

        imp = pd.read_sql_query(
            """SELECT symbol, implied_move_pct, expiry, days_to_expiry, spot,
                      snap_date
               FROM implied_moves WHERE snap_date >= ?""",
            mcon, params=((today - timedelta(days=3)).isoformat(),))
        imp_by = {r["symbol"]: dict(r) for _, r in imp.iterrows()} if not imp.empty else {}

        rev = revision_momentum(con, symbols)
        rs = reaction_stats(hist, px, symbols) if not hist.empty and not px.empty else {}

        model = {"base_rate": 0.70, "buckets": {}, "n": 0}
        if BEAT_MODEL.exists():
            model = json.loads(BEAT_MODEL.read_text())
        elif events_path:
            try:
                ev = pd.read_pickle(events_path)
                model = fit_beat_model(ev)
                BEAT_MODEL.write_text(json.dumps(model, indent=2))
            except Exception as e:  # noqa: BLE001
                log.warning("could not fit beat model: %s", e)

        px_by = {s: g.reset_index(drop=True) for s, g in px.groupby("symbol")} \
            if not px.empty else {}

        rows = []
        for _, c in cal.iterrows():
            sym = c["symbol"]
            r: dict = {
                "symbol": sym,
                "name": c["name"],
                "report_date": c["report_date"],
                "session": c["session"],
                "fiscal_quarter": c["fiscal_quarter"],
                "market_cap": c["market_cap"],
                "eps_forecast": c["eps_forecast"],
                "n_estimates": c["n_estimates"],
                "days_to_report": (date.fromisoformat(c["report_date"]) - today).days,
            }
            r.update(rev.get(sym, {}))
            r.update(rs.get(sym, {}))

            im = imp_by.get(sym)
            if im:
                r["implied_move_pct"] = im.get("implied_move_pct")
                r["implied_expiry"] = im.get("expiry")
                r["spot"] = im.get("spot")

            p = px_by.get(sym)
            if p is not None and len(p) > 61:
                cl = p["close"].to_numpy(float)
                r["price"] = float(cl[-1])
                r["runup_10d"] = float(cl[-1] / cl[-11] - 1) * 100
                r["runup_60d"] = float(cl[-1] / cl[-61] - 1) * 100
                rr = np.diff(cl[-22:]) / cl[-22:-1]
                r["vol_20d"] = float(np.std(rr) * np.sqrt(252)) * 100

            if r.get("implied_move_pct") and r.get("realised_move_med_8"):
                r["implied_vs_realised"] = (r["implied_move_pct"]
                                            / r["realised_move_med_8"])

            pb, pbn = p_beat(model, r.get("beat_rate_8"), r.get("surp_mean_4"))
            r["p_beat"], r["p_beat_n"] = pb, pbn

            # Sizing off the best available estimate of the event move.
            move = r.get("implied_move_pct") or r.get("realised_move_med_8")
            if move:
                s = sizing.vol_target_size(move)
                r["size_pct"] = s.position_pct
                r["size_basis"] = s.basis
                r["size_risk_pct"] = s.risk_pct

            r["verdict"] = build_verdict(r)
            rows.append(r)

        return pd.DataFrame(rows)
    finally:
        con.close()
        mcon.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--events", default=str(config.DATA / "events.pkl"))
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    df = score_upcoming(args.days, args.events)
    if df.empty:
        print("nothing upcoming - run the calendar ingest")
        return

    df.to_pickle(config.RESULTS / "scorecard.pkl")
    log.info("scored %d upcoming events -> results/scorecard.pkl", len(df))

    show = df.sort_values("market_cap", ascending=False).head(args.top)
    for _, r in show.iterrows():
        v = r["verdict"]
        mc = (r["market_cap"] or 0) / 1e9
        print(f"\n{'=' * 72}")
        print(f"{r['symbol']:<6} {str(r['name'])[:40]:<40} ${mc:.1f}b")
        print(f"  reports {r['report_date']} ({r['session']}), "
              f"T-{r['days_to_report']}   ->  {v['stance']}")
        for s in v["supports"]:
            print(f"   +  {s}")
        for s in v["against"]:
            print(f"   -  {s}")
        for s in v["neutral"]:
            print(f"   .  {s}")
        if r.get("size_pct"):
            print(f"   size: {r['size_pct']:.1f}% of portfolio ({r['size_basis']})")


if __name__ == "__main__":
    main()
