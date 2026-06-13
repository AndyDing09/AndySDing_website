/* ═══════════════════════════════════════════════════════════════════════
   Desk Scorecard (Phase 3) — the desk's rules-based ideas vs. buy-and-hold SPY.
   Honest, hypothetical, no "AI vs human", no human portfolio. Reads scorecard.php.
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var stocks = document.getElementById('stocks');
  if (!stocks) return;
  var panel, loaded = false;

  function el(t, c, h) { var e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; }
  function pct(v) { return v == null || isNaN(v) ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%'; }
  function colors() {
    var cs = getComputedStyle(document.documentElement), dark = document.documentElement.dataset.theme === 'dark';
    return { text: (cs.getPropertyValue('--ink-2') || '#44555e').trim(), grid: dark ? 'rgba(255,255,255,0.05)' : 'rgba(14,26,34,0.06)',
      border: (cs.getPropertyValue('--border') || '#ddd').trim(), green: (cs.getPropertyValue('--green') || '#0d6e7d').trim(), ink3: (cs.getPropertyValue('--ink-3') || '#888').trim() };
  }

  function mount() {
    if (panel) return;
    panel = el('section', 'desk-score');
    panel.innerHTML =
      '<div class="db-head"><div><span class="db-eyebrow">SCORECARD</span>' +
      '<h3 class="db-title">Desk ideas vs. the market</h3></div>' +
      '<button class="btn btn-primary btn-small" id="sc-run">Load scorecard</button></div>' +
      '<p class="db-disclaimer"><strong>Hypothetical, educational experiment.</strong> A rules-based simulation of the desk\'s ' +
      'screen over the trailing ~year — no fees, slippage, taxes, or emotion. Short samples are noisy; this is <em>not</em> ' +
      'evidence the desk can beat the market, and most active strategies underperform a simple index fund.</p>' +
      '<div id="sc-body"></div>';
    var brief = document.querySelector('.desk-brief');
    var anchor = brief || document.getElementById('desk-account') || document.getElementById('sa-disclaimer');
    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(panel, anchor.nextSibling);
    else stocks.querySelector('.stocks-inner').prepend(panel);
    document.getElementById('sc-run').addEventListener('click', run);
  }

  function run() {
    var body = document.getElementById('sc-body'), btn = document.getElementById('sc-run');
    btn.disabled = true; btn.textContent = 'Running…';
    body.innerHTML = '<p class="sa-muted">Simulating the desk\'s screen over the past year…</p>';
    fetch('scorecard.php?action=scorecard').then(function (r) { return r.json(); }).then(function (d) {
      if (d.error) { body.innerHTML = '<p class="sa-muted">' + d.error + '</p>'; btn.disabled = false; btn.textContent = 'Load scorecard'; return; }
      render(d);
      btn.disabled = false; btn.textContent = '↻ Refresh';
    }).catch(function () { body.innerHTML = '<p class="sa-muted">Couldn\'t load the scorecard right now.</p>'; btn.disabled = false; btn.textContent = 'Load scorecard'; });
  }

  function render(d) {
    var body = document.getElementById('sc-body');
    body.innerHTML = '';
    var m = d.metrics;
    var beat = d.beat_market;
    // verdict banner
    body.appendChild(el('div', 'sc-verdict ' + (beat ? 'win' : 'lose'),
      '<strong>' + (beat ? 'Desk ahead of SPY' : 'Desk behind SPY') + '</strong> over ~' + d.window_days + ' trading days · ' +
      'desk ' + pct(m.desk_cum_pct) + ' vs SPY ' + pct(m.spy_cum_pct)));
    // metric tiles
    var tiles = [
      ['Desk return', pct(m.desk_cum_pct)], ['SPY return', pct(m.spy_cum_pct)],
      ['Sharpe (desk)', m.sharpe == null ? '—' : m.sharpe.toFixed(2)],
      ['Max drawdown', pct(m.max_drawdown_pct)], ['Win rate', m.win_rate_pct + '%'],
      ['Trades', String(m.trades)], ['Avg win', pct(m.avg_win_pct)], ['Avg loss', pct(m.avg_loss_pct)]
    ];
    var grid = el('div', 'sc-tiles');
    tiles.forEach(function (t) { grid.appendChild(el('div', 'sc-tile', '<span class="sc-tile-v">' + t[1] + '</span><span class="sc-tile-l">' + t[0] + '</span>')); });
    body.appendChild(grid);
    // equity curve
    body.appendChild(el('h4', 'db-section', 'Equity curve (rebased to 100)'));
    var chartBox = el('div', 'sc-chart'); body.appendChild(chartBox);
    body.appendChild(el('div', 'sc-legend', '<span class="sc-leg desk">● Desk</span> <span class="sc-leg spy">● SPY</span>'));
    drawChart(chartBox, d);
    // rules + verdict text
    body.appendChild(el('p', 'sa-mini-note', '<strong>Rules:</strong> ' + d.rules));
    body.appendChild(el('p', 'sc-verdict-text', d.verdict));
  }

  function drawChart(box, d) {
    if (!window.LightweightCharts) { box.innerHTML = '<p class="sa-muted">Chart library unavailable.</p>'; return; }
    box.innerHTML = '';
    var c = colors();
    var chart = LightweightCharts.createChart(box, {
      autoSize: true, height: 300,
      layout: { background: { type: 'solid', color: 'transparent' }, textColor: c.text, fontFamily: 'Inter, sans-serif' },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.border }, timeScale: { borderColor: c.border, timeVisible: false }
    });
    var desk = chart.addLineSeries({ color: c.green, lineWidth: 2, priceLineVisible: false });
    desk.setData(d.desk.curve.map(function (p) { return { time: p.t, value: p.v }; }));
    var spy = chart.addLineSeries({ color: c.ink3, lineWidth: 2, lineStyle: 2, priceLineVisible: false });
    spy.setData(d.spy.curve.map(function (p) { return { time: p.t, value: p.v }; }));
    chart.timeScale().fitContent();
  }

  function boot() { if (loaded) return; loaded = true; mount(); }
  function maybe() { if (stocks.classList.contains('active')) boot(); }
  new MutationObserver(maybe).observe(stocks, { attributes: true, attributeFilter: ['class'] });
  maybe();
})();
