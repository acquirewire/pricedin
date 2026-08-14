"""Export the pipeline's output as JSON for the Next.js front end.

The Python side stays the single source of truth. This writes a static snapshot
into web/src/data/, which the app reads at build time — so the site deploys as
static files with no runtime database and no API to keep alive.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import datetime

import numpy as np
import pandas as pd

import config
import db
import levels as lv
import paper

log = logging.getLogger("pricedin.export_web")

WEB_DATA = config.ROOT / "web" / "src" / "data"


def clean(v):
    """JSON-safe scalars. NaN becomes null rather than the literal NaN token."""
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if not math.isfinite(f) else round(f, 6)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return str(v)[:10]
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    return v


SCORECARD_FIELDS = [
    "symbol", "name", "report_date", "session", "days_to_report", "market_cap",
    "price", "eps_forecast", "n_estimates", "n_analysts",
    "p_beat", "p_beat_n", "beat_rate_8", "surp_mean_4",
    "rev_chg_7d", "rev_chg_30d", "rev_chg_90d", "up_30d", "down_30d",
    "n_observed", "snap_span_days",
    "implied_move_pct", "implied_expiry", "realised_move_med_8",
    "realised_move_max_8", "implied_vs_realised",
    "runup_10d", "runup_60d", "vol_20d",
    "reac_mean_8", "reac_median_8", "reaction_slope", "beat_and_fell_rate",
    "last_reactions", "n_quarters", "size_pct", "size_basis", "size_risk_pct",
]


def export_events(model) -> list[dict]:
    df = pd.read_pickle(config.RESULTS / "scorecard.pkl")
    out = []
    for _, r in df.iterrows():
        row = {f: clean(r[f]) for f in SCORECARD_FIELDS if f in r}
        v = r.get("verdict")
        if isinstance(v, dict):
            row["verdict"] = {
                "stance": v.get("stance"),
                "tone": v.get("colour"),
                "score": v.get("score"),
                "supports": v.get("supports", []),
                "against": v.get("against", []),
                "neutral": v.get("neutral", []),
                "caveat": v.get("caveat"),
            }
        # Trade geometry, so the detail page does not have to recompute it.
        if model:
            direction = "short" if (v or {}).get("score", 0) < 0 else "long"
            row["plans"] = [clean(p.dict())
                            for p in lv.plan_all(model, r.to_dict(), direction)]
        out.append(row)
    return out


def export_portfolio() -> dict:
    con = paper.connect()
    try:
        summary = paper.summary(con)
        curves = {}
        for b in summary["book"]:
            c = pd.read_sql_query(
                "SELECT date, equity FROM equity WHERE book=? ORDER BY date",
                con, params=(b,))
            if not c.empty:
                # Weekly sampling keeps the payload small without changing the
                # shape of a 650-session curve.
                c = c.iloc[::5]
                curves[b] = [{"date": d, "equity": round(float(e), 2)}
                             for d, e in zip(c["date"], c["equity"])]
        blotter = pd.read_sql_query(
            "SELECT book, symbol, side, entry_date, entry_price, exit_price, "
            "exit_date, exit_reason, pnl, ret_pct FROM positions "
            "WHERE status='closed' AND book != 'spy_hold' "
            "ORDER BY exit_date DESC, id DESC LIMIT 60", con)
        open_pos = pd.read_sql_query(
            "SELECT book, symbol, side, entry_date, entry_price, qty "
            "FROM positions WHERE status='open' ORDER BY entry_date DESC", con)
        span = con.execute("SELECT MIN(date) a, MAX(date) b FROM equity").fetchone()
    finally:
        con.close()

    books = []
    for _, r in summary.iterrows():
        d = {k: clean(r[k]) for k in summary.columns}
        d["description"] = paper.BOOKS.get(r["book"], "")
        d["role"] = ("control" if r["book"] == "random"
                     else "benchmark" if r["book"] == "spy_hold" else "strategy")
        books.append(d)

    return {
        "books": books,
        "curves": curves,
        "blotter": [{k: clean(v) for k, v in row.items()}
                    for row in blotter.to_dict("records")],
        "open": [{k: clean(v) for k, v in row.items()}
                 for row in open_pos.to_dict("records")],
        "period": {"start": span["a"], "end": span["b"]} if span else {},
        "settings": {
            "starting_cash": paper.STARTING_CASH,
            "max_concurrent": paper.MAX_CONCURRENT,
            "cost_bps": paper.COST_BPS,
            "slippage_bps": paper.SLIPPAGE_BPS,
        },
    }


def export_backtest() -> dict:
    res_path = config.RESULTS / "backtest_results.csv"
    surv_path = config.RESULTS / "backtest_survivors.csv"
    out: dict = {"strategies": [], "survivors": [], "magnitude": []}

    if res_path.exists():
        res = pd.read_csv(res_path)
        directional = res[res["kind"] == "directional"] if "kind" in res else res
        magnitude = res[res["kind"] == "magnitude"] if "kind" in res else res.iloc[0:0]

        for _, r in directional.iterrows():
            out["strategies"].append({k: clean(r[k]) for k in [
                "name", "period", "n", "mean_bps", "net_mean_bps", "hit_rate",
                "t_stat", "control_mean_bps", "excess_bps", "t_vs_control", "note"
            ] if k in r})
        for _, r in magnitude.iterrows():
            d = {k: clean(r[k]) for k in
                 ["name", "period", "n", "mean_bps", "control_mean_bps", "note"]
                 if k in r}
            cm = r.get("control_mean_bps")
            d["ratio"] = clean(r["mean_bps"] / cm) if cm else None
            out["magnitude"].append(d)

    if surv_path.exists():
        surv = pd.read_csv(surv_path)
        out["survivors"] = [{k: clean(v) for k, v in row.items()}
                            for row in surv.to_dict("records")]

    mm = lv.load_move_model()
    if mm:
        out["move_model"] = {
            "corr_train": clean(mm.get("corr_train")),
            "corr_validate": clean(mm.get("corr_validate")),
            "n_train": clean(mm.get("n_train")),
            "calibration": clean(mm.get("calibration")),
        }
    out["splits"] = {
        "train_end": config.BACKTEST_TRAIN_END,
        "validate_end": config.BACKTEST_VALIDATE_END,
    }
    return out


def export_meta() -> dict:
    con = db.core(init=False)
    try:
        universe = con.execute(
            "SELECT COUNT(*) c FROM universe WHERE delisted=0").fetchone()["c"]
        snaps = con.execute(
            "SELECT COUNT(*) c FROM estimate_snapshots").fetchone()["c"]
        observed = con.execute("SELECT COUNT(*) c FROM estimate_snapshots "
                               "WHERE source='observed'").fetchone()["c"]
        span = con.execute("SELECT MIN(snap_date) a, MAX(snap_date) b "
                           "FROM estimate_snapshots").fetchone()
        prints = con.execute("SELECT COUNT(*) c FROM earnings_history "
                             "WHERE eps_actual IS NOT NULL").fetchone()["c"]
    finally:
        con.close()
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "universe": universe,
        "snapshot_rows": snaps,
        "snapshot_observed": observed,
        "snapshot_span": {"start": span["a"], "end": span["b"]} if span else {},
        "historical_prints": prints,
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(WEB_DATA))
    args = ap.parse_args()

    out = config.ROOT / args.out if not str(args.out).startswith("C:") else \
        __import__("pathlib").Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    model = lv.load_move_model()
    payloads = {
        "events.json": export_events(model),
        "portfolio.json": export_portfolio(),
        "backtest.json": export_backtest(),
        "meta.json": export_meta(),
    }
    for name, data in payloads.items():
        p = out / name
        p.write_text(json.dumps(data, indent=None, separators=(",", ":")),
                     encoding="utf-8")
        log.info("%-16s %8.0f KB", name, p.stat().st_size / 1024)

    log.info("exported to %s", out)


if __name__ == "__main__":
    main()
