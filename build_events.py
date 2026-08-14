"""Assemble the event panel from earnings history + prices, ready to backtest.

Run after ingest.history and ingest.prices.
"""
from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

import config
import db
from ingest import history as hist_mod
from ingest import prices as price_mod
from signals.events import build_events

log = logging.getLogger("pricedin.build_events")

OUT = config.DATA / "events.pkl"
BENCH = "SPY"


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--limit-symbols", type=int, default=0)
    args = ap.parse_args()

    log.info("loading earnings history...")
    h = hist_mod.load_history(reported_only=True)
    log.info("  %d reported prints across %d symbols",
             len(h), h["symbol"].nunique() if not h.empty else 0)
    if h.empty:
        log.error("no earnings history - run `python -m ingest.history` first")
        return

    syms = sorted(h["symbol"].unique())
    if args.limit_symbols:
        syms = syms[: args.limit_symbols]

    log.info("loading prices for %d symbols...", len(syms))
    px = price_mod.load_prices(syms)
    log.info("  %d price rows across %d symbols",
             len(px), px["symbol"].nunique() if not px.empty else 0)
    if px.empty:
        log.error("no prices - run `python -m ingest.prices` first")
        return

    bench = price_mod.load_prices([BENCH])[["date", "close"]] \
        if not price_mod.load_prices([BENCH]).empty else None
    if bench is None or bench.empty:
        log.warning("no %s benchmark prices - relative strength will be null", BENCH)
        bench = None

    log.info("building event panel...")
    ev = build_events(h[h["symbol"].isin(syms)], px, bench)
    if ev.empty:
        log.error("no events built")
        return

    ev.to_pickle(args.out)
    log.info("wrote %d events to %s", len(ev), args.out)
    log.info("  span: %s .. %s", ev["report_date"].min().date(),
             ev["report_date"].max().date())
    log.info("  symbols: %d", ev["symbol"].nunique())

    cov = ev[["surprise_pct", "runup_10d", "reaction_slope", "rel_strength_60d",
              "ret_1d", "drift_5d", "drift_20d"]].notna().mean()
    log.info("  feature coverage:\n%s", cov.round(3).to_string())

    by_year = ev.groupby("year").size()
    log.info("  events per year:\n%s", by_year.to_string())


if __name__ == "__main__":
    main()
