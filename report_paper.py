"""Portfolio dashboard for the paper books — equity curves and trade blotter.

Inline SVG, no chart library, single self-contained file.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import sys
from datetime import datetime

import numpy as np
import pandas as pd

import config
import paper

log = logging.getLogger("pricedin.report_paper")

OUT = config.RESULTS / "portfolio.html"

# Colour-blind safe, consistent across chart and table. Benchmarks are
# deliberately neutral greys so the strategy books read as the subject.
COLOURS = {
    "stance_long": "#2f7fd0",
    "stance_short": "#d06a2f",
    "drift_long": "#4aa564",
    "cheap_vol": "#8a5fc4",
    "random": "#9aa3b0",
    "spy_hold": "#5b6472",
}
DASHED = {"random", "spy_hold"}


def sparkline_svg(curves: dict[str, pd.DataFrame], w: int = 900, h: int = 340,
                  pad: int = 46) -> str:
    if not curves:
        return "<p>No equity data.</p>"

    all_dates = sorted({d for c in curves.values() for d in c["date"]})
    if len(all_dates) < 2:
        return "<p>Not enough history to plot.</p>"
    idx = {d: i for i, d in enumerate(all_dates)}
    n = len(all_dates)

    lo = min(float(c["equity"].min()) for c in curves.values())
    hi = max(float(c["equity"].max()) for c in curves.values())
    if hi <= lo:
        hi = lo + 1
    span = hi - lo
    lo -= span * 0.05
    hi += span * 0.05

    def X(i):
        return pad + (w - 2 * pad) * i / max(1, n - 1)

    def Y(v):
        return h - pad - (h - 2 * pad) * (v - lo) / (hi - lo)

    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" '
             f'preserveAspectRatio="xMidYMid meet" role="img" '
             f'aria-label="Paper trading equity curves by book">']

    # gridlines + y labels
    for f in (0, 0.25, 0.5, 0.75, 1):
        v = lo + (hi - lo) * f
        y = Y(v)
        parts.append(f'<line x1="{pad}" y1="{y:.1f}" x2="{w - pad}" y2="{y:.1f}" '
                     f'stroke="var(--line)" stroke-width="1"/>')
        parts.append(f'<text x="{pad - 8}" y="{y + 4:.1f}" text-anchor="end" '
                     f'font-size="11" fill="var(--muted)">'
                     f'{v / 1000:,.0f}k</text>')

    # starting capital reference
    y0 = Y(paper.STARTING_CASH)
    if pad <= y0 <= h - pad:
        parts.append(f'<line x1="{pad}" y1="{y0:.1f}" x2="{w - pad}" y2="{y0:.1f}" '
                     f'stroke="var(--muted)" stroke-width="1" '
                     f'stroke-dasharray="2 3" opacity="0.8"/>')

    # x labels
    for f in (0, 0.5, 1):
        i = int((n - 1) * f)
        parts.append(f'<text x="{X(i):.1f}" y="{h - pad + 18}" '
                     f'text-anchor="middle" font-size="11" '
                     f'fill="var(--muted)">{all_dates[i]}</text>')

    for book, c in curves.items():
        pts = " ".join(f"{X(idx[d]):.1f},{Y(float(v)):.1f}"
                       for d, v in zip(c["date"], c["equity"]))
        dash = ' stroke-dasharray="5 4"' if book in DASHED else ""
        parts.append(f'<polyline points="{pts}" fill="none" '
                     f'stroke="{COLOURS.get(book, "#888")}" stroke-width="2"'
                     f'{dash} stroke-linejoin="round"/>')

    parts.append("</svg>")
    return "".join(parts)


CSS = """
:root{--bg:#f7f8fa;--panel:#fff;--line:#e3e6ec;--ink:#12151c;--muted:#5b6472;
 --pos:#0b8a5a;--neg:#c0342b;--warn:#b3730a;--warn-bg:#fbf2e2;--neutral-bg:#eef0f4;
 --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --bg:#0e1116;--panel:#161b22;--line:#252c37;--ink:#e6e9ef;--muted:#8b94a3;
 --pos:#3fb984;--neg:#f0645a;--warn:#e0a33c;--warn-bg:#2a2011;--neutral-bg:#1c222b;}}
:root[data-theme="dark"]{--bg:#0e1116;--panel:#161b22;--line:#252c37;--ink:#e6e9ef;
 --muted:#8b94a3;--pos:#3fb984;--neg:#f0645a;--warn:#e0a33c;--warn-bg:#2a2011;
 --neutral-bg:#1c222b;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.02em}
h2{font-size:15px;margin:30px 0 12px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:14px;margin-bottom:20px}
.note{background:var(--warn-bg);border:1px solid var(--line);
 border-left:3px solid var(--warn);border-radius:8px;padding:13px 15px;
 font-size:13.5px;margin-bottom:22px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
 padding:18px;margin-bottom:20px}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:12px;font-size:12.5px}
.lg{display:flex;align-items:center;gap:6px;color:var(--muted)}
.sw{width:16px;height:3px;border-radius:2px;flex:none}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;padding:10px 11px;font-size:11px;text-transform:uppercase;
 letter-spacing:.06em;color:var(--muted);border-bottom:1px solid var(--line);
 white-space:nowrap}
