"""Paper trading engine.

Runs several books side by side over the same events, each with its own cash,
positions and equity curve. That is the whole design point: a single book that
made 4% tells you nothing, because you cannot tell skill from a rising market.
Two of the books exist purely as yardsticks —

    random      picks the same number of trades from the same eligible pool,
                at random, with the same sizing and costs
    spy_hold    buys SPY on day one and never trades again

— so the only question that matters, "is the stance column worth anything?",
gets answered by the gap between the strategy books and those two.

Fills are taken from daily OHLC with gaps handled honestly:
  * a stop is checked against the LOW (long) or HIGH (short), but if the bar
    OPENED beyond the stop the fill is the open, not the stop price. This is
    what actually happens on an earnings gap and it is where naive backtests
    invent money that does not exist.
  * if a bar touches both the stop and the target, the stop is assumed first.
  * costs are charged on entry and exit.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

import config
import db
import levels as lv

log = logging.getLogger("pricedin.paper")

PAPER_DB = config.DATA / "paper.db"
STARTING_CASH = 100_000.0
COST_BPS = 20.0            # round trip, split across entry and exit
SLIPPAGE_BPS = 5.0         # each side, on top of cost

PAPER_SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    book            TEXT PRIMARY KEY,
    description     TEXT,
    starting_cash   REAL,
    created         TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    book            TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,          -- long | short
    style           TEXT,
    qty             REAL,
    entry_date      TEXT,
    entry_price     REAL,
    tp              REAL,
    sl              REAL,
    planned_exit    TEXT,
    event_date      TEXT,
    status          TEXT DEFAULT 'open',    -- open | closed
    exit_date       TEXT,
    exit_price      REAL,
    exit_reason     TEXT,                   -- tp | sl | time | gap_sl
    gross_pnl       REAL,
    costs           REAL,
    pnl             REAL,
    ret_pct         REAL,
    -- 'replay' rows are deterministic output of paper_replay.py and can be
    -- rebuilt from the event panel at any time. 'live' rows record a decision
    -- taken at a particular day's close and can never be reconstructed, so
    -- they are the only ones worth committing.
    source          TEXT DEFAULT 'live'
);
CREATE INDEX IF NOT EXISTS idx_pos_book ON positions(book, status);
CREATE INDEX IF NOT EXISTS idx_pos_sym  ON positions(symbol, entry_date);

CREATE TABLE IF NOT EXISTS equity (
    book            TEXT NOT NULL,
    date            TEXT NOT NULL,
    cash            REAL,
    positions_value REAL,
    equity          REAL,
    n_open          INTEGER,
    PRIMARY KEY (book, date)
);
"""

