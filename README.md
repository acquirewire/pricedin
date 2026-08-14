# Priced In

A research dashboard for upcoming US earnings: who reports when, what the market
has already decided about it, and — crucially — what the evidence does *not*
support claiming.

Built entirely on free data sources. No paid API, no vendor lock-in.

```bash
pip install -r requirements.txt
python db.py                    # create schema
python -m ingest.universe       # ~3,000 US names above $500m
python -m ingest.calendar       # rolling earnings calendar
python -m ingest.snapshot       # consensus snapshot (the important one)
python -m ingest.history        # 10y of surprise history
python -m ingest.prices         # 11y OHLCV
python build_events.py          # point-in-time event panel
python backtest.py              # walk-forward validation
python score.py && python report.py
```

Or just `python daily.py`, which is what the GitHub Action runs.

---

## The idea

Predicting "will they beat EPS" is close to a solved problem — analyst consensus
*is* the prediction, and companies beat it roughly 70% of the time. The stock
reaction is driven by guidance and by what was already priced in, not by the
headline number.

So this doesn't try to predict beats. It answers three separate questions and
keeps them separate, because blending them into one score hides where a view
comes from:

| Panel | Question | Inputs |
|---|---|---|
| **Expectation** | Will they beat? | Consensus history, revision momentum, revision breadth, analyst count |
| **Asymmetry** | Is it worth it? | Implied move vs realised move distribution, run-up into the print |
| **Reaction** | Does beating even help? | Reaction/surprise slope, mean reaction, beat-and-fell rate |

## What compounds

Today's consensus EPS is free from a dozen places. The *history* of consensus EPS
is not — it sits behind Bloomberg and FactSet because someone had to store it
daily. `ingest/snapshot.py` stores it.

The accelerant: Yahoo's `eps_trend` reports what consensus was 7, 30, 60 and 90
days ago. So a ticker arrives with a quarter of revision history already attached
instead of starting empty. First run produced **11,552 rows spanning three
months** rather than one day. Every run after that extends it forward.

This is why `data/core.db` is committed to git and `data/market.db` is not:
prices can be re-downloaded from Yahoo any time, consensus-as-of-a-past-date
cannot be re-fetched at any price.

---

## Backtest results

83,366 earnings events, 2,600 symbols, 2016–2026. Walk-forward: train through
2020, validate through 2023, holdout 2024–2026 examined exactly once.

Every strategy is measured against a **random-entry control** drawn from the same
liquid universe in the same window. This matters more than any other design
choice here — most earnings "edges" are long exposure to a market that drifts
upward, and they look excellent until you ask what a coin flip would have done.

### Directional strategies: 0 of 15 survived

| Strategy | Train excess | Validate excess | Holdout excess | Verdict |
|---|---|---|---|---|
| `pead_long_beat_20d` | +26 bps | +34 bps | **+5 bps** | Cleared train+validate, **failed holdout** |
| `runup_weak_long` | +43 bps | +49 bps | −12 bps | Missed the control gate, then failed |
| `serial_beater` | +21 bps | −4 bps | −4 bps | Textbook overfit — strong in train only |
| `pead_short_miss` | −48 bps | −57 bps | −96 bps | Shorting misses loses money, consistently |
| `runup_fade` | −35 bps | −20 bps | −141 bps | "It's already priced in" does not work as a trade |

*(excess = strategy mean minus random control mean, same period, same pool)*

The single best directional idea — buy a >5% beat and hold 20 days, the classic
post-earnings-announcement drift — returned 159 bps in holdout against a control
of 173 bps. It underperformed a random pick. Gross returns looked great in every
period; the edge over random was never real.

### Magnitude: robust across all three periods

| Test | Train | Validate | Holdout |
|---|---|---|---|
| Quietest quartile of past reactions | **0.54×** | 0.58× | **0.54×** |
| Loudest quartile of past reactions | **1.55×** | 1.47× | **1.56×** |

*(ratio of realised absolute move vs a random name in the same window)*

