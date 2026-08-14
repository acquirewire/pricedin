"""Rolling earnings calendar sweep.

We keep a little history behind us as well as the lookahead, because companies
move their report dates and we want to notice when they do — a date slip is
itself information.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import config
import db
from providers import nasdaq

log = logging.getLogger("pricedin.calendar")


def refresh_calendar(con=None, lookback: int | None = None,
                     lookahead: int | None = None) -> int:
    own = con is None
    con = con or db.core()
    try:
        lookback = config.CALENDAR_LOOKBACK_DAYS if lookback is None else lookback
        lookahead = config.CALENDAR_LOOKAHEAD_DAYS if lookahead is None else lookahead
        start = date.today() - timedelta(days=lookback)
        end = date.today() + timedelta(days=lookahead)

        rows = nasdaq.fetch_calendar_range(start, end)
        if not rows:
            log.error("calendar returned nothing")
            return 0

        # Only keep names we actually track, so the calendar cannot smuggle
        # sub-$500m junk into the universe through the back door.
        known = {r["symbol"] for r in
                 con.execute("SELECT symbol FROM universe WHERE delisted=0")}
        rows = [r for r in rows if r["symbol"] in known]

        now = datetime.now().isoformat(timespec="seconds")
        con.executemany(
            """
            INSERT INTO earnings_calendar
                (symbol, report_date, session, fiscal_quarter, eps_forecast,
                 n_estimates, confirmed, source, first_seen, last_updated)
            VALUES
                (:symbol, :report_date, :session, :fiscal_quarter, :eps_forecast,
                 :n_estimates, 0, :source, :now, :now)
            ON CONFLICT(symbol, report_date) DO UPDATE SET
                session        = excluded.session,
                fiscal_quarter = COALESCE(excluded.fiscal_quarter, fiscal_quarter),
                eps_forecast   = COALESCE(excluded.eps_forecast, eps_forecast),
                n_estimates    = MAX(excluded.n_estimates, n_estimates),
                last_updated   = excluded.last_updated
            """,
            [{**r, "now": now} for r in rows],
        )
        con.commit()
        log.info("calendar: %d rows across %s..%s", len(rows), start, end)
        return len(rows)
    finally:
        if own:
            con.close()


def upcoming(con, days: int = 21) -> list[dict]:
    """Calendar entries in the next N days, joined to universe metadata."""
    today = date.today().isoformat()
    end = (date.today() + timedelta(days=days)).isoformat()
    rows = con.execute(
        """
        SELECT c.symbol, c.report_date, c.session, c.fiscal_quarter,
               c.eps_forecast, c.n_estimates, u.name, u.market_cap
        FROM earnings_calendar c
        JOIN universe u ON u.symbol = c.symbol
        WHERE c.report_date BETWEEN ? AND ? AND u.delisted = 0
        ORDER BY c.report_date, u.market_cap DESC
        """,
        (today, end),
    ).fetchall()
    return [dict(r) for r in rows]


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    started = datetime.now().isoformat(timespec="seconds")
    with db.core_ctx() as con:
        n = refresh_calendar(con)
        db.log_run(con, "calendar", date.today().isoformat(), started,
                   datetime.now().isoformat(timespec="seconds"), n, 0)
        nxt = upcoming(con, 14)
        print(f"{len(nxt)} tracked names reporting in the next 14 days")
        for r in nxt[:20]:
            mc = (r["market_cap"] or 0) / 1e9
            print(f"  {r['report_date']}  {r['symbol']:<6} {r['session']:<7} "
                  f"${mc:>7.1f}b  est {r['eps_forecast']}")


if __name__ == "__main__":
    main()
