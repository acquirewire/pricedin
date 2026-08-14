"""Daily orchestrator. One entry point for the cron job.

Order matters: universe before calendar (the calendar filters to known names),
calendar before snapshot (tiering needs report dates), snapshot before scoring.
Each stage is independently fatal-tolerant — a Yahoo outage in one stage should
not stop the others from writing what they can.
"""
from __future__ import annotations

import argparse
import logging
import sys
import traceback
from datetime import date, datetime

import config
import db

log = logging.getLogger("pricedin.daily")


def stage(name: str, fn, *args, **kwargs):
    log.info("=" * 60)
    log.info("STAGE: %s", name)
    log.info("=" * 60)
    t0 = datetime.now()
    try:
        out = fn(*args, **kwargs)
        log.info("%s ok in %.0fs", name, (datetime.now() - t0).total_seconds())
        return out, None
    except Exception as e:  # noqa: BLE001
        log.error("%s FAILED: %s", name, e)
        log.debug(traceback.format_exc())
        return None, str(e)


def notify(title: str, body: str) -> None:
    if not config.NTFY_TOPIC:
        return
    try:
        import requests
        requests.post(f"https://ntfy.sh/{config.NTFY_TOPIC}",
                      data=body.encode("utf-8"),
                      headers={"Title": title, "Priority": "default"},
                      timeout=15)
    except Exception as e:  # noqa: BLE001
        log.warning("ntfy failed: %s", e)


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-prices", action="store_true")
    ap.add_argument("--skip-history", action="store_true")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--score-days", type=int, default=21)
    args = ap.parse_args()

    from ingest import universe as m_uni, calendar as m_cal
    from ingest import snapshot as m_snap, options as m_opt
    from ingest import prices as m_px, history as m_hist

    errors: list[str] = []
    today = date.today().isoformat()

    _, e = stage("universe", m_uni.refresh_universe)
    if e:
        errors.append(f"universe: {e}")

    _, e = stage("calendar", m_cal.refresh_calendar)
    if e:
        errors.append(f"calendar: {e}")

    # The snapshot is the one stage that cannot be recovered if missed — every
    # skipped day is a permanent hole in the revision history.
    def do_snapshot():
        with db.core_ctx() as con:
            syms, _ = m_uni.symbols_due(con, today)
            log.info("tiering selected %d symbols", len(syms))
            return m_snap.snapshot_symbols(syms, today, args.workers, con)

    res, e = stage("snapshot", do_snapshot)
    if e:
        errors.append(f"snapshot: {e}")

    def do_options():
        with db.core_ctx() as con:
            pairs = m_opt.targets(con)
        return m_opt.ingest_options(pairs, args.workers)

    _, e = stage("implied moves", do_options)
    if e:
        errors.append(f"options: {e}")

    if not args.skip_history:
        def do_history():
            with db.core_ctx() as con:
                syms, dtr = m_uni.symbols_due(con, today)
                # Only names close to reporting need their history topped up.
                near = [s for s in syms if dtr.get(s, 9999) <= config.TIER_A_DAYS]
                return m_hist.ingest_history(near, args.workers, con)
        _, e = stage("earnings history", do_history)
        if e:
            errors.append(f"history: {e}")

    if not args.skip_prices:
        def do_prices():
            with db.core_ctx() as con:
                syms = [r["symbol"] for r in con.execute(
                    "SELECT symbol FROM universe WHERE delisted=0")]
            return m_px.ingest_prices(syms + ["SPY"], incremental=True)
        _, e = stage("prices", do_prices)
        if e:
            errors.append(f"prices: {e}")

    def do_score():
        import score
        import report
        df = score.score_upcoming(args.score_days, str(config.DATA / "events.pkl"))
        if df.empty:
            raise RuntimeError("scorecard empty")
        df.to_pickle(config.RESULTS / "scorecard.pkl")

        con = db.core(init=False)
        try:
            meta = {
                "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "universe": con.execute(
                    "SELECT COUNT(*) c FROM universe WHERE delisted=0").fetchone()["c"],
                "snap_rows": con.execute(
                    "SELECT COUNT(*) c FROM estimate_snapshots").fetchone()["c"],
            }
        finally:
            con.close()
        html = report.build_html(df, meta)
        (config.RESULTS / "dashboard.html").write_text(html, encoding="utf-8")
        return len(df)

    n_scored, e = stage("score + dashboard", do_score)
    if e:
        errors.append(f"score: {e}")

    with db.core_ctx() as con:
        rows = con.execute(
            "SELECT COUNT(*) c FROM estimate_snapshots").fetchone()["c"]
        obs = con.execute("SELECT COUNT(*) c FROM estimate_snapshots "
                          "WHERE source='observed'").fetchone()["c"]
        span = con.execute("SELECT MIN(snap_date) a, MAX(snap_date) b "
                           "FROM estimate_snapshots").fetchone()

    log.info("=" * 60)
    log.info("snapshot history: %d rows (%d observed), %s .. %s",
             rows, obs, span["a"], span["b"])
    log.info("scored: %s", n_scored)
    if errors:
        log.warning("completed with %d errors: %s", len(errors), "; ".join(errors))
        notify("Priced In: run had errors", "\n".join(errors))
    else:
        log.info("all stages ok")

    return 1 if len(errors) >= 3 else 0


if __name__ == "__main__":
    sys.exit(main())
