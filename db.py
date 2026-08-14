"""SQLite schema and helpers.

Two databases (see config): core.db holds the irreplaceable consensus history,
market.db holds re-downloadable price and options data.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import config

CORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS universe (
    symbol          TEXT PRIMARY KEY,
    name            TEXT,
    market_cap      REAL,
    last_price      REAL,
    first_seen      TEXT,
    last_seen       TEXT,
    has_options     INTEGER DEFAULT -1,   -- -1 unknown, 0 no, 1 yes
    delisted        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS earnings_calendar (
    symbol          TEXT NOT NULL,
    report_date     TEXT NOT NULL,
    session         TEXT,                 -- pre / post / unknown
    fiscal_quarter  TEXT,
    eps_forecast    REAL,
    n_estimates     INTEGER,
    confirmed       INTEGER DEFAULT 0,
    source          TEXT,
    first_seen      TEXT,
    last_updated    TEXT,
    PRIMARY KEY (symbol, report_date)
);
CREATE INDEX IF NOT EXISTS idx_cal_date ON earnings_calendar(report_date);

-- The moat. One row per symbol per observation date per forecast period.
-- 'observed' rows are captured live; 'backfill' rows are reconstructed from
-- Yahoo's eps_trend 7/30/60/90-day lookback on first contact with a ticker.
CREATE TABLE IF NOT EXISTS estimate_snapshots (
    symbol          TEXT NOT NULL,
    snap_date       TEXT NOT NULL,
    period          TEXT NOT NULL,        -- 0q, +1q, 0y, +1y
    eps_avg         REAL,
    eps_low         REAL,
    eps_high        REAL,
    eps_n_analysts  INTEGER,
    eps_year_ago    REAL,
    rev_avg         REAL,
    rev_n_analysts  INTEGER,
    rev_year_ago    REAL,
    up_7d           INTEGER,
    down_7d         INTEGER,
    up_30d          INTEGER,
    down_30d        INTEGER,
    source          TEXT NOT NULL,        -- observed | backfill
    PRIMARY KEY (symbol, snap_date, period)
);
CREATE INDEX IF NOT EXISTS idx_snap_symbol ON estimate_snapshots(symbol, period, snap_date);

CREATE TABLE IF NOT EXISTS earnings_history (
    symbol          TEXT NOT NULL,
    report_date     TEXT NOT NULL,
    report_ts       TEXT,
    eps_estimate    REAL,
    eps_actual      REAL,
    surprise_pct    REAL,
    PRIMARY KEY (symbol, report_date)
);
CREATE INDEX IF NOT EXISTS idx_hist_date ON earnings_history(report_date);

CREATE TABLE IF NOT EXISTS ingest_log (
    job             TEXT NOT NULL,
    run_date        TEXT NOT NULL,
    started         TEXT,
    finished        TEXT,
    n_ok            INTEGER,
    n_fail          INTEGER,
    notes           TEXT,
    PRIMARY KEY (job, run_date, started)
);
"""

MARKET_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    symbol          TEXT NOT NULL,
    date            TEXT NOT NULL,
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL,
    volume          REAL,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);

CREATE TABLE IF NOT EXISTS implied_moves (
    symbol          TEXT NOT NULL,
    snap_date       TEXT NOT NULL,
    expiry          TEXT,
    days_to_expiry  INTEGER,
    spot            REAL,
    atm_strike      REAL,
    straddle_mid    REAL,
    implied_move_pct REAL,
    atm_iv          REAL,
    n_contracts     INTEGER,
    PRIMARY KEY (symbol, snap_date)
);
"""


def connect(path: Path, schema: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    if schema:
        con.executescript(schema)
    return con


def core(init: bool = True) -> sqlite3.Connection:
    return connect(config.CORE_DB, CORE_SCHEMA if init else None)


def market(init: bool = True) -> sqlite3.Connection:
    return connect(config.MARKET_DB, MARKET_SCHEMA if init else None)


@contextmanager
def core_ctx():
    con = core()
    try:
        yield con
        con.commit()
    finally:
        con.close()


@contextmanager
def market_ctx():
    con = market()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def log_run(con, job: str, run_date: str, started: str, finished: str,
            n_ok: int, n_fail: int, notes: str = "") -> None:
    con.execute(
        "INSERT OR REPLACE INTO ingest_log VALUES (?,?,?,?,?,?,?)",
        (job, run_date, started, finished, n_ok, n_fail, notes),
    )


def init_all() -> None:
    core().close()
    market().close()


if __name__ == "__main__":
    init_all()
    print(f"initialised {config.CORE_DB}")
    print(f"initialised {config.MARKET_DB}")
