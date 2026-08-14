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

import pandas as pd

import config
import db

log = logging.getLogger("pricedin.daily")


def _as_ok_fail(res) -> tuple[int, int] | None:
    """Recognise the (n_ok, n_fail) shape the ingest jobs return."""
    if (isinstance(res, tuple) and len(res) == 2
            and all(isinstance(x, int) for x in res)):
        return res
    return None


def stage(name: str, fn, *args, min_success_rate: float = 0.5,
          allow_zero: bool = False, **kwargs):
    """Run a stage and judge whether it actually did anything.

    Catching exceptions is not enough. The ingest jobs swallow per-symbol
    errors by design — one dead ticker must not stop a 3,000-name sweep — so a
    total upstream outage returns (0, 3000) and looks like a clean run. That is
    the worst possible failure mode for the snapshot stage, where a silently
    missed day is a permanent hole. So a stage that succeeded on fewer than
    min_success_rate of its attempts is treated as failed.
    """
    log.info("=" * 60)
    log.info("STAGE: %s", name)
    log.info("=" * 60)
    t0 = datetime.now()
    try:
        out = fn(*args, **kwargs)
        secs = (datetime.now() - t0).total_seconds()

        pair = _as_ok_fail(out)
        if pair is not None:
            ok, fail = pair
            total = ok + fail
            if total and (ok / total) < min_success_rate:
                raise RuntimeError(
                    f"only {ok}/{total} succeeded ({ok / total:.0%}), below the "
                    f"{min_success_rate:.0%} threshold - upstream is probably "
                    f"rate limiting or down")
            log.info("%s ok in %.0fs (%d/%d)", name, secs, ok, total)
        else:
            if not allow_zero and isinstance(out, int) and out == 0:
                raise RuntimeError("stage produced 0 rows")
            log.info("%s ok in %.0fs", name, secs)
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

    # Held to a higher bar than the other stages: this is the only data that
    # cannot be re-fetched later. A missed day is partially recoverable, since
    # eps_trend backfills 7/30/60/90 days on the next successful run, but only
    # if we notice and rerun inside a week.
    res, e = stage("snapshot", do_snapshot, min_success_rate=0.6)
    if e:
        errors.append(f"snapshot: {e}")
        snapshot_failed = True
    else:
        snapshot_failed = False

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
        # Zero new rows is legitimate here: on a weekend or holiday there is
        # simply no new bar to fetch.
        _, e = stage("prices", do_prices, allow_zero=True)
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

    def do_paper():
        import paper
        import report_paper
        sc = pd.read_pickle(config.RESULTS / "scorecard.pkl")
        res = paper.run_live(sc, today)
        log.info("paper: %d closed, %d opened", res["closed"], res["opened"])
        log.info("\n%s", res["summary"].round(2).to_string(index=False))

        con = paper.connect()
        try:
            s = paper.summary(con)
            curves = {}
            for b in s["book"]:
                c = pd.read_sql_query(
                    "SELECT date, equity FROM equity WHERE book=? ORDER BY date",
                    con, params=(b,))
                if not c.empty:
                    curves[b] = c
            blotter = pd.read_sql_query(
                "SELECT book, symbol, side, entry_price, exit_price, exit_date, "
                "exit_reason, pnl, ret_pct FROM positions WHERE status='closed' "
                "AND book != 'spy_hold' ORDER BY exit_date DESC, id DESC LIMIT 25",
                con)
            span = con.execute(
                "SELECT MIN(date) a, MAX(date) b FROM equity").fetchone()
        finally:
            con.close()

        html = report_paper.build_html(s, curves, blotter, {
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "period": f"{span['a']} .. {span['b']}" if span and span["a"] else "",
            "max_concurrent": paper.MAX_CONCURRENT,
        })
        (config.RESULTS / "portfolio.html").write_text(html, encoding="utf-8")
        return res["closed"] + res["opened"]

    # Zero is normal: on most days no tracked name enters or exits.
    _, e = stage("paper trading", do_paper, allow_zero=True)
    if e:
        errors.append(f"paper: {e}")

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
        if snapshot_failed:
            notify("Priced In: SNAPSHOT MISSED",
                   "The consensus snapshot did not run. Rerun within 7 days and "
                   "eps_trend will backfill the gap; after that it is permanent.\n\n"
                   + "\n".join(errors))
        else:
            notify("Priced In: run had errors", "\n".join(errors))
    else:
        log.info("all stages ok")

    # A failed snapshot alone is worth a red build — it is the only stage whose
    # data cannot be recovered by simply running again later.
    return 1 if (snapshot_failed or len(errors) >= 3) else 0


if __name__ == "__main__":
    sys.exit(main())
