"""Daily consensus snapshot — the part of this project that compounds.

Today's consensus EPS is free from a dozen places. The *history* of consensus
EPS is not: it sits behind Bloomberg/FactSet/Zacks because someone had to be
storing it every day. This job stores it.

Two sources of rows:

  observed  what consensus is today. Captured once per symbol per day.
  backfill  reconstructed from Yahoo's eps_trend, which reports what consensus
            was 7/30/60/90 days ago. This means a ticker arrives with a quarter
            of revision history already attached rather than starting empty.

Observed rows always beat backfill rows for the same (symbol, date, period).
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
from ingest import universe as uni
from providers import yahoo

log = logging.getLogger("pricedin.snapshot")

_COLS = (
    "symbol", "snap_date", "period", "eps_avg", "eps_low", "eps_high",
    "eps_n_analysts", "eps_year_ago", "rev_avg", "rev_n_analysts",
    "rev_year_ago", "up_7d", "down_7d", "up_30d", "down_30d", "source",
)

_OBSERVED_SQL = f"""
INSERT INTO estimate_snapshots ({', '.join(_COLS)})
VALUES ({', '.join(':' + c for c in _COLS)})
ON CONFLICT(symbol, snap_date, period) DO UPDATE SET
    eps_avg=excluded.eps_avg, eps_low=excluded.eps_low,
    eps_high=excluded.eps_high, eps_n_analysts=excluded.eps_n_analysts,
    eps_year_ago=excluded.eps_year_ago, rev_avg=excluded.rev_avg,
    rev_n_analysts=excluded.rev_n_analysts, rev_year_ago=excluded.rev_year_ago,
    up_7d=excluded.up_7d, down_7d=excluded.down_7d,
    up_30d=excluded.up_30d, down_30d=excluded.down_30d,
    source='observed'
"""

# Never let a reconstructed row overwrite one we actually watched happen.
_BACKFILL_SQL = f"""
INSERT INTO estimate_snapshots ({', '.join(_COLS)})
VALUES ({', '.join(':' + c for c in _COLS)})
ON CONFLICT(symbol, snap_date, period) DO NOTHING
"""


def _blank(symbol: str, snap_date: str, period: str, source: str) -> dict:
    row = {c: None for c in _COLS}
    row.update(symbol=symbol, snap_date=snap_date, period=period, source=source)
    return row


def build_rows(symbol: str, est: dict, today: str) -> tuple[list[dict], list[dict]]:
    """Turn one get_estimates() payload into observed + backfill rows."""
    observed, backfill = [], []
    td = date.fromisoformat(today)

    for period, p in est.items():
        row = _blank(symbol, today, period, "observed")
        for k in ("eps_avg", "eps_low", "eps_high", "eps_n_analysts",
                  "eps_year_ago", "rev_avg", "rev_n_analysts", "rev_year_ago",
                  "up_7d", "down_7d", "up_30d", "down_30d"):
            if p.get(k) is not None:
                row[k] = p[k]

        trend = p.get("trend") or {}
        # Prefer the trend's 'current' reading for consistency with the
        # lookback values, so a revision series is measured on one ruler.
        if trend.get(0) is not None:
            row["eps_avg"] = trend[0]
        observed.append(row)

        for lag in (7, 30, 60, 90):
            val = trend.get(lag)
            if val is None:
                continue
            b = _blank(symbol, (td - timedelta(days=lag)).isoformat(),
                       period, "backfill")
            b["eps_avg"] = val
            b["eps_n_analysts"] = p.get("eps_n_analysts")
            backfill.append(b)

    return observed, backfill


def snapshot_symbols(symbols: list[str], today: str | None = None,
                     workers: int = 4, con=None) -> tuple[int, int]:
    """Fetch and store estimates for the given symbols. Returns (ok, fail)."""
    own = con is None
    con = con or db.core()
    today = today or date.today().isoformat()
    lock = threading.Lock()
    n_ok = n_fail = 0
    pending_obs: list[dict] = []
    pending_bf: list[dict] = []

    def flush():
        if pending_obs:
            con.executemany(_OBSERVED_SQL, pending_obs)
            pending_obs.clear()
        if pending_bf:
            con.executemany(_BACKFILL_SQL, pending_bf)
            pending_bf.clear()
        con.commit()

    def work(sym: str):
        try:
            est = yahoo.get_estimates(sym)
        except Exception as e:  # noqa: BLE001
            log.debug("%s failed: %s", sym, e)
            return sym, None
        return sym, est

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(work, s): s for s in symbols}
            for i, fut in enumerate(as_completed(futures), 1):
                sym, est = fut.result()
                if not est:
                    n_fail += 1
                else:
                    obs, bf = build_rows(sym, est, today)
                    with lock:
                        pending_obs.extend(obs)
                        pending_bf.extend(bf)
                    n_ok += 1

                if i % 200 == 0:
                    with lock:
                        flush()
                    log.info("  %d/%d  ok=%d fail=%d", i, len(symbols), n_ok, n_fail)
        with lock:
            flush()
    except KeyboardInterrupt:
        with lock:
            flush()
        log.warning("interrupted - flushed %d ok so far", n_ok)
        raise
    finally:
        if own:
            con.close()

    return n_ok, n_fail


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="ignore tiering and snapshot the whole universe")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--symbols", type=str, default="")
    args = ap.parse_args()

    started = datetime.now().isoformat(timespec="seconds")
    today = date.today().isoformat()

    with db.core_ctx() as con:
        if args.symbols:
            syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        else:
            syms, dtr = uni.symbols_due(con, today, force_all=args.all)
            log.info("tiering selected %d symbols", len(syms))
        if args.limit:
            syms = syms[: args.limit]

        log.info("snapshotting %d symbols with %d workers", len(syms), args.workers)
        n_ok, n_fail = snapshot_symbols(syms, today, args.workers, con)

        db.log_run(con, "snapshot", today, started,
                   datetime.now().isoformat(timespec="seconds"), n_ok, n_fail)

        tot = con.execute("SELECT COUNT(*) c FROM estimate_snapshots").fetchone()["c"]
        obs = con.execute("SELECT COUNT(*) c FROM estimate_snapshots "
                          "WHERE source='observed'").fetchone()["c"]
        span = con.execute("SELECT MIN(snap_date) a, MAX(snap_date) b "
                           "FROM estimate_snapshots").fetchone()
        log.info("done: ok=%d fail=%d", n_ok, n_fail)
        log.info("snapshot table: %d rows (%d observed, %d backfilled), %s..%s",
                 tot, obs, tot - obs, span["a"], span["b"])


if __name__ == "__main__":
    main()
