"""Nasdaq provider: universe screener and earnings calendar.

Both are undocumented JSON endpoints behind nasdaq.com. They are generous and
stable in practice but need a browser User-Agent, and they will happily return
HTTP 200 with an empty payload when unhappy — so callers must check counts, not
just status codes.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import requests

import config

log = logging.getLogger("pricedin.nasdaq")

_HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://www.nasdaq.com/",
}

SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks"
CALENDAR_URL = "https://api.nasdaq.com/api/calendar/earnings"


def _get(url: str, params: dict, retries: int = 3):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=_HEADERS,
                             timeout=config.HTTP_TIMEOUT)
            if r.status_code == 200:
                return r.json()
            log.debug("%s -> HTTP %s", url, r.status_code)
        except Exception as e:  # noqa: BLE001
            log.debug("%s failed: %s", url, e)
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    return None


def _num(v):
    """Parse Nasdaq's money strings: '$4,025,475,080', '(0.12)', '', 'N/A'."""
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "N/A", "--", "-"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").replace(",", "").replace("%", "")
    try:
        f = float(s)
    except ValueError:
        return None
    return -f if neg else f


# ---------------------------------------------------------------- universe
def fetch_universe(limit: int = 8000) -> list[dict]:
    """Every US-listed stock with a market cap, in one call."""
    j = _get(SCREENER_URL, {
        "tableonly": "true", "limit": str(limit), "offset": "0", "download": "false",
    })
    if not j:
        return []
    data = j.get("data") or {}
    rows = (data.get("table") or {}).get("rows") or data.get("rows") or []

    out = []
    for r in rows:
        sym = (r.get("symbol") or "").strip().upper()
        if not sym or any(c in sym for c in config.EXCLUDE_SUFFIXES):
            continue
        name = (r.get("name") or "").strip()
        low = name.lower()
        if any(tok in low for tok in config.EXCLUDE_NAME_TOKENS):
            continue
        mcap = _num(r.get("marketCap"))
        if mcap is None or mcap < config.MIN_MARKET_CAP:
            continue
        out.append({
            "symbol": sym,
            "name": name,
            "market_cap": mcap,
            "last_price": _num(r.get("lastsale")),
        })
    return out


# ---------------------------------------------------------------- calendar
_SESSION_MAP = {
    "time-pre-market": "pre",
    "time-after-hours": "post",
    "time-not-supplied": "unknown",
}


def fetch_calendar_day(d: date) -> list[dict]:
    j = _get(CALENDAR_URL, {"date": d.isoformat()})
    if not j:
        return []
    rows = (j.get("data") or {}).get("rows") or []

    out = []
    for r in rows:
        sym = (r.get("symbol") or "").strip().upper()
        if not sym:
            continue
        out.append({
            "symbol": sym,
            "report_date": d.isoformat(),
            "session": _SESSION_MAP.get(r.get("time") or "", "unknown"),
            "fiscal_quarter": (r.get("fiscalQuarterEnding") or "").strip() or None,
            "eps_forecast": _num(r.get("epsForecast")),
            "n_estimates": int(_num(r.get("noOfEsts")) or 0),
            "market_cap": _num(r.get("marketCap")),
            "name": (r.get("name") or "").strip(),
            "source": "nasdaq",
        })
    return out


def fetch_calendar_range(start: date, end: date, sleep: float = 0.4) -> list[dict]:
    """Sweep the calendar day by day. Weekends are skipped — nobody reports."""
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.extend(fetch_calendar_day(d))
            time.sleep(sleep)
        d += timedelta(days=1)
    return out