A stock's own history of reaction size predicts its next reaction size, with a
~2.9× spread between the tails, and the numbers barely move across a decade and
three independent samples. This is the finding the product is built on: it is
what makes "implied 7.0% vs realised 3.2%" a meaningful statement rather than a
coincidence.

### What this means

The honest conclusion is that **direction is not predictable from this feature
set, and magnitude is.** The dashboard reflects that. The Stance column exists
to summarise the panels transparently, and says in its own caveat that it is not
a validated edge. The Implied÷Realised column is the one with evidence behind it.

A dashboard that told you what to buy would be more satisfying and less true.

---

## Avoiding the classic mistakes

**Announcement timing.** A print after Tuesday's close reacts in Wednesday's bar;
one before Tuesday's open reacts in Tuesday's. Get this wrong by a day and the
backtest measures the reaction it is trying to predict. `signals/events.py`
defines `t0` as the last session whose close precedes the announcement and
derives everything from that. Session is inferred from the announcement hour in
Yahoo's timestamps.

**Point-in-time features.** Every feature for an event uses only prior events and
prices up to `t0`. Reaction slope, beat rate and surprise history are computed
from strictly earlier prints, never the full series.

**Costs.** 20 bps round-trip charged to every strategy. Several signals are
positive gross and negative net.

**The control.** Described above. It is the reason 14 of 15 strategies were
rejected before the holdout was ever opened.

### Known limitations

- **Survivorship bias.** The universe is today's listed names. Companies that
  delisted after a catastrophic print are absent, so realised-move statistics are
  optimistic. Not fixable on free data; stated rather than hidden.
- **Revision momentum is not in the backtest.** We have three months of
  revision history and a decade of price history. Including it would mean
  fitting on the three months and calling it a decade. It appears in the
  Expectation panel as context and is deliberately excluded from `p_beat`.
- **Estimate quality on small caps** is poor. The $500m floor and analyst-count
  display help; a 2-analyst consensus is shown but should not be trusted.
- **Yahoo's `impliedVolatility`** is unreliable on short-dated contracts, so
  implied move is derived from the straddle mid, not from IV.

---

## Layout

```
config.py              universe filters, tiering, backtest splits, sizing limits
db.py                  SQLite schema. core.db (committed) / market.db (not)
providers/             all external I/O — swap for a paid feed without touching
  yahoo.py             estimates, earnings history, prices, option chains
  nasdaq.py            universe screener, earnings calendar
ingest/
  universe.py          screener -> filtered universe + refresh tiering
  calendar.py          rolling calendar sweep
  snapshot.py          daily consensus snapshot + 90d backfill
  history.py           historical surprise
  prices.py            OHLCV
  options.py           implied move for near-term reporters
signals/events.py      point-in-time event panel (t0 definition lives here)
backtest.py            walk-forward + random control + survivor gate
score.py               three panels, P(beat), rules-based verdict
sizing.py              vol targeting (no view) and fractional Kelly (view)
report.py              single-file HTML dashboard
daily.py               orchestrator for the cron job
```

### Refresh tiering

Free APIs are rate limited, so refresh is driven by urgency, not fairness:

| Tier | Days to report | Cadence |
|---|---|---|
| A | ≤ 21 | daily, plus option chains |
| B | ≤ 60 | Mondays and Thursdays |
| C | everything else | Sundays |

A typical weekday selects ~600 names, which finishes in about 90 seconds at 6
workers.

---

## Deployment

`.github/workflows/daily.yml` runs at 09:15 UTC on weekdays, commits the updated
`core.db` and dashboard, and caches `market.db` between runs. Set the `NTFY_TOPIC`
secret for failure alerts.

The snapshot stage is the one that cannot be recovered if missed — a skipped day
is a permanent hole in the revision history — so it runs before the optional
stages and its failures are reported loudly.

---

## Not investment advice

This is a research tool built from free, unofficial data sources by someone
studying accounting and finance. It does not know your circumstances and is not
a recommendation to buy or sell anything. The backtest section above is a fair
description of how little of this is predictive.
