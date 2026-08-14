"""Yahoo Finance provider (via yfinance).

Free and unofficial, so every call is wrapped in retry/backoff and every parse
is defensive — Yahoo changes shapes without warning and a single bad ticker
must never take down a 3,000-name sweep.
"""
from __future__ import annotations

import logging
import time
import warnings
from datetime import date, datetime, timedelta

import pandas as pd

import config

warnings.filterwarnings("ignore")
log = logging.getLogger("pricedin.yahoo")

_yf = None


def _lazy_yf():
    global _yf
    if _yf is None:
        import yfinance as yf
        _yf = yf
    return _yf


def _retry(fn, *args, **kwargs):
    """Call fn with backoff. Returns None rather than raising."""
    last = None
    for attempt in range(config.YF_MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - any failure is a retry candidate
            last = e
            if attempt < config.YF_MAX_RETRIES - 1:
                time.sleep(config.YF_BACKOFF ** attempt)
    log.debug("giving up after %d attempts: %s", config.YF_MAX_RETRIES, last)
    return None


def _f(v):
    """Coerce to float, mapping Yahoo's many flavours of missing to None."""
    if v is None:
        return None
    try:
        if isinstance(v, str):
            v = v.replace(",", "").replace("$", "").strip()
            if v in ("", "N/A", "-", "--"):
                return None
        f = float(v)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _i(v):
    f = _f(v)
    return None if f is None else int(f)


# --------------------------------------------------------------- estimates
def get_estimates(symbol: str) -> dict | None:
    """Consensus EPS/revenue by period, with Yahoo's 7/30/60/90d lookback.

    The lookback is the important part: it lets us reconstruct three months of
    revision history the first time we ever see a ticker, instead of waiting a
    quarter to accumulate it.

    Returns {period: {...}} for periods 0q, +1q, 0y, +1y.
    """
    yf = _lazy_yf()
    t = _retry(yf.Ticker, symbol)
    if t is None:
        return None

    def grab(attr):
        try:
            df = getattr(t, attr)
            if isinstance(df, pd.DataFrame) and not df.empty:
                return df
        except Exception:  # noqa: BLE001
            pass
        return None

    est = grab("earnings_estimate")
    rev = grab("revenue_estimate")
    trend = grab("eps_trend")
    revis = grab("eps_revisions")

    if est is None and trend is None:
        return None

    periods = set()
    for df in (est, rev, trend, revis):
        if df is not None:
            periods.update(str(p) for p in df.index)
    if not periods:
        return None

    out: dict[str, dict] = {}
    for p in periods:
        row: dict = {"period": p}

        if est is not None and p in est.index:
            r = est.loc[p]
            row.update(
                eps_avg=_f(r.get("avg")),
                eps_low=_f(r.get("low")),
                eps_high=_f(r.get("high")),
                eps_n_analysts=_i(r.get("numberOfAnalysts")),
                eps_year_ago=_f(r.get("yearAgoEps")),
            )
        if rev is not None and p in rev.index:
            r = rev.loc[p]
            row.update(
                rev_avg=_f(r.get("avg")),
                rev_n_analysts=_i(r.get("numberOfAnalysts")),
                rev_year_ago=_f(r.get("yearAgoRevenue")),
            )
        if trend is not None and p in trend.index:
            r = trend.loc[p]
            row["trend"] = {
                0: _f(r.get("current")),
                7: _f(r.get("7daysAgo")),
                30: _f(r.get("30daysAgo")),
                60: _f(r.get("60daysAgo")),
                90: _f(r.get("90daysAgo")),
            }
        if revis is not None and p in revis.index:
            r = revis.loc[p]
            row.update(
                up_7d=_i(r.get("upLast7days")),
                down_7d=_i(r.get("downLast7Days") if "downLast7Days" in r
                           else r.get("downLast7days")),
                up_30d=_i(r.get("upLast30days")),
                down_30d=_i(r.get("downLast30days")),
            )
        out[p] = row

    time.sleep(config.YF_SLEEP)
    return out


# --------------------------------------------------------- earnings history
def get_earnings_history(symbol: str, limit: int = 48) -> list[dict]:
    """Past EPS estimate vs actual. Rows with no actual are future dates."""
    yf = _lazy_yf()
    t = _retry(yf.Ticker, symbol)
    if t is None:
        return []
    df = _retry(t.get_earnings_dates, limit=limit)
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []

    rows = []
    for ts, r in df.iterrows():
        try:
            d = pd.Timestamp(ts)
        except Exception:  # noqa: BLE001
            continue
        actual = _f(r.get("Reported EPS"))
        rows.append({
            "symbol": symbol,
            "report_date": d.date().isoformat(),
            "report_ts": d.isoformat(),
            "eps_estimate": _f(r.get("EPS Estimate")),
            "eps_actual": actual,
            "surprise_pct": _f(r.get("Surprise(%)")),
            "is_future": actual is None,
        })
    time.sleep(config.YF_SLEEP)
    return rows


# ------------------------------------------------------------------ prices
def get_prices(symbols: list[str], start: str, end: str | None = None) -> pd.DataFrame:
    """Batch OHLCV. Returns long format: symbol,date,open,high,low,close,volume."""
    yf = _lazy_yf()
    if not symbols:
        return pd.DataFrame()

    raw = _retry(
        yf.download, tickers=symbols, start=start, end=end,
        auto_adjust=True, progress=False, threads=True, group_by="column",
    )
    if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty:
        return pd.DataFrame()

    # Single ticker comes back with flat columns; multi comes back MultiIndex.
    if not isinstance(raw.columns, pd.MultiIndex):
        raw = raw.copy()
        raw.columns = pd.MultiIndex.from_product([raw.columns, [symbols[0]]])

    frames = []
    for sym in {c[1] for c in raw.columns}:
        try:
            sub = raw.xs(sym, axis=1, level=1)
        except KeyError:
            continue
        sub = sub.dropna(how="all")
        if sub.empty:
            continue
        sub = sub.reset_index()
        sub.columns = [str(c).lower() for c in sub.columns]
        sub["symbol"] = sym
        frames.append(sub)

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.date.astype(str)
    keep = ["symbol", "date", "open", "high", "low", "close", "volume"]
    for c in keep:
        if c not in out.columns:
            out[c] = None
    return out[keep]


# ----------------------------------------------------------- implied move
def get_implied_move(symbol: str, after_date: str | None = None) -> dict | None:
    """ATM straddle on the first expiry after the earnings date.

    implied_move_pct is the straddle mid as a percentage of spot — roughly what
    the options market is pricing as the one-sigma move through the print.
    """
    yf = _lazy_yf()
    t = _retry(yf.Ticker, symbol)
    if t is None:
        return None

    try:
        expiries = list(t.options or [])
    except Exception:  # noqa: BLE001
        return None
    if not expiries:
        return None

    cutoff = date.fromisoformat(after_date) if after_date else date.today()
    target = next((e for e in expiries if date.fromisoformat(e) >= cutoff), None)
    if target is None:
        return None

    chain = _retry(t.option_chain, target)
    if chain is None:
        return None
    calls, puts = chain.calls, chain.puts
    if calls is None or puts is None or calls.empty or puts.empty:
        return None

    spot = _f(getattr(t, "fast_info", {}).get("last_price") if hasattr(t, "fast_info") else None)
    if spot is None:
        hist = _retry(t.history, period="5d")
        if hist is None or hist.empty:
            return None
        spot = _f(hist["Close"].iloc[-1])
    if not spot:
        return None

    def mid(df, strike):
        r = df[df["strike"] == strike]
        if r.empty:
            return None
        r = r.iloc[0]
        bid, ask = _f(r.get("bid")), _f(r.get("ask"))
        if bid and ask and ask > 0:
            return (bid + ask) / 2
        return _f(r.get("lastPrice")) or None

    # Only consider strikes quoted on both sides, else deep ITM junk wins.
    common = sorted(set(calls["strike"]) & set(puts["strike"]))
    if not common:
        return None
    atm = min(common, key=lambda s: abs(s - spot))

    c_mid, p_mid = mid(calls, atm), mid(puts, atm)
    if not c_mid or not p_mid:
        return None
    straddle = c_mid + p_mid

    ivs = [_f(v) for v in
           list(calls[calls["strike"] == atm]["impliedVolatility"]) +
           list(puts[puts["strike"] == atm]["impliedVolatility"])]
    ivs = [v for v in ivs if v and v > 0.001]

    time.sleep(config.YF_SLEEP)
    return {
        "symbol": symbol,
        "snap_date": date.today().isoformat(),
        "expiry": target,
        "days_to_expiry": (date.fromisoformat(target) - date.today()).days,
        "spot": spot,
        "atm_strike": atm,
        "straddle_mid": straddle,
        "implied_move_pct": 100.0 * straddle / spot,
        "atm_iv": (sum(ivs) / len(ivs)) if ivs else None,
        "n_contracts": len(calls) + len(puts),
    }


def has_options(symbol: str) -> bool:
    yf = _lazy_yf()
    t = _retry(yf.Ticker, symbol)
    if t is None:
        return False
    try:
        return bool(t.options)
    except Exception:  # noqa: BLE001
        return False
