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

Neither SQLite file is committed — both are rebuildable. What *is* committed is
`data/snapshots.csv.gz`, the append-only record of every consensus reading ever
observed. It is **127 KB** for the first 11,552 rows, versus 14.5 MB for the
database that contains them, and it round-trips losslessly:

```bash
python db.py export     # core.db -> data/snapshots.csv.gz
python db.py import     # data/snapshots.csv.gz -> core.db
```

Prices and earnings history can be re-downloaded from Yahoo any time.
Consensus-as-of-a-past-date cannot be re-fetched at any price. Only the second
category gets versioned.

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

## Trade levels

`levels.py` produces entry, target and stop geometry — with two hard rules built
in, both of which contradict how this is usually done.

**A stop-loss does not work through an earnings print.** The stock gaps at the
open and fills you far past your level; a 5% stop on a name that gaps 12% is a
12% loss. So `through_print` plans carry **no stop at all** and say why. Position
size is the only risk control that functions across a gap, which is exactly what
`sizing.py` is for. Stops appear only on `post_print_drift` plans, where you
enter after the gap has already happened.

**Levels come from predicted move size, expectancy comes from honest odds.** A
linear model on the stock's own reaction history predicts move *magnitude* with
correlation 0.40 / 0.40 / 0.42 across train / validate / holdout, monotonic
across all ten deciles, 4.8× spread between the top and bottom decile. Direction
gets no such treatment, because it does not survive. Expected value is computed
from the empirical up-rate for that move size, so most directional plans come
back marked negative — which is the honest answer, not a broken calculator.

```
NVDA  reports 2026-08-26 (post)   stance: Leaning unfavourable

  [through_print]    short    EV  -79 bps   (negative expectancy)
  [post_print_drift] short    EV  -11 bps   (negative expectancy)
  [premium_sell]     short_vol EV +246 bps  (TRADEABLE)
```

Only the premium-sell setup clears, which is consistent with the backtest: the
one finding that survived holdout was about magnitude, and magnitude is what
option premium prices.

---

## Paper trading

`paper.py` runs six books over the same events with the same costs and sizing.
Two of them exist purely as yardsticks: `random` takes the same number of trades
from the same pool at random, and `spy_hold` just buys the index. A book that is
up has proven nothing until it beats those.

`paper_replay.py` replays the books across the holdout period so the portfolio
starts with a real curve instead of three months of waiting. Fills come from
daily OHLC, and **a bar that gaps through a stop fills at the open, not at the
stop price** — skipping that is how backtests invent money.

### Result over 2024-01 to 2026-08

| Book | Trades | Hit rate | Costs paid | Return | Sharpe |
|---|---|---|---|---|---|
| stance_long | 5,638 | 48% | $67,613 | **−32.3%** | −0.61 |
| stance_short | 2,015 | 48% | $21,257 | −49.0% | −1.83 |
| drift_long | 2,567 | 46% | $32,237 | −19.0% | −0.70 |
| cheap_vol | 3,990 | 47% | $47,771 | −48.0% | −2.36 |
| `random` (control) | 4,733 | 48% | $55,072 | −41.5% | −1.02 |
| `spy_hold` (benchmark) | 1 | — | $404 | **+69.1%** | 0.62 |

$100k per book, max 20 concurrent positions, 30bps round trip.

**Turnover is what kills it.** `stance_long` paid $67,613 in costs on $100,000
of capital, at 225× turnover. Run the same replay frictionless and the picture
inverts:

```bash
python paper_replay.py --start 2024-01-01 --cost-bps 0 --slippage-bps 0
```

| Book | Return (0 costs) | vs control |
|---|---|---|
| stance_long | **+47.6%** | +34.3 |
| drift_long | +14.4% | +1.1 |
| `random` | +13.3% | — |
| `spy_hold` | +69.5% | — |

So there is a gross edge of roughly 34 points over the control across 2.5 years,
and costs turn it into a 32% loss — an 80-point swing. Even gross it loses to
buying SPY and going outside.

**Where the gross edge comes from matters.** The backtest found no directional
edge on equal-weighted returns, and the hit rate here is 48% — the same coin flip.
What differs is that positions are **sized by the validated move model**: small in
volatile names, large in quiet ones. The picking does not work; the sizing does.
Sharpe 0.81 against the control's 0.35 says the same thing. That is one path over
one period and has not been through the survivor gate, so treat it as a lead
worth testing, not a result.

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

