"""Price history ingest.

Lives in market.db, which is gitignored: this data is fully re-downloadable, so
committing gigabytes of it would be pointless. Only the consensus snapshots are
irreplaceable enough to version.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta

import pandas as pd

import config
import db
from providers import yahoo

log = logging.getLogger("pricedin.prices")


def _existing_max(con) -> dict[str, str]:
    rows = con.execute("SELECT symbol, MAX(date) m FROM prices GROUP BY symbol").fetchall()
    return {r["symbol"]: r["m"] for r in rows}


def ingest_prices(symbols: list[str], years: int | None = None,
                  incremental: bool = True) -> int:
    years = years or config.PRICE_HISTORY_YEARS
    full_start = (date.today() - timedelta(days=int(years * 365.25))).isoformat()

    mcon = db.market()
    ccon = None
    try:
        have = _existing_max(mcon) if incremental else {}
        total = 0

        for i in range(0, len(symbols), config.BATCH_SIZE):
            batch = symbols[i: i + config.BATCH_SIZE]

            # Split by how much history each name still needs so we are not
            # re-downloading 11 years for a name we updated yesterday.
            fresh = [s for s in batch if s not in have]
            stale = [s for s in batch if s in have]

            for group, start in ((fresh, full_start), (stale, None)):
                if not group:
                    continue
                if start is None:
                    earliest = min(have[s] for s in group)
                    start = (date.fromisoformat(earliest) - timedelta(days=5)).isoformat()
                    if start >= date.today().isoformat():
                        continue

                df = yahoo.get_prices(group, start)
                if df is None or df.empty:
                    continue
                df = df.dropna(subset=["close"])
                if df.empty:
                    continue

                mcon.executemany(
                    "INSERT OR REPLACE INTO prices "
                    "(symbol,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)",
                    df[["symbol", "date", "open", "high", "low", "close", "volume"]]
                    .itertuples(index=False, name=None),
                )
                total += len(df)

            mcon.commit()
            log.info("  prices %d/%d symbols, %d rows so far",
                     min(i + config.BATCH_SIZE, len(symbols)), len(symbols), total)

        return total
    finally:
        mcon.close()
        if ccon:
            ccon.close()


def load_prices(symbols: list[str] | None = None,
                start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Read prices back as a tidy DataFrame."""
    con = db.market(init=False)
    try:
        q = "SELECT symbol,date,open,high,low,close,volume FROM prices WHERE 1=1"
        params: list = []
        if symbols:
            q += f" AND symbol IN ({','.join('?' * len(symbols))})"
            params += symbols
        if start:
            q += " AND date >= ?"
            params.append(start)
        if end:
            q += " AND date <= ?"
            params.append(end)
        df = pd.read_sql_query(q, con, params=params)
    finally:
        con.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    return df


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--years", type=int, default=config.PRICE_HISTORY_YEARS)
    ap.add_argument("--full", action="store_true", help="re-download from scratch")
    ap.add_argument("--symbols", type=str, default="")
    args = ap.parse_args()

    started = datetime.now().isoformat(timespec="seconds")
    with db.core_ctx() as con:
        if args.symbols:
            syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        else:
            syms = [r["symbol"] for r in con.execute(
                "SELECT symbol FROM universe WHERE delisted=0 "
                "ORDER BY market_cap DESC")]
        if args.limit:
            syms = syms[: args.limit]

        log.info("ingesting prices for %d symbols", len(syms))
        n = ingest_prices(syms, args.years, incremental=not args.full)
        db.log_run(con, "prices", date.today().isoformat(), started,
                   datetime.now().isoformat(timespec="seconds"), n, 0)
        log.info("wrote %d price rows", n)


if __name__ == "__main__":
    main()
