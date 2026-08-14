"""Single-file HTML dashboard.

Everything is inlined so the output can be opened from disk, committed, served
statically, or published as an artifact without any build step.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import sys
from datetime import date, datetime

import numpy as np
import pandas as pd

import config

log = logging.getLogger("pricedin.report")

OUT = config.RESULTS / "dashboard.html"


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if not np.isfinite(f) else round(f, 4)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (pd.Timestamp, date, datetime)):
        return str(v)[:10]
    return v


def to_records(df: pd.DataFrame) -> list[dict]:
    keep = [
        "symbol", "name", "report_date", "session", "days_to_report",
        "market_cap", "price", "eps_forecast", "n_estimates", "n_analysts",
        "p_beat", "p_beat_n", "beat_rate_8", "surp_mean_4",
        "rev_chg_7d", "rev_chg_30d", "rev_chg_90d", "up_30d", "down_30d",
        "n_observed", "snap_span_days",
        "implied_move_pct", "implied_expiry", "realised_move_med_8",
        "realised_move_max_8", "implied_vs_realised",
        "runup_10d", "runup_60d", "vol_20d",
        "reac_mean_8", "reac_median_8", "reaction_slope", "beat_and_fell_rate",
        "last_reactions", "n_quarters",
        "size_pct", "size_basis", "size_risk_pct", "verdict",
    ]
    recs = []
    for _, r in df.iterrows():
        d = {}
        for k in keep:
            if k not in r:
                continue
            v = r[k]
            if k == "verdict" and isinstance(v, dict):
                d[k] = v
            elif k == "last_reactions" and isinstance(v, list):
                d[k] = [_clean(x) for x in v]
            else:
                d[k] = _clean(v)
        recs.append(d)
    return recs


CSS = """
:root{
  --bg:#f7f8fa; --panel:#ffffff; --line:#e3e6ec; --ink:#12151c; --muted:#5b6472;
  --pos:#0b8a5a; --neg:#c0342b; --warn:#b3730a; --accent:#2f5fd0;
  --pos-bg:#e6f5ee; --neg-bg:#fdeceb; --warn-bg:#fbf2e2; --neutral-bg:#eef0f4;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#0e1116; --panel:#161b22; --line:#252c37; --ink:#e6e9ef; --muted:#8b94a3;
    --pos:#3fb984; --neg:#f0645a; --warn:#e0a33c; --accent:#6f95ea;
    --pos-bg:#12291f; --neg-bg:#2b1614; --warn-bg:#2a2011; --neutral-bg:#1c222b;
  }
}
:root[data-theme="dark"]{
  --bg:#0e1116; --panel:#161b22; --line:#252c37; --ink:#e6e9ef; --muted:#8b94a3;
  --pos:#3fb984; --neg:#f0645a; --warn:#e0a33c; --accent:#6f95ea;
  --pos-bg:#12291f; --neg-bg:#2b1614; --warn-bg:#2a2011; --neutral-bg:#1c222b;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1280px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.02em}
.sub{color:var(--muted);font-size:14px;margin-bottom:22px}
.disclaimer{background:var(--warn-bg);border:1px solid var(--line);
  border-left:3px solid var(--warn);border-radius:8px;padding:12px 14px;
  font-size:13px;color:var(--ink);margin-bottom:22px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
  gap:12px;margin-bottom:22px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.stat .v{font-size:22px;font-weight:600;letter-spacing:-.02em}
.stat .l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:2px}
.controls{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px;align-items:center}
input,select{background:var(--panel);color:var(--ink);border:1px solid var(--line);
  border-radius:8px;padding:8px 10px;font-size:14px;font-family:inherit}
input:focus,select:focus{outline:2px solid var(--accent);outline-offset:-1px}
.tablewrap{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px}
table{width:100%;border-collapse:collapse;font-size:13.5px;min-width:960px}
th{text-align:left;padding:11px 12px;font-size:11px;text-transform:uppercase;
  letter-spacing:.06em;color:var(--muted);border-bottom:1px solid var(--line);
  cursor:pointer;white-space:nowrap;user-select:none;background:var(--panel);
  position:sticky;top:0;z-index:1}
th:hover{color:var(--ink)}
td{padding:11px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
tr.row{cursor:pointer}
tr.row:hover td{background:var(--neutral-bg)}
.num{font-family:var(--mono);font-size:12.5px;text-align:right}
.sym{font-weight:650;letter-spacing:-.01em}
.nm{color:var(--muted);font-size:12px;max-width:190px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.badge{display:inline-block;padding:3px 9px;border-radius:999px;font-size:11.5px;
  font-weight:600;white-space:nowrap}
.pos{background:var(--pos-bg);color:var(--pos)}
.neg{background:var(--neg-bg);color:var(--neg)}
.lean-pos{background:var(--pos-bg);color:var(--pos);opacity:.78}
.lean-neg{background:var(--neg-bg);color:var(--neg);opacity:.78}
.neutral{background:var(--neutral-bg);color:var(--muted)}
.up{color:var(--pos)}.down{color:var(--neg)}
.detail td{background:var(--bg);padding:0;border-bottom:2px solid var(--line)}
.dwrap{padding:18px 20px;display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px}
.panel h4{margin:0 0 9px;font-size:11px;text-transform:uppercase;
  letter-spacing:.07em;color:var(--muted)}
.kv{display:flex;justify-content:space-between;gap:14px;padding:4px 0;
  font-size:13px;border-bottom:1px dotted var(--line)}
.kv span:last-child{font-family:var(--mono);font-size:12.5px}
.reasons{grid-column:1/-1;border-top:1px solid var(--line);padding-top:14px}
.reason{display:flex;gap:9px;padding:4px 0;font-size:13.5px;align-items:flex-start}
.mark{font-family:var(--mono);font-weight:700;flex:none;width:14px}
.caveat{margin-top:12px;font-size:12px;color:var(--muted);font-style:italic;
  border-left:2px solid var(--line);padding-left:10px}
.empty{padding:36px;text-align:center;color:var(--muted)}
footer{margin-top:28px;color:var(--muted);font-size:12px;line-height:1.7}
code{font-family:var(--mono);font-size:12px;background:var(--neutral-bg);
  padding:1px 5px;border-radius:4px}
"""

JS = """
const D = window.__DATA__;
let sortKey='days_to_report', sortDir=1, open=new Set();

const f = (v,d=1,suf='')=> (v===null||v===undefined||Number.isNaN(v)) ? '<span style="color:var(--muted)">—</span>'
  : (typeof v==='number'? v.toFixed(d):v)+suf;
const sgn = (v,d=1,suf='%')=>{
  if(v===null||v===undefined||Number.isNaN(v)) return '<span style="color:var(--muted)">—</span>';
  const c = v>0?'up':(v<0?'down':'');
  return `<span class="${c}">${v>0?'+':''}${v.toFixed(d)}${suf}</span>`;
};
const cap = v => v===null||v===undefined ? '—' : (v>=1e12?(v/1e12).toFixed(1)+'T':v>=1e9?(v/1e9).toFixed(1)+'B':(v/1e6).toFixed(0)+'M');

function rows(){
  const q=(document.getElementById('q').value||'').toLowerCase();
  const st=document.getElementById('stance').value;
  let r=D.filter(d=>{
    if(q && !(d.symbol.toLowerCase().includes(q)||(d.name||'').toLowerCase().includes(q))) return false;
    if(st && (!d.verdict||d.verdict.colour!==st)) return false;
    return true;
  });
  r.sort((a,b)=>{
    let x=a[sortKey],y=b[sortKey];
    if(sortKey==='stance'){x=a.verdict?a.verdict.score:0;y=b.verdict?b.verdict.score:0;}
    if(x===null||x===undefined)return 1; if(y===null||y===undefined)return -1;
    if(typeof x==='string')return sortDir*x.localeCompare(y);
    return sortDir*(x-y);
  });
  return r;
}

function detail(d){
  const v=d.verdict||{supports:[],against:[],neutral:[],caveat:''};
  const kv=(k,val)=>`<div class="kv"><span>${k}</span><span>${val}</span></div>`;
  const lr=(d.last_reactions||[]).map(x=>`<span class="${x>0?'up':'down'}">${x>0?'+':''}${x}%</span>`).join('  ') || '—';
  return `<div class="dwrap">
    <div class="panel"><h4>Expectation — will they beat?</h4>
      ${kv('Historical beat frequency', f(d.p_beat*100,0,'%')+(d.p_beat_n?` <span style="color:var(--muted)">n=${d.p_beat_n}</span>`:' <span style="color:var(--muted)">base</span>'))}
      ${kv('Beat rate, last 8', d.beat_rate_8!=null?(d.beat_rate_8*100).toFixed(0)+'%':'—')}
      ${kv('Mean surprise, last 4', sgn(d.surp_mean_4,1,'%'))}
      ${kv('Consensus EPS revision 30d', sgn(d.rev_chg_30d,1,'%'))}
      ${kv('Consensus EPS revision 90d', sgn(d.rev_chg_90d,1,'%'))}
      ${kv('Revision breadth 30d', (d.up_30d!=null?`${d.up_30d} up / ${d.down_30d} down`:'—'))}
      ${kv('Analysts covering', f(d.n_analysts,0))}
    </div>
    <div class="panel"><h4>Asymmetry — is it worth it?</h4>
      ${kv('Implied move (straddle)', f(d.implied_move_pct,1,'%'))}
      ${kv('Median realised, last 8', f(d.realised_move_med_8,1,'%'))}
      ${kv('Largest realised, last 8', f(d.realised_move_max_8,1,'%'))}
      ${kv('Implied ÷ realised', f(d.implied_vs_realised,2,'x'))}
      ${kv('Run-up, 10 sessions', sgn(d.runup_10d))}
      ${kv('Run-up, 60 sessions', sgn(d.runup_60d))}
      ${kv('Realised vol, 20d', f(d.vol_20d,0,'%'))}
    </div>
    <div class="panel"><h4>Reaction — does beating help?</h4>
      ${kv('Mean reaction, last 8', sgn(d.reac_mean_8))}
      ${kv('Median reaction, last 8', sgn(d.reac_median_8))}
      ${kv('Reaction/surprise slope', f(d.reaction_slope,4))}
      ${kv('Beat but fell', d.beat_and_fell_rate!=null?(d.beat_and_fell_rate*100).toFixed(0)+'%':'—')}
      ${kv('Last 4 reactions', lr)}
      ${kv('Quarters of history', f(d.n_quarters,0))}
      ${kv('Vol-target size', d.size_pct!=null?d.size_pct.toFixed(1)+'% of portfolio':'—')}
    </div>
    <div class="reasons">
      ${v.supports.map(s=>`<div class="reason"><span class="mark up">+</span><span>${s}</span></div>`).join('')}
      ${v.against.map(s=>`<div class="reason"><span class="mark down">−</span><span>${s}</span></div>`).join('')}
      ${v.neutral.map(s=>`<div class="reason"><span class="mark" style="color:var(--muted)">·</span><span>${s}</span></div>`).join('')}
      ${d.size_basis?`<div class="reason"><span class="mark" style="color:var(--muted)">§</span><span>Size basis: ${d.size_basis}. No directional view embedded.</span></div>`:''}
      <div class="caveat">${v.caveat||''}</div>
    </div>
  </div>`;
}

function render(){
  const r=rows(), tb=document.getElementById('tb');
  if(!r.length){tb.innerHTML='<tr><td colspan="11" class="empty">No matching events.</td></tr>';return;}
  tb.innerHTML=r.map(d=>{
    const v=d.verdict||{stance:'—',colour:'neutral'};
    const o=open.has(d.symbol);
    return `<tr class="row" data-s="${d.symbol}">
      <td><span class="sym">${d.symbol}</span><div class="nm">${d.name||''}</div></td>
      <td class="num">${d.report_date}</td>
      <td class="num">${d.days_to_report}</td>
      <td>${d.session||''}</td>
      <td class="num">${cap(d.market_cap)}</td>
      <td><span class="badge ${v.colour}">${v.stance}</span></td>
      <td class="num">${d.p_beat!=null?(d.p_beat*100).toFixed(0)+'%':'—'}</td>
      <td class="num">${f(d.implied_move_pct,1,'%')}</td>
      <td class="num">${f(d.realised_move_med_8,1,'%')}</td>
      <td class="num">${f(d.implied_vs_realised,2,'x')}</td>
      <td class="num">${sgn(d.runup_10d)}</td>
    </tr>` + (o?`<tr class="detail"><td colspan="11">${detail(d)}</td></tr>`:'');
  }).join('');
  tb.querySelectorAll('tr.row').forEach(tr=>tr.onclick=()=>{
    const s=tr.dataset.s; open.has(s)?open.delete(s):open.add(s); render();
  });
}

document.querySelectorAll('th[data-k]').forEach(th=>th.onclick=()=>{
  const k=th.dataset.k;
  if(sortKey===k) sortDir*=-1; else {sortKey=k; sortDir=1;}
  render();
});
document.getElementById('q').oninput=render;
document.getElementById('stance').onchange=render;
render();
"""


def build_html(df: pd.DataFrame, meta: dict) -> str:
    recs = to_records(df)
    data = json.dumps(recs, allow_nan=False)

    stances = {}
    for r in recs:
        s = (r.get("verdict") or {}).get("stance", "—")
        stances[s] = stances.get(s, 0) + 1

    with_imp = sum(1 for r in recs if r.get("implied_move_pct") is not None)
    with_rev = sum(1 for r in recs if r.get("rev_chg_30d") is not None)

    stat = lambda v, l: (f'<div class="stat"><div class="v">{v}</div>'  # noqa: E731
                         f'<div class="l">{l}</div></div>')

    return f"""<title>Priced In — earnings dashboard</title>
<style>{CSS}</style>
<div class="wrap">
  <h1>Priced In</h1>
  <div class="sub">Upcoming earnings, and what the market has already decided about them.
    Generated {html.escape(meta.get('generated', ''))} · universe {meta.get('universe', 0)} names ·
    snapshot history {meta.get('snap_rows', 0):,} rows</div>

  <div class="disclaimer"><strong>Not investment advice, and the direction column is
  not a signal.</strong> Fifteen directional strategies were backtested over 83,366
  prints from 2016&ndash;2026 against a random-entry control. <strong>None survived
  train, validate and holdout.</strong> The best (buy a &gt;5% beat, hold 20 days)
  cleared the first two periods and then failed out of sample. So the Stance column is
  a transparent summary of the panels, not an edge.
  <br><br>What <em>did</em> hold up across all three periods is magnitude: stocks in the
  quietest quartile of past earnings reactions went on to move <strong>0.54&times;</strong>
  as much as a random name (0.54 / 0.58 / 0.54 across train / validate / holdout), and the
  loudest quartile moved <strong>1.56&times;</strong> as much (1.55 / 1.47 / 1.56). That is
  what the Implied&divide;Realised column is built on. Position sizes are vol-targeting
  arithmetic with no view embedded.</div>

  <div class="stats">
    {stat(len(recs), 'events scored')}
    {stat(with_imp, 'with implied move')}
    {stat(with_rev, 'with revision data')}
    {stat(stances.get('Favourable', 0) + stances.get('Leaning favourable', 0), 'leaning favourable')}
    {stat(stances.get('Unfavourable', 0) + stances.get('Leaning unfavourable', 0), 'leaning unfavourable')}
  </div>

  <div class="controls">
    <input id="q" placeholder="Filter by ticker or name…" style="min-width:240px">
    <select id="stance">
      <option value="">All stances</option>
      <option value="pos">Favourable</option>
      <option value="lean-pos">Leaning favourable</option>
      <option value="neutral">Neutral</option>
      <option value="lean-neg">Leaning unfavourable</option>
      <option value="neg">Unfavourable</option>
    </select>
    <span style="color:var(--muted);font-size:13px">Click any row for the workings.</span>
  </div>

  <div class="tablewrap"><table>
    <thead><tr>
      <th data-k="symbol">Ticker</th>
      <th data-k="report_date">Reports</th>
      <th data-k="days_to_report">T−</th>
      <th data-k="session">Session</th>
      <th data-k="market_cap">Mkt cap</th>
      <th data-k="stance">Stance</th>
      <th data-k="p_beat">P(beat)</th>
      <th data-k="implied_move_pct">Implied</th>
      <th data-k="realised_move_med_8">Realised</th>
      <th data-k="implied_vs_realised">Imp÷Real</th>
      <th data-k="runup_10d">Run-up 10d</th>
    </tr></thead>
    <tbody id="tb"></tbody>
  </table></div>

  <footer>
    <strong>How to read this.</strong> <code>Implied</code> is the ATM straddle on the first
    expiry after the print, as a percentage of spot — what options are charging for the event.
    <code>Realised</code> is the median absolute one-day move over the last eight prints.
    A ratio well above 1 means expectations are expensive; well below 1 means cheap.
    <code>P(beat)</code> is the historical frequency with which similar-looking names beat,
    fitted on data through {html.escape(str(config.BACKTEST_TRAIN_END))} only.
    <code>Run-up 10d</code> is how much is already in the price going in.
    <br><br>Revision data comes from this project's own daily consensus snapshots, seeded with
    Yahoo's 90-day lookback. Coverage deepens every day the collector runs.
  </footer>
</div>
<script>window.__DATA__={data};{JS}</script>
"""


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        stream=sys.stdout)
    ap = argparse.ArgumentParser()
    ap.add_argument("--scorecard", default=str(config.RESULTS / "scorecard.pkl"))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    df = pd.read_pickle(args.scorecard)

    import db as _db
    con = _db.core(init=False)
    try:
        meta = {
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "universe": con.execute(
                "SELECT COUNT(*) c FROM universe WHERE delisted=0").fetchone()["c"],
            "snap_rows": con.execute(
                "SELECT COUNT(*) c FROM estimate_snapshots").fetchone()["c"],
        }
    finally:
        con.close()

    html_str = build_html(df, meta)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html_str)
    log.info("wrote %s (%.0f KB, %d events)", args.out,
             len(html_str) / 1024, len(df))


if __name__ == "__main__":
    main()
