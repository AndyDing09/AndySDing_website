"""One-page EOD report (§7.4): self-contained HTML, auto-opens at 16:05 ET.

Sections: equity curve, today's trades with R-multiples, expectancy trend
(20-trade rolling), setup breakdown, top skipped signals with reasons,
data-quality incidents, tomorrow's carry-over names — and the red expectancy
banner when the rolling number is negative (the agent must never bury it).
"""

from __future__ import annotations

import html
import json
import webbrowser
from datetime import datetime
from pathlib import Path

from ..data.store import Store
from ..journal.expectancy import RollingMonitor, compute, cut_by
from ..journal.journal import SkippedOutcome


def _svg_equity_curve(points: list[float], w: int = 640, h: int = 160) -> str:
    if len(points) < 2:
        return "<p class='muted'>not enough closed trades for a curve</p>"
    lo, hi = min(points), max(points)
    span = (hi - lo) or 1.0
    step = w / (len(points) - 1)
    coords = " ".join(f"{i*step:.1f},{h - (p - lo) / span * (h - 12) - 6:.1f}"
                      for i, p in enumerate(points))
    last_color = "#2c7a4b" if points[-1] >= points[0] else "#a04537"
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="equity curve">'
            f'<polyline fill="none" stroke="{last_color}" stroke-width="2" '
            f'points="{coords}"/></svg>')


