"""Historical earnings surprises: estimate vs actual, quarter by quarter.

This is the backbone of the backtest. Unlike the consensus snapshots, it is
available retrospectively, so every signal derived from it can be tested over a
decade on day one.
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime

import pandas as pd

import config
import db
from providers import yahoo

log = logging.getLogger("pricedin.history")

_SQL = """
INSERT INTO earnings_history
    (symbol, report_date, report_ts, eps_estimate, eps_actual, surprise_pct)
VALUES (?,?,?,?,?,?)
ON CONFLICT(symbol, report_date) DO UPDATE SET
    report_ts    = COALESCE(excluded.report_ts, report_ts),
    eps_estimate = COALESCE(excluded.eps_estimate, eps_estimate),
    eps_actual   = COALESCE(excluded.eps_actual, eps_actual),
    surprise_pct = COALESCE(excluded.surprise_pct, surprise_pct)
"""


def ingest_history(symbols: list[str], workers: int = 4, con=None) -> tuple[int, int]:
    own = con is None
    con = con or db.core()
    lock = threading.Lock()
    n_ok = n_fail = 0
    pending: list[tuple] = []

    def flush():
        if pending:
            con.executemany(_SQL, pending)
            pending.clear()
        con.commit()

    def work(sym):
        try:
            return sym, yahoo.get_earnings_history(sym)
        except Exception:  # noqa: BLE001
            return sym, None

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(work, s) for s in symbols]
            for i, fut in enumerate(as_completed(futures), 1):
                sym, rows = fut.result()
                if not rows:
                    n_fail += 1
                else:
                    with lock:
                        pending.extend([
                            (r["symbol"], r["report_date"], r["report_ts"],
                             r["eps_estimate"], r["eps_actual"], r["surprise_pct"])
                            for r in rows
                        ])
                    n_ok += 1
                if i % 200 == 0:
                    with lock:
                        flush()
                    log.info("  %d/%d ok=%d fail=%d", i, len(symbols), n_ok, n_fail)
        with lock:
            flush()
    except KeyboardInterrupt:
        with lock:
            flush()
        raise
    finally:
        if own:
            con.close()
    return n_ok, n_fail


def load_history(symbols: list[str] | None = None,
                 reported_only: bool = True) -> pd.DataFrame:
    con = db.core(init=False)
    try:
        q = ("SELECT symbol, report_date, report_ts, eps_estimate, eps_actual, "
             "surprise_pct FROM earnings_history WHERE 1=1")
        params: list = []
        if reported_only:
            q += " AND eps_actual IS NOT NULL"
        if symbols:
            q += f" AND symbol IN ({','.join('?' * len(symbols))})"
            params += symbols
        df = pd.read_sql_query(q, con, params=params)
    finally:
        con.close()
    if not df.empty:
        df["report_date"] = pd.to_datetime(df["report_date"])
        df = df.sort_values(["symbol", "report_date"]).reset_index(drop=True)
    return df


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--symbols", type=str, default="")
    ap.add_argument("--missing-only", action="store_true",
                    help="skip symbols that already have history rows")
    args = ap.parse_args()

    started = datetime.now().isoformat(timespec="seconds")
    with db.core_ctx() as con:
        if args.symbols:
            syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        else:
            q = ("SELECT symbol FROM universe WHERE delisted=0 "
                 "ORDER BY market_cap DESC")
            if args.missing_only:
                q = ("SELECT u.symbol FROM universe u "
                     "LEFT JOIN (SELECT DISTINCT symbol FROM earnings_history) h "
                     "  ON h.symbol = u.symbol "
                     "WHERE u.delisted=0 AND h.symbol IS NULL "
                     "ORDER BY u.market_cap DESC")
            syms = [r["symbol"] for r in con.execute(q)]
        if args.limit:
            syms = syms[: args.limit]

        log.info("earnings history for %d symbols", len(syms))
        n_ok, n_fail = ingest_history(syms, args.workers, con)
        db.log_run(con, "history", date.today().isoformat(), started,
                   datetime.now().isoformat(timespec="seconds"), n_ok, n_fail)

        tot = con.execute("SELECT COUNT(*) c FROM earnings_history").fetchone()["c"]
        rep = con.execute("SELECT COUNT(*) c FROM earnings_history "
                          "WHERE eps_actual IS NOT NULL").fetchone()["c"]
        log.info("ok=%d fail=%d | table: %d rows, %d with actuals",
                 n_ok, n_fail, tot, rep)


if __name__ == "__main__":
    main()