td{padding:10px 11px;border-bottom:1px solid var(--line);white-space:nowrap}
.num{font-family:var(--mono);font-size:12.5px;text-align:right}
.bk{font-weight:600}
.desc{color:var(--muted);font-size:11.5px;white-space:normal;max-width:330px}
.up{color:var(--pos)}.down{color:var(--neg)}
.tag{display:inline-block;padding:2px 7px;border-radius:999px;font-size:10.5px;
 background:var(--neutral-bg);color:var(--muted);font-weight:600;margin-left:6px}
.tablewrap{overflow-x:auto}
footer{margin-top:26px;color:var(--muted);font-size:12px;line-height:1.7}
code{font-family:var(--mono);font-size:12px;background:var(--neutral-bg);
 padding:1px 5px;border-radius:4px}
"""


def build_html(summary: pd.DataFrame, curves: dict, blotter: pd.DataFrame,
               meta: dict) -> str:
    def pct(v):
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            return '<span style="color:var(--muted)">—</span>'
        c = "up" if v > 0 else ("down" if v < 0 else "")
        return f'<span class="{c}">{v:+.2f}%</span>'

    def money(v):
        if v is None or not np.isfinite(v):
            return "—"
        c = "up" if v > 0 else ("down" if v < 0 else "")
        return f'<span class="{c}">${v:,.0f}</span>'

    rows = []
    order = ["stance_long", "stance_short", "drift_long", "cheap_vol",
             "random", "spy_hold"]
    summary = summary.set_index("book").reindex(
        [b for b in order if b in set(summary["book"])]).reset_index()

    for _, r in summary.iterrows():
        b = r["book"]
        tag = ('<span class="tag">CONTROL</span>' if b == "random"
               else '<span class="tag">BENCHMARK</span>' if b == "spy_hold" else "")
        hit = r["hit_rate"]
        rows.append(f"""<tr>
          <td><span class="bk" style="color:{COLOURS.get(b, '#888')}">{b}</span>{tag}
              <div class="desc">{html.escape(paper.BOOKS.get(b, ''))}</div></td>
          <td class="num">{int(r['trades']):,}</td>
          <td class="num">{'' if not np.isfinite(hit) else f'{hit:.0%}'}</td>
          <td class="num">{r['avg_ret_pct']:+.3f}%</td>
          <td class="num">{money(r['costs_paid'])}</td>
          <td class="num">{money(r['net_pnl'])}</td>
          <td class="num">{pct(r['return_pct'])}</td>
          <td class="num">{'—' if not np.isfinite(r['sharpe']) else f"{r['sharpe']:.2f}"}</td>
          <td class="num">{'—' if not np.isfinite(r['max_dd_pct']) else f"{r['max_dd_pct']:.1f}%"}</td>
        </tr>""")

    legend = "".join(
        f'<div class="lg"><span class="sw" style="background:{COLOURS.get(b, "#888")}'
        f'{";opacity:.7" if b in DASHED else ""}"></span>{b}</div>'
        for b in summary["book"])

    blot = ""
    if not blotter.empty:
        brows = []
        for _, t in blotter.iterrows():
            brows.append(f"""<tr>
              <td>{t['exit_date']}</td>
              <td><span class="bk">{t['symbol']}</span></td>
              <td style="color:{COLOURS.get(t['book'], '#888')}">{t['book']}</td>
              <td>{t['side']}</td>
              <td class="num">{t['entry_price']:.2f}</td>
              <td class="num">{t['exit_price']:.2f}</td>
              <td>{t['exit_reason']}</td>
              <td class="num">{money(t['pnl'])}</td>
              <td class="num">{pct(t['ret_pct'])}</td>
            </tr>""")
        blot = f"""<h2>Most recent closed trades</h2>
        <div class="card"><div class="tablewrap"><table>
          <thead><tr><th>Exit</th><th>Symbol</th><th>Book</th><th>Side</th>
          <th>Entry</th><th>Exit px</th><th>Reason</th><th>P&amp;L</th>
          <th>Return</th></tr></thead>
          <tbody>{''.join(brows)}</tbody></table></div></div>"""

    return f"""<title>Priced In — paper portfolio</title>