BOOKS = {
    "stance_long": "Buys every name the dashboard rates favourable, held "
                   "through the print.",
    "stance_short": "Shorts every name rated unfavourable, held through the "
                    "print.",
    "drift_long": "Buys after a >5% beat, entering at the reaction close and "
                  "holding 5 sessions with a stop.",
    "cheap_vol": "Buys names where the options market is charging LESS than "
                 "the move model predicts — the closest spot-only proxy for "
                 "the one edge that survived holdout.",
    "random": "CONTROL. Same number of trades, same sizing, same costs, picked "
              "at random from the eligible pool.",
    "spy_hold": "BENCHMARK. Buys SPY once and holds.",
}


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(PAPER_DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.executescript(PAPER_SCHEMA)
    # Migration for databases created before `source` existed.
    cols = {r["name"] for r in con.execute("PRAGMA table_info(positions)")}
    if "source" not in cols:
        con.execute("ALTER TABLE positions ADD COLUMN source TEXT DEFAULT 'live'")
        con.commit()
    return con


def init_books(con, starting_cash: float = STARTING_CASH) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    con.executemany(
        "INSERT OR IGNORE INTO books VALUES (?,?,?,?)",
        [(b, d, starting_cash, now) for b, d in BOOKS.items()],
    )
    con.commit()


# ------------------------------------------------------------------- prices
class PriceCache:
    """Daily OHLC keyed by symbol, with fast as-of lookups."""

    def __init__(self, symbols: list[str], start: str, end: str | None = None):
        from ingest.prices import load_prices
        df = load_prices(sorted(set(symbols)), start=start, end=end)
        self.by: dict[str, pd.DataFrame] = {}
        for s, g in df.groupby("symbol"):
            g = g.sort_values("date").reset_index(drop=True)
            self.by[s] = g

    def bars_after(self, symbol: str, after: str, n: int = 40) -> pd.DataFrame:
        g = self.by.get(symbol)
        if g is None:
            return pd.DataFrame()
        m = g[g["date"] > pd.Timestamp(after)]
        return m.head(n)

    def close_on_or_before(self, symbol: str, d: str) -> tuple[str, float] | None:
        g = self.by.get(symbol)
        if g is None:
            return None
        m = g[g["date"] <= pd.Timestamp(d)]
        if m.empty:
            return None
        r = m.iloc[-1]
        return str(r["date"])[:10], float(r["close"])

    def close_at(self, symbol: str, d: str) -> float | None:
        g = self.by.get(symbol)
        if g is None:
            return None
        m = g[g["date"] == pd.Timestamp(d)]
        return float(m.iloc[0]["close"]) if not m.empty else None


# -------------------------------------------------------------------- fills
@dataclass
class Fill:
    date: str
    price: float
    reason: str


def simulate_exit(bars: pd.DataFrame, side: str, tp: float | None,
                  sl: float | None, hold_days: int) -> Fill | None:
    """Walk forward bar by bar and find where the position actually closes.

    Gap logic is the point of this function. If the bar opens through the stop,
    the fill is the open — you do not get your stop price. Skipping this is how
    a backtest turns a 12% gap into a tidy 5% loss.
    """
    if bars.empty:
        return None

    for i, (_, b) in enumerate(bars.iterrows()):
        d = str(b["date"])[:10]
        o, h, l, c = (float(b["open"]), float(b["high"]),
                      float(b["low"]), float(b["close"]))

        if side == "long":
            if sl is not None:
                if o <= sl:
                    return Fill(d, o, "gap_sl")
                if l <= sl:
                    return Fill(d, sl, "sl")
            if tp is not None:
                if o >= tp:
                    return Fill(d, o, "gap_tp")
                if h >= tp:
                    return Fill(d, tp, "tp")
        else:
            if sl is not None:
                if o >= sl:
                    return Fill(d, o, "gap_sl")
                if h >= sl:
                    return Fill(d, sl, "sl")
            if tp is not None:
                if o <= tp:
                    return Fill(d, o, "gap_tp")
                if l <= tp:
                    return Fill(d, tp, "tp")

        if i + 1 >= hold_days:
            return Fill(d, c, "time")

    last = bars.iloc[-1]
    return Fill(str(last["date"])[:10], float(last["close"]), "time")


def record_trade(con, book: str, symbol: str, side: str, style: str,
                 qty: float, entry_date: str, entry_price: float,
                 exit_fill: Fill, tp: float | None, sl: float | None,
                 event_date: str | None, source: str = "replay") -> float:
    """Book a completed round trip and return its net P&L."""
    direction = 1 if side == "long" else -1
    gross = direction * (exit_fill.price - entry_price) * qty
    notional_in = abs(entry_price * qty)
    notional_out = abs(exit_fill.price * qty)
    costs = ((notional_in + notional_out) / 2) * \
            ((COST_BPS + 2 * SLIPPAGE_BPS) / 10_000)
    pnl = gross - costs
    ret = pnl / notional_in * 100 if notional_in else 0.0

    con.execute(
        """INSERT INTO positions
           (book, symbol, side, style, qty, entry_date, entry_price, tp, sl,
            planned_exit, event_date, status, exit_date, exit_price,
            exit_reason, gross_pnl, costs, pnl, ret_pct, source)
           VALUES (?,?,?,?,?,?,?,?,?,?,?, 'closed', ?,?,?,?,?,?,?,?)""",
        (book, symbol, side, style, qty, entry_date, entry_price, tp, sl,
         None, event_date, exit_fill.date, exit_fill.price, exit_fill.reason,
         gross, costs, pnl, ret, source),
    )
    return pnl


# ----------------------------------------------------------------- selection
def eligible(scorecard: pd.DataFrame) -> pd.DataFrame:
    df = scorecard.copy()
    if "verdict" in df.columns:
        df["stance_score"] = df["verdict"].apply(
            lambda v: v.get("score", 0) if isinstance(v, dict) else 0)
    else:
        df["stance_score"] = 0
    return df[df["price"].notna()]


def select_for_book(book: str, df: pd.DataFrame, rng, model) -> pd.DataFrame:
    if book == "stance_long":
        return df[df["stance_score"] >= 1]
    if book == "stance_short":
        return df[df["stance_score"] <= -1]
    if book == "cheap_vol":
        sub = df[df["implied_move_pct"].notna()].copy()
        if sub.empty:
            return sub
        preds = []
        for _, r in sub.iterrows():
            preds.append(lv.predict_move(
                model, r.get("realised_move_med_8"),
                r.get("realised_move_max_8"), r.get("vol_20d")))
        sub["pred_move"] = preds
        sub = sub[sub["pred_move"].notna()]
        # Options underpricing the model's expectation -> own the move.
        return sub[sub["implied_move_pct"] / sub["pred_move"] <= 0.85]
    if book == "drift_long":
        return df.iloc[0:0]     # handled separately, needs the reaction first
    return df


# ------------------------------------------------------------------ equity
def mark_equity(con, px: PriceCache, on_date: str) -> None:
    for b in con.execute("SELECT book, starting_cash FROM books").fetchall():
        book, cash0 = b["book"], b["starting_cash"]
        realised = con.execute(
            "SELECT COALESCE(SUM(pnl),0) s FROM positions "
            "WHERE book=? AND status='closed' AND exit_date<=?",
            (book, on_date)).fetchone()["s"]

        open_rows = con.execute(
            "SELECT symbol, side, qty, entry_price FROM positions "
            "WHERE book=? AND status='open'", (book,)).fetchall()
        mtm = 0.0
        for r in open_rows:
            c = px.close_on_or_before(r["symbol"], on_date)
            if not c or r["qty"] is None or r["entry_price"] is None:
                continue
            direction = 1 if r["side"] == "long" else -1
            mtm += direction * (c[1] - r["entry_price"]) * r["qty"]

        equity = cash0 + realised + mtm
        con.execute(
            "INSERT OR REPLACE INTO equity VALUES (?,?,?,?,?,?)",
            (book, on_date, cash0 + realised, mtm, equity, len(open_rows)),
        )
    con.commit()


# ------------------------------------------------------------------ reporting
def summary(con) -> pd.DataFrame:
    rows = []
    for b in con.execute("SELECT book, starting_cash, description FROM books"):
        book, cash0 = b["book"], b["starting_cash"]
        t = con.execute(
            """SELECT COUNT(*) n, COALESCE(SUM(pnl),0) pnl,
                      COALESCE(AVG(ret_pct),0) avg_ret,
                      COALESCE(SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END),0) wins,
                      COALESCE(SUM(costs),0) costs
               FROM positions WHERE book=? AND status='closed'""",
            (book,)).fetchone()
        eq = con.execute(
            "SELECT equity FROM equity WHERE book=? ORDER BY date DESC LIMIT 1",
            (book,)).fetchone()
        curve = pd.read_sql_query(
            "SELECT date, equity FROM equity WHERE book=? ORDER BY date",
            con, params=(book,))
        sharpe = float("nan")
        maxdd = float("nan")
        if len(curve) > 5:
            r = curve["equity"].pct_change().dropna()
            if r.std() > 0:
                sharpe = float(r.mean() / r.std() * np.sqrt(252))
            peak = curve["equity"].cummax()
            maxdd = float(((curve["equity"] - peak) / peak).min() * 100)

        equity = eq["equity"] if eq else cash0
        rows.append({
            "book": book,
            "trades": t["n"],
            "hit_rate": (t["wins"] / t["n"]) if t["n"] else float("nan"),
            "avg_ret_pct": t["avg_ret"],
            "net_pnl": t["pnl"],
            "costs_paid": t["costs"],
            "equity": equity,
            "return_pct": (equity / cash0 - 1) * 100,
            "sharpe": sharpe,
            "max_dd_pct": maxdd,
        })
    return pd.DataFrame(rows)


# -------------------------------------------------------------- live trading
MAX_CONCURRENT = 20
RISK_BUDGET = 0.5
MAX_POSITION = 5.0


def close_due(con, px: PriceCache, today: str) -> int:
    """Close any open position whose exit condition has now been met."""
    # Discard any position that was written without a usable quantity. These
    # can only come from a NaN sizing input, they can never be marked or
    # closed, and leaving them would quietly corrupt every equity reading.
    bad = con.execute(
        "DELETE FROM positions WHERE status='open' "
        "AND (qty IS NULL OR entry_price IS NULL)").rowcount
    if bad:
        log.warning("dropped %d open position(s) with no usable size", bad)
        con.commit()

    rows = con.execute(
        "SELECT * FROM positions WHERE status='open'").fetchall()
    n = 0
    for r in rows:
        hold = 5 if r["style"] == "post_print_drift" else 1
        bars = px.bars_after(r["symbol"], r["entry_date"], 40)
        bars = bars[bars["date"] <= pd.Timestamp(today)]
        if bars.empty:
            continue
        fill = simulate_exit(bars, r["side"], r["tp"], r["sl"], hold)
        if fill is None:
            continue

        direction = 1 if r["side"] == "long" else -1
        gross = direction * (fill.price - r["entry_price"]) * r["qty"]
        nin = abs(r["entry_price"] * r["qty"])
        nout = abs(fill.price * r["qty"])
        costs = ((nin + nout) / 2) * ((COST_BPS + 2 * SLIPPAGE_BPS) / 10_000)
        pnl = gross - costs
        con.execute(
            """UPDATE positions SET status='closed', exit_date=?, exit_price=?,
               exit_reason=?, gross_pnl=?, costs=?, pnl=?, ret_pct=?
               WHERE id=?""",
            (fill.date, fill.price, fill.reason, gross, costs, pnl,
             pnl / nin * 100 if nin else 0.0, r["id"]),
        )
        n += 1
    con.commit()
    return n


def open_new(con, px: PriceCache, scorecard: pd.DataFrame, model,
             today: str, rng) -> int:
    """Open positions for names whose entry session is today.

    A name reporting after today's close is entered at today's close. A name
    reporting before tomorrow's open is also entered at today's close — in both
    cases today's close is the last price that does not know the result.
    """
    import levels as lv

    df = eligible(scorecard)
    if df.empty:
        return 0
    tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
    entering = df[
        ((df["session"] == "post") & (df["report_date"] == today))
        | ((df["session"] == "pre") & (df["report_date"] == tomorrow))
    ]
    if entering.empty:
        return 0

    n = 0
    for book in BOOKS:
        if book == "spy_hold":
            continue
        if book == "random":
            k = min(3, len(entering))
            sel = entering.sample(n=k, random_state=int(rng.integers(1e6))) \
                if k else entering.iloc[0:0]
        else:
            sel = select_for_book(book, entering, rng, model)
        if sel.empty:
            continue

        n_open = con.execute(
            "SELECT COUNT(*) c FROM positions WHERE book=? AND status='open'",
            (book,)).fetchone()["c"]
        realised = con.execute(
            "SELECT COALESCE(SUM(pnl),0) s FROM positions "
            "WHERE book=? AND status='closed'", (book,)).fetchone()["s"]
        cash0 = con.execute(
            "SELECT starting_cash c FROM books WHERE book=?",
            (book,)).fetchone()["c"]
        equity = cash0 + realised

        side = "short" if book == "stance_short" else "long"
        for _, r in sel.iterrows():
            if n_open >= MAX_CONCURRENT or equity <= 0:
                break
            sym = r["symbol"]
            if con.execute(
                "SELECT 1 FROM positions WHERE book=? AND symbol=? "
                "AND status='open'", (book, sym)).fetchone():
                continue

            import sizing
            price = sizing._finite(r.get("price"))
            pred = sizing._finite(lv.predict_move(
                model, r.get("realised_move_med_8"),
                r.get("realised_move_max_8"),
                r.get("vol_20d"), r.get("implied_move_pct")))
            if not price or price <= 0 or not pred:
                continue
            size_pct = sizing.vol_target_size(
                pred, risk_budget_pct=RISK_BUDGET,
                max_position_pct=MAX_POSITION).position_pct
            qty = (equity * size_pct / 100.0) / price
            # Belt and braces: a NaN here would be stored as NULL and only
            # blow up later, in mark_equity, far from the cause.
            if size_pct <= 0 or not sizing._finite(qty) or qty <= 0:
                continue

            con.execute(
                """INSERT INTO positions
                   (book, symbol, side, style, qty, entry_date, entry_price,
                    tp, sl, planned_exit, event_date, status, source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?, 'open', 'live')""",
                (book, sym, side, "through_print", qty, today, float(price),
                 None, None, None, str(r["report_date"])[:10]),
            )
            n_open += 1
            n += 1
    con.commit()
    return n


def run_live(scorecard: pd.DataFrame, today: str | None = None) -> dict:
    """One day of live paper trading. Safe to run more than once per day."""
    import levels as lv

    today = today or date.today().isoformat()
    rng = np.random.default_rng()
    model = lv.load_move_model()

    con = connect()
    try:
        init_books(con)
        symbols = sorted(set(scorecard["symbol"].tolist())) + ["SPY"]
        held = [r["symbol"] for r in
                con.execute("SELECT DISTINCT symbol FROM positions "
                            "WHERE status='open'")]
        px = PriceCache(sorted(set(symbols + held)),
                        start=(date.fromisoformat(today) -
                               timedelta(days=120)).isoformat())

        n_closed = close_due(con, px, today)
        n_opened = open_new(con, px, scorecard, model, today, rng) if model else 0
        mark_equity(con, px, today)
        s = summary(con)
    finally:
        con.close()
    return {"closed": n_closed, "opened": n_opened, "summary": s}


# ------------------------------------------------------------ persistence
# paper.db is gitignored because it is large and mostly regenerable, but the
# live trades are not: once a position has been opened at a given day's close,
# that decision cannot be reconstructed later. Same reasoning as the consensus
# snapshots — archive the irreplaceable part as a compressed CSV and commit it,
# so a cache miss on a cold runner cannot silently restart the portfolio at
# zero and pretend nothing happened.
PAPER_ARCHIVE = config.DATA / "paper_history.csv.gz"
EQUITY_ARCHIVE = config.DATA / "paper_equity.csv.gz"

_POS_COLS = [
    "book", "symbol", "side", "style", "qty", "entry_date", "entry_price",
    "tp", "sl", "planned_exit", "event_date", "status", "exit_date",
    "exit_price", "exit_reason", "gross_pnl", "costs", "pnl", "ret_pct",
    "source",
]
_EQ_COLS = ["book", "date", "cash", "positions_value", "equity", "n_open"]


def export_archive() -> tuple[int, int]:
    """Archive the live trades and the full equity curve.

    Replay trades are excluded: 18,944 of them compress to 1.3MB, they would be
    recommitted every day, and `paper_replay.py` regenerates them exactly from
    a fixed seed. The equity curve IS kept in full, because it is what the
    portfolio chart draws and it is only tens of KB.
    """
    import csv
    import gzip

    con = connect()
    try:
        pos = con.execute(
            f"SELECT {', '.join(_POS_COLS)} FROM positions "
            f"WHERE source = 'live' ORDER BY entry_date, id").fetchall()
        eq = con.execute(
            f"SELECT {', '.join(_EQ_COLS)} FROM equity ORDER BY date, book"
        ).fetchall()
    finally:
        con.close()

    for path, cols, rows in ((PAPER_ARCHIVE, _POS_COLS, pos),
                             (EQUITY_ARCHIVE, _EQ_COLS, eq)):
        with gzip.open(path, "wt", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            w.writerows([tuple(r) for r in rows])
    return len(pos), len(eq)


def import_archive() -> tuple[int, int]:
    import csv
    import gzip

    def read(path, cols):
        if not path.exists():
            return []
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return [
                tuple(None if r.get(c) in ("", None) else r.get(c) for c in cols)
                for r in csv.DictReader(fh)
            ]

    pos = read(PAPER_ARCHIVE, _POS_COLS)
    eq = read(EQUITY_ARCHIVE, _EQ_COLS)

    con = connect()
    try:
        init_books(con)
        if pos:
            # Only clear live rows — any replay history already rebuilt on this
            # runner must survive, since the archive deliberately omits it.
            con.execute("DELETE FROM positions WHERE source = 'live'")
            con.executemany(
                f"INSERT INTO positions ({', '.join(_POS_COLS)}) "
                f"VALUES ({', '.join('?' * len(_POS_COLS))})", pos)
        if eq:
            con.executemany(
                f"INSERT OR REPLACE INTO equity ({', '.join(_EQ_COLS)}) "
                f"VALUES ({', '.join('?' * len(_EQ_COLS))})", eq)
        con.commit()
    finally:
        con.close()
    return len(pos), len(eq)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--import", dest="do_import", action="store_true")
    args = ap.parse_args()

    if args.export:
        p, e = export_archive()
        print(f"archived {p} positions, {e} equity rows -> {PAPER_ARCHIVE.name}, "
              f"{EQUITY_ARCHIVE.name}")
        return
    if args.do_import:
        p, e = import_archive()
        print(f"restored {p} positions, {e} equity rows")
        return

    con = connect()
    init_books(con)
    if args.summary:
        s = summary(con)
        pd.set_option("display.width", 200)
        print(s.round(2).to_string(index=False))
    con.close()


if __name__ == "__main__":
    main()
