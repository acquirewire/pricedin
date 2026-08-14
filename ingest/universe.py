"""Build and maintain the tradeable universe, and decide what to refresh today.

Free APIs are rate limited, so the refresh list is driven by urgency: a name
reporting next week is worth a daily estimate snapshot, one reporting in three
months is not.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta

import config
import db
from providers import nasdaq

log = logging.getLogger("pricedin.universe")


def refresh_universe(con=None) -> int:
    """Pull the screener and upsert. Stale names get flagged delisted."""
    own = con is None
    con = con or db.core()
    try:
        rows = nasdaq.fetch_universe()
        if not rows:
            log.error("screener returned nothing - leaving universe untouched")
            return 0

        today = date.today().isoformat()
        con.executemany(
            """
            INSERT INTO universe (symbol, name, market_cap, last_price,
                                  first_seen, last_seen)
            VALUES (:symbol, :name, :market_cap, :last_price, :today, :today)
            ON CONFLICT(symbol) DO UPDATE SET
                name        = excluded.name,
                market_cap  = excluded.market_cap,
                last_price  = excluded.last_price,
                last_seen   = excluded.last_seen,
                delisted    = 0
            """,
            [{**r, "today": today} for r in rows],
        )
        # Anything absent from the screener for two weeks has probably gone.
        cutoff = (date.today() - timedelta(days=14)).isoformat()
        con.execute("UPDATE universe SET delisted=1 WHERE last_seen < ?", (cutoff,))
        con.commit()
        log.info("universe: %d symbols", len(rows))
        return len(rows)
    finally:
        if own:
            con.close()


def _next_report_dates(con, today: str) -> dict[str, str]:
    """Symbol -> nearest upcoming (or very recent) report date."""
    horizon = (date.fromisoformat(today) + timedelta(days=400)).isoformat()
    floor = (date.fromisoformat(today) - timedelta(days=3)).isoformat()
    rows = con.execute(
        """
        SELECT symbol, MIN(report_date) AS rd
        FROM earnings_calendar
        WHERE report_date BETWEEN ? AND ?
        GROUP BY symbol
        """,
        (floor, horizon),
    ).fetchall()
    return {r["symbol"]: r["rd"] for r in rows}


def symbols_due(con=None, today: str | None = None,
                force_all: bool = False) -> tuple[list[str], dict[str, int]]:
    """Which symbols to snapshot today, and how many days out each reports.

    Tier A (<=21d to report): every day.
    Tier B (<=60d):           Mondays and Thursdays.
    Tier C (everything else): Sundays.

    Returns (symbols, {symbol: days_to_report or 9999}).
    """
    own = con is None
    con = con or db.core()
    try:
        today = today or date.today().isoformat()
        td = date.fromisoformat(today)
        weekday = td.weekday()  # 0=Mon

        universe = [r["symbol"] for r in con.execute(
            "SELECT symbol FROM universe WHERE delisted=0").fetchall()]
        nxt = _next_report_dates(con, today)

        dtr: dict[str, int] = {}
        for s in universe:
            rd = nxt.get(s)
            dtr[s] = (date.fromisoformat(rd) - td).days if rd else 9999

        if force_all:
            return sorted(universe, key=lambda s: dtr[s]), dtr

        due = []
        for s in universe:
            d = dtr[s]
            if d <= config.TIER_A_DAYS:
                due.append(s)
            elif d <= config.TIER_B_DAYS and weekday in (0, 3):
                due.append(s)
            elif weekday == 6:
                due.append(s)

        due.sort(key=lambda s: dtr[s])
        return due, dtr
    finally:
        if own:
            con.close()


def tier_of(days_to_report: int) -> str:
    if days_to_report <= config.TIER_A_DAYS:
        return "A"
    if days_to_report <= config.TIER_B_DAYS:
        return "B"
    return "C"


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--show-due", action="store_true")
    args = ap.parse_args()

    started = datetime.now().isoformat(timespec="seconds")
    n = refresh_universe()
    with db.core_ctx() as con:
        db.log_run(con, "universe", date.today().isoformat(), started,
                   datetime.now().isoformat(timespec="seconds"), n, 0)
        if args.show_due:
            due, dtr = symbols_due(con)
            print(f"due today: {len(due)}")
            for s in due[:25]:
                print(f"  {s:<6} T-{dtr[s]}")


if __name__ == "__main__":
    main()