**Costs.** 20 bps round-trip charged to every strategy, and 30 bps in the paper
books once slippage is added. Several signals are positive gross and negative
net; one of them swings 80 percentage points between the two.

**NaN, not None, is the dangerous missing value.** `not float('nan')` is `False`,
so a NaN passes a truthiness guard, poisons the arithmetic downstream, and then
gets stored by SQLite as `NULL` — surfacing much later and far from its cause.
This actually happened: a NaN move estimate produced a NaN position size and a
position with no quantity, which only blew up two steps later during
mark-to-market. Everything entering `sizing.py` now goes through a finite check.

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
db.py                  SQLite schema + the committed snapshot archive (export/import)
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
levels.py              move-size model, entry/TP/SL geometry, EV gate
sizing.py              vol targeting (no view) and fractional Kelly (view)
paper.py               six-book paper portfolio, OHLC fills with gap handling
paper_replay.py        replay the books over the holdout period
report.py              single-file HTML earnings dashboard
report_paper.py        single-file HTML portfolio dashboard
export_web.py          pipeline output -> JSON for the front end
daily.py               orchestrator for the cron job
web/                   Next.js front end (see below)
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

## Front end

`web/` is a Next.js 16 app (React 19, Tailwind 4, shadcn/ui) that reads a static
JSON snapshot of the pipeline's output. Python stays the source of truth; the
site has no database and no API to keep alive.

```bash
python export_web.py          # writes web/src/data/*.json
cd web && npm run dev         # or `npm run build` for static output
```

Four routes: the earnings calendar, a per-symbol detail page prerendered for
every tracked company, the paper portfolio, and the methodology write-up. A
production build emits 196 static pages.

### Design notes

The brief was to look like research infrastructure rather than a launch page,
which mostly meant deciding what *not* to do.

- **IBM Plex Sans and Plex Mono.** Institutional rather than promotional, and
  Plex Mono gives real tabular figures.
- **Tabular numerals everywhere**, applied globally to table cells rather than
  remembered per component. Figures that do not line up in a column are the
  clearest tell of a data product built by someone who does not use one.
- **Hairline borders, no shadows, 6px radius.** Depth via rules and spacing.
- **Desaturated red and green.** These appear on hundreds of cells at once;
  saturated semantics read as a toy.
- **Missing data renders as an em dash, never as zero.** On a research screen
  the difference between "we measured zero" and "we have no measurement" is the
  whole point.
- **The stance is a dot and a word, not a coloured BUY pill.** The backtest
  found no directional edge, so a confident badge would be claiming something
  the evidence does not support.

The methodology page is the one that matters: it leads with the fact that
nothing survived, and shows the excess-over-control figures per period so the
failures are legible rather than buried.

---

## Deployment

`.github/workflows/daily.yml` runs at 09:15 UTC on weekdays, commits the updated
snapshot archive and dashboard, and caches both databases between runs. On a
cache miss it rebuilds the snapshot history from the committed archive first,
so a cold runner never loses accumulated consensus data. Set the `NTFY_TOPIC`
secret for failure alerts.

The snapshot stage is the one that cannot be recovered if missed — a skipped day
is a permanent hole in the revision history — so it runs before the optional
stages, is held to a higher success threshold than the rest, and fails the build
on its own.

**On silent failure.** The ingest jobs deliberately swallow per-symbol errors so
one dead ticker cannot stop a 3,000-name sweep. The consequence is that a total
upstream outage returns `(0, 3000)` and looks exactly like a clean run — which is
precisely what happened during development when Yahoo rate-limited a burst of
~7,000 calls, and `daily.py` cheerfully logged "all stages ok" having collected
nothing. `stage()` now judges stages on their success *rate*, not just on whether
they threw:

| Stage | Threshold | Zero rows allowed |
|---|---|---|
| snapshot | 60% | no — fails the build alone |
| everything else | 50% | no |
| prices | 50% | yes (no new bar at weekends) |

A missed snapshot is partially recoverable: `eps_trend` backfills 7/30/60/90 days
on the next successful run, so a gap noticed within a week closes itself. After
that it is permanent, which is why the alert names the deadline.

---

## Not investment advice

This is a research tool built from free, unofficial data sources by someone
studying accounting and finance. It does not know your circumstances and is not
a recommendation to buy or sell anything. The backtest section above is a fair
description of how little of this is predictive.