<style>{CSS}</style>
<div class="wrap">
  <h1>Paper portfolio</h1>
  <div class="sub">Six books, same events, same costs, same sizing rules.
    {html.escape(meta.get('period', ''))} · generated {html.escape(meta.get('generated', ''))}</div>

  <div class="note"><strong>Read the control, not the P&amp;L.</strong> Two of these
  books exist only as yardsticks: <code>random</code> takes the same number of trades
  from the same pool at random, and <code>spy_hold</code> just buys the index. A book
  is only interesting if it beats those. In a rising market almost any book shows a
  profit, which is exactly how strategies get adopted that have no edge at all.
  <br><br>Every rule here was fixed on data before {html.escape(config.BACKTEST_VALIDATE_END)},
  and this replay runs after it, so the result is genuinely out of sample. The live
  stance uses consensus revisions and implied moves; neither exists historically, so
  the replay scores a <em>proxy</em> stance built only from features observable at the
  time. Same shape of rule, not the same rule.</div>

  <div class="card">
    {sparkline_svg(curves)}
    <div class="legend">{legend}</div>
  </div>

  <h2>Book performance</h2>
  <div class="card"><div class="tablewrap"><table>
    <thead><tr>
      <th>Book</th><th>Trades</th><th>Hit rate</th><th>Avg/trade</th>
      <th>Costs paid</th><th>Net P&amp;L</th><th>Return</th><th>Sharpe</th>
      <th>Max DD</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table></div></div>

  {blot}

  <footer>
    Starting capital ${paper.STARTING_CASH:,.0f} per book · max
    {meta.get('max_concurrent', 20)} concurrent positions ·
    {paper.COST_BPS:.0f}bps round-trip cost plus {paper.SLIPPAGE_BPS:.0f}bps
    slippage per side · positions sized by the validated move model, not by conviction.
    <br>Stops are simulated against the bar's open when it gaps through the level,
    so an earnings gap costs what it really costs rather than the stop price.
    <br><br><strong>Not investment advice.</strong> A paper book that is up has not
    proven anything until it has beaten the control over a period nobody chose
    after the fact.
  </footer>
</div>
"""


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--blotter", type=int, default=25)
    args = ap.parse_args()

    con = paper.connect()
    try:
        s = paper.summary(con)
        curves = {}
        for b in s["book"]:
            c = pd.read_sql_query(
                "SELECT date, equity FROM equity WHERE book=? ORDER BY date",
                con, params=(b,))
            if not c.empty:
                curves[b] = c
        blotter = pd.read_sql_query(
            "SELECT book, symbol, side, entry_price, exit_price, exit_date, "
            "exit_reason, pnl, ret_pct FROM positions WHERE status='closed' "
            "AND book != 'spy_hold' ORDER BY exit_date DESC, id DESC LIMIT ?",
            con, params=(args.blotter,))
        span = con.execute(
            "SELECT MIN(date) a, MAX(date) b FROM equity").fetchone()
    finally:
        con.close()

    meta = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "period": f"{span['a']} .. {span['b']}" if span and span["a"] else "",
        "max_concurrent": 20,
    }
    out = build_html(s, curves, blotter, meta)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(out)
    log.info("wrote %s (%.0f KB)", args.out, len(out) / 1024)


if __name__ == "__main__":
    main()