def build_eod_html(store: Store, day_start: datetime, day_end: datetime,
                   monitor: RollingMonitor, skipped: list[SkippedOutcome],
                   carryover: list[str], min_sample_n: int = 30) -> str:
    trades = store.trades_between(day_start, day_end)
    all_trades = store.last_trades(500)
    day = compute(trades, min_sample_n)
    monitor.update(all_trades)

    # equity curve: cumulative pnl across every stored trade
    curve, cum = [], 0.0
    for t in all_trades:
        cum += float(t["pnl_usd"])
        curve.append(cum)

    rows = "".join(
        f"<tr><td>{html.escape(str(t['symbol']))}</td><td>{html.escape(str(t['setup']))}</td>"
        f"<td class='n'>{float(t['entry_fill']):.2f}</td><td class='n'>{float(t['exit_fill']):.2f}</td>"
        f"<td class='n'>{int(t['qty'])}</td><td class='n {'pos' if float(t['realized_r'])>=0 else 'neg'}'>"
        f"{float(t['realized_r']):+.2f}R</td><td class='n'>{float(t['pnl_usd']):+.2f}</td>"
        f"<td>{html.escape(str(t['exit_reason']))}</td></tr>"
        for t in trades) or "<tr><td colspan='8' class='muted'>no trades today</td></tr>"

    setup_stats = cut_by(trades, "setup", min_sample_n)
    setup_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td class='n'>{s.n}</td>"
        f"<td class='n'>{s.win_rate:.0%}</td><td class='n'>{s.expectancy_r:+.2f}R</td>"
        f"<td class='muted'>{html.escape(s.note)}</td></tr>"
        for k, s in setup_stats.items()) or "<tr><td colspan='5' class='muted'>—</td></tr>"

    top_skipped = sorted(skipped, key=lambda s: s.would_r, reverse=True)[:3]
    skipped_rows = "".join(
        f"<tr><td>{html.escape(s.symbol)}</td><td>{html.escape(s.setup)}</td>"
        f"<td>{html.escape(s.reason)}</td><td class='n'>{s.would_have} "
        f"({s.would_r:+.1f}R)</td></tr>"
        for s in top_skipped) or "<tr><td colspan='4' class='muted'>none</td></tr>"

    incidents = store.conn.execute(
        "SELECT ts, kind, symbol, detail FROM incidents WHERE ts >= ? AND ts < ? ORDER BY ts",
        [day_start, day_end]).fetchall()
    incident_rows = "".join(
        f"<tr><td>{r[0]}</td><td>{html.escape(str(r[1]))}</td>"
        f"<td>{html.escape(str(r[2]))}</td><td>{html.escape(str(r[3]))}</td></tr>"
        for r in incidents) or "<tr><td colspan='4' class='muted'>none 🎉</td></tr>"

    banner = monitor.banner()
    banner_html = (f"<div class='redbanner'>{html.escape(banner.replace(chr(27)+'[1;31m','').replace(chr(27)+'[0m',''))}</div>"
                   if banner else "")
    roll = monitor.stats

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Warrior Desk EOD — {day_start.date().isoformat()}</title>
<style>
 body{{font:14px/1.5 system-ui,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#16181a}}
 h1{{font-size:22px}} h2{{font-size:16px;margin-top:28px}}
 table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
 td,th{{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left;font-size:13px}}
 .n{{text-align:right}} .pos{{color:#2c7a4b}} .neg{{color:#a04537}} .muted{{color:#888}}
 .redbanner{{background:#a04537;color:#fff;padding:12px 16px;border-radius:6px;font-weight:600;margin:16px 0}}
 .grid{{display:flex;gap:24px;flex-wrap:wrap}} .stat b{{font-size:20px;display:block}}
 footer{{margin-top:32px;color:#888;font-size:12px}}
</style></head><body>
<h1>Warrior Desk — End of Day · {day_start.date().isoformat()}</h1>
{banner_html}
<div class="grid">
 <div class="stat"><b>{day.n}</b>trades</div>
 <div class="stat"><b>{day.total_pnl:+.2f}</b>day P&amp;L (USD)</div>
 <div class="stat"><b>{day.expectancy_r:+.2f}R</b>expectancy/trade (day)</div>
 <div class="stat"><b>{roll.expectancy_usd:+.2f}</b>rolling-{monitor.window} expectancy (USD)</div>
 <div class="stat"><b>{roll.win_rate:.0%}</b>rolling win rate (CI {roll.win_rate_ci[0]:.0%}–{roll.win_rate_ci[1]:.0%})</div>
 <div class="stat"><b>{day.total_slippage:+.2f}</b>slippage cost (USD)</div>
</div>
<h2>Equity curve (all recorded trades)</h2>{_svg_equity_curve(curve)}
<h2>Today's trades</h2>
<table><tr><th>sym</th><th>setup</th><th>entry</th><th>exit</th><th>qty</th><th>R</th><th>P&amp;L</th><th>exit</th></tr>{rows}</table>
<h2>Setup breakdown</h2>
<table><tr><th>setup</th><th>n</th><th>win%</th><th>expectancy</th><th>sample</th></tr>{setup_rows}</table>
<h2>Top skipped signals (missed-R audit)</h2>
<table><tr><th>sym</th><th>setup</th><th>skip reason</th><th>would have</th></tr>{skipped_rows}</table>
<h2>Data-quality incidents</h2>
<table><tr><th>ts</th><th>kind</th><th>sym</th><th>detail</th></tr>{incident_rows}</table>
<h2>Tomorrow's carry-over watch</h2>
<p>{html.escape(', '.join(carryover) if carryover else 'none')}</p>
<footer>Simulated (paper) results with a slippage model applied — still optimistic vs live fills.
Educational; not financial advice. {html.escape(day.note or roll.note or '')}</footer>
</body></html>"""


def write_eod_report(store: Store, day_start: datetime, day_end: datetime,
                     monitor: RollingMonitor, skipped: list[SkippedOutcome],
                     carryover: list[str], reports_dir: str | Path,
                     auto_open: bool = False, min_sample_n: int = 30) -> Path:
    out = Path(reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"eod_{day_start.date().isoformat()}.html"
    # encoding is explicit: Windows defaults to cp1252, which cannot encode the
    # report's unicode (crashed on the operator's machine).
    dest.write_text(build_eod_html(store, day_start, day_end, monitor, skipped,
                                   carryover, min_sample_n), encoding="utf-8")
    if auto_open:
        try:
            webbrowser.open(dest.as_uri())
        except Exception:
            pass
    return dest
