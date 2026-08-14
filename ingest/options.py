"""Implied move ingest for near-term reporters.

We only pull option chains for Tier A names (reporting within ~3 weeks), which
keeps this to a few hundred calls a day. The expiry chosen is the first one
*after* the report date, so the straddle actually spans the event.

Yahoo's own impliedVolatility field is unreliable on short-dated contracts, so
implied_move_pct is derived from the straddle mid rather than from IV.
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import config
import db
from providers import yahoo

log = logging.getLogger("pricedin.options")

_SQL = """
INSERT INTO implied_moves
    (symbol, snap_date, expiry, days_to_expiry, spot, atm_strike,
     straddle_mid, implied_move_pct, atm_iv, n_contracts)
VALUES (:symbol,:snap_date,:expiry,:days_to_expiry,:spot,:atm_strike,
        :straddle_mid,:implied_move_pct,:atm_iv,:n_contracts)
ON CONFLICT(symbol, snap_date) DO UPDATE SET
    expiry=excluded.expiry, days_to_expiry=excluded.days_to_expiry,
    spot=excluded.spot, atm_strike=excluded.atm_strike,
    straddle_mid=excluded.straddle_mid,
    implied_move_pct=excluded.implied_move_pct,
    atm_iv=excluded.atm_iv, n_contracts=excluded.n_contracts
"""


def targets(con, days: int | None = None) -> list[tuple[str, str]]:
    """(symbol, report_date) for names reporting inside the Tier A window."""
    days = days if days is not None else config.TIER_A_DAYS
    today = date.today().isoformat()
    end = (date.today() + timedelta(days=days)).isoformat()
    rows = con.execute(
        """
        SELECT c.symbol, MIN(c.report_date) rd
        FROM earnings_calendar c
        JOIN universe u ON u.symbol = c.symbol
        WHERE c.report_date BETWEEN ? AND ? AND u.delisted = 0
        GROUP BY c.symbol
        ORDER BY rd
        """,
        (today, end),
    ).fetchall()
    return [(r["symbol"], r["rd"]) for r in rows]


def ingest_options(pairs: list[tuple[str, str]], workers: int = 4) -> tuple[int, int]:
    mcon = db.market()
    lock = threading.Lock()
    n_ok = n_fail = 0
    pending: list[dict] = []

    def flush():
        if pending:
            mcon.executemany(_SQL, pending)
            pending.clear()
        mcon.commit()

    def work(pair):
        sym, rd = pair
        try:
            # +1 day so a same-day expiry that dies before an after-hours
            # print is not mistaken for event coverage.
            after = (date.fromisoformat(rd) + timedelta(days=1)).isoformat()
            return yahoo.get_implied_move(sym, after)
        except Exception:  # noqa: BLE001
            return None

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(work, p) for p in pairs]
            for i, fut in enumerate(as_completed(futures), 1):
                res = fut.result()
                if not res:
                    n_fail += 1
                else:
                    with lock:
                        pending.append(res)
                    n_ok += 1
                if i % 100 == 0:
                    with lock:
                        flush()
                    log.info("  %d/%d ok=%d fail=%d", i, len(pairs), n_ok, n_fail)
        with lock:
            flush()
    finally:
        mcon.close()
    return n_ok, n_fail


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=config.TIER_A_DAYS)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    started = datetime.now().isoformat(timespec="seconds")
    with db.core_ctx() as con:
        pairs = targets(con, args.days)
        if args.limit:
            pairs = pairs[: args.limit]
        log.info("implied moves for %d names reporting within %dd",
                 len(pairs), args.days)
        n_ok, n_fail = ingest_options(pairs, args.workers)
        db.log_run(con, "options", date.today().isoformat(), started,
                   datetime.now().isoformat(timespec="seconds"), n_ok, n_fail)
        log.info("ok=%d fail=%d", n_ok, n_fail)


if __name__ == "__main__":
    main()
