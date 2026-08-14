"""Central configuration for Priced In.

Everything tunable lives here so the ingest jobs, backtest and dashboard all
agree on universe definition, tiering and file locations.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"
CACHE = DATA / "cache"
for _d in (DATA, RESULTS, CACHE):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- databases
# Two databases, split by whether the data is replaceable.
#
#   core.db   estimate snapshots, calendar, universe, earnings history.
#             Irreplaceable — a snapshot of consensus on a given day cannot be
#             re-fetched later at any price. This one gets committed to git.
#
#   market.db prices and option chains. Fully re-downloadable from Yahoo at any
#             time, and large. Gitignored.
CORE_DB = DATA / "core.db"
MARKET_DB = DATA / "market.db"

# ---------------------------------------------------------------- universe
# US-listed common stock. The market cap floor and the options requirement do
# the real filtering: below ~$500m analyst coverage is too thin for a consensus
# to mean anything, and without a listed option chain there is no implied move,
# which is the single most useful input we have.
MIN_MARKET_CAP = 500_000_000
MIN_ANALYSTS = 2          # a "consensus" of one analyst is not a consensus
EXCLUDE_SUFFIXES = ("^", "/")   # warrants, units, preferred, rights
EXCLUDE_NAME_TOKENS = (
    "warrant", "unit", "preferred", "right", "depositary",
    "acquisition corp", "trust preferred",
)

# ---------------------------------------------------------------- tiering
# Free APIs are rate limited, so we cannot refresh 3,000 names every day. We
# refresh by urgency instead: a name reporting next week matters far more than
# one reporting in three months.
TIER_A_DAYS = 21          # reporting within 21d -> refresh daily, fetch options
TIER_B_DAYS = 60          # reporting within 60d -> refresh twice a week
                          # everything else      -> refresh weekly
CALENDAR_LOOKAHEAD_DAYS = 75
CALENDAR_LOOKBACK_DAYS = 10   # keep recent past to catch date slips / actuals

# ---------------------------------------------------------------- throttling
YF_SLEEP = float(os.environ.get("PRICEDIN_YF_SLEEP", "0.25"))
YF_MAX_RETRIES = 3
YF_BACKOFF = 2.0
BATCH_SIZE = 100          # tickers per yf.download call
HTTP_TIMEOUT = 25

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
             "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
SEC_USER_AGENT = os.environ.get("PRICEDIN_SEC_UA", "pricedin research h.h.shek@lse.ac.uk")

# ---------------------------------------------------------------- history
PRICE_HISTORY_YEARS = 11
BACKTEST_TRAIN_END = "2020-12-31"
BACKTEST_VALIDATE_END = "2023-12-31"
# Everything after BACKTEST_VALIDATE_END is holdout. Look at it once.

# ---------------------------------------------------------------- signals
REACTION_MIN_QUARTERS = 8     # below this, per-stock reaction stats are noise
RUNUP_WINDOW = 10             # trading days before the print
DRIFT_WINDOWS = (1, 5, 20)    # post-earnings return horizons we measure

# ---------------------------------------------------------------- sizing
# Deterministic vol targeting. No view is embedded here — it converts a risk
# budget into a position size given the expected move. Kelly fraction is only
# applied to signals that cleared the backtest gate.
DEFAULT_RISK_BUDGET_PCT = 1.0     # % of portfolio you are willing to lose
MAX_POSITION_PCT = 10.0
KELLY_FRACTION = 0.25             # quarter Kelly, and only on validated edges

# ---------------------------------------------------------------- alerts
NTFY_TOPIC = os.environ.get("PRICEDIN_NTFY_TOPIC", "")
