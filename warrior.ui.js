/* ═══════════════════════════════════════════════════════════════════════
   Warrior Desk — website VIEWER (⚡ tab under Stocks)
   Renders the JSON snapshot the Python agent publishes to warrior.php. The
   website never trades; it shows the agent's 12-step gauntlet verdicts, the
   ranked watchlist, the journal summary, and graduation progress. Educational.
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var mount;
  var timer = null;

  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
  function api(url, opts) {
    return fetch(url, opts).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, status: r.status, d: d }; }); });
  }
  function money(v) { return (v == null) ? 'n/a' : '$' + Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }); }
  function pct(v) { return (v == null) ? 'n/a' : (Number(v) * 100).toFixed(1) + '%'; }
  function num(v, d) { return (v == null) ? 'n/a' : Number(v).toFixed(d == null ? 2 : d); }
  function ago(sec) {
    if (sec == null) return '';
    if (sec < 60) return sec + 's ago';
    if (sec < 3600) return Math.floor(sec / 60) + 'm ago';
    return Math.floor(sec / 3600) + 'h ago';
  }

  function gradeBadge(g) {
    var cls = g === 'A' ? 'wd-a' : (g === 'B' ? 'wd-b' : 'wd-c');
    return '<span class="wd-grade ' + cls + '">' + esc(g) + '</span>';
  }

  function load() {
    if (!mount) return;
    api('warrior.php?action=snapshot').then(function (res) {
      if (res.status === 401) { return renderSignin(); }
      if (!res.ok) { return renderMsg('Could not load the Warrior feed (' + res.status + ').'); }
      if (!res.d.snapshot) { return renderMsg(res.d.hint || 'No snapshot published yet.'); }
      render(res.d);
    }).catch(function () { renderMsg('Network error loading the Warrior feed.'); });
  }

  function renderMsg(msg) {
    mount.innerHTML = '<div class="sa-panel wd-empty"><p>' + esc(msg) + '</p>' +
      '<p class="sa-muted">On your computer, run <code>warrior publish</code> (or <code>warrior run</code>) ' +
      'with <code>WARRIOR_PUBLISH_URL</code> set to this site\'s <code>warrior.php</code>.</p></div>';
  }
  function renderSignin() {
    mount.innerHTML = '<div class="sa-panel wd-empty"><p>Sign in on the ' +
      '<strong>🧭 Research &amp; trading desk</strong> tab to view your private Warrior feed.</p></div>';
  }

  function render(payload) {
    var s = payload.snapshot;
    var stale = payload.stale ? '<span class="wd-stale">stale</span>' : '';
    var html = '';

    // header
    html += '<div class="wd-top">' +
      '<div><span class="wd-mode">' + esc(s.mode) + '</span> ' +
      '<span class="sa-muted">as of ' + esc(ago(payload.age_seconds)) + '</span> ' + stale + '</div>' +
      '<div class="wd-actions">' +
      '<input id="wd-ticker" placeholder="ticker" maxlength="12" />' +
      '<button class="btn btn-ghost btn-small" id="wd-req">Run gauntlet</button>' +
      '<button class="btn btn-ghost btn-small" id="wd-refresh">↻</button>' +
      '</div></div>';

    // session strip
    var ses = s.session || {};
    html += '<div class="wd-strip">' +
      cell('Window', esc(ses.window)) +
      cell('Day P&L', money(ses.day_pnl)) +
      cell('Trades', esc(ses.trades_today)) +
      cell('Losses', esc(ses.consecutive_losses)) +
      cell('Open', esc(ses.open_positions)) +
      cell('Equity', money(s.account_equity)) +
      (ses.halted ? '<div class="wd-halt">HALTED — ' + esc(ses.halt_reason) + '</div>' : '') +
      '</div>';

    // proposals
    html += '<h4 class="wd-h">Signals</h4>';
    if (!s.proposals || !s.proposals.length) {
      html += '<p class="sa-muted">No setups evaluated yet. Type a ticker above to ask the agent.</p>';
    } else {
      s.proposals.slice().reverse().forEach(function (p) { html += proposalCard(p); });
    }

    // watchlist
    if (s.watchlist && s.watchlist.length) {
      html += '<h4 class="wd-h">Watchlist (movers)</h4><table class="wd-table"><thead><tr>' +
        '<th>Sym</th><th>Price</th><th>Gap</th><th>RVOL</th><th>Score</th></tr></thead><tbody>';
      s.watchlist.forEach(function (c) {
        html += '<tr class="wd-watch" data-sym="' + esc(c.symbol) + '"><td>' + esc(c.symbol) + '</td>' +
          '<td>' + num(c.price) + '</td><td>' + pct(c.gap_pct) + '</td><td>' + num(c.rvol, 1) + 'x</td>' +
          '<td>' + num(c.score, 2) + '</td></tr>';
      });
      html += '</tbody></table>';
    }

    // journal today + stats + graduation
    html += statsBlock(s);

    html += '<p class="wd-disc">' + esc(s.disclaimer || '') + '</p>';
    mount.innerHTML = html;
    wire();
  }

  function cell(label, val) {
    return '<div class="wd-cell"><span class="wd-cell-l">' + label + '</span><span class="wd-cell-v">' + val + '</span></div>';
  }

  function proposalCard(p) {
    var approved = p.approved;
    var verdict = approved
      ? '<span class="wd-ok">✓ ' + esc(p.approval || 'approved') + '</span>'
      : '<span class="wd-no">✗ rejected</span>';
    var head = '<div class="wd-card-head">' + gradeBadge(p.grade) +
      '<span class="wd-sym">' + esc(p.symbol) + '</span>' +
      '<span class="wd-tag">' + esc(p.pattern) + '</span>' +
      '<span class="wd-tag">' + esc(p.window) + '</span>' +
      verdict + (p.triggered ? '<span class="wd-trig">● triggered</span>' : '<span class="wd-wait">waiting for breakout</span>') +
      '</div>';

    var plan = '';
    if (approved) {
      plan = '<div class="wd-plan">' +
        '<b>BUY ' + esc(p.shares) + '</b> ' + esc(p.symbol) + ' @ <b>' + num(p.entry) + '</b>' +
        ' · STOP <b>' + num(p.stop) + '</b> · TARGET <b>' + num(p.target) + '</b>' +
        ' · R:R ' + num(p.reward_risk, 1) + ' · risk ' + money(p.risk_dollars) +
        ' · ' + pct(p.position_pct) + ' of acct</div>';
    } else {
      plan = '<div class="wd-reasons">' + esc((p.reasons || []).join('; ')) + '</div>';
    }

    var thesis = p.thesis ? '<p class="wd-thesis">' + esc(p.thesis) + '</p>' : '';

    // details: metric table + 12-step trace
    var metrics = '';
    if (p.metrics) {
      metrics = '<table class="wd-metrics">';
      Object.keys(p.metrics).forEach(function (k) {
        var v = p.metrics[k];
        if (v === null || typeof v === 'object') return;
        metrics += '<tr><td>' + esc(k) + '</td><td>' + esc(v) + '</td></tr>';
      });
      metrics += '</table>';
    }
    var steps = '';
    if (p.steps && p.steps.length) {
      steps = '<ol class="wd-steps">';
      p.steps.forEach(function (st) {
        var mk = st.status === 'PASS' ? '✓' : (st.status === 'FAIL' ? '✗' : (st.status === 'SKIP' ? '–' : '·'));
        steps += '<li class="wd-step-' + esc(st.status) + '"><b>' + mk + ' ' + esc(st.name) +
          '</b>: ' + esc(st.detail) + '</li>';
      });
      steps += '</ol>';
    }
    var details = '<details class="wd-details"><summary>12-step trace &amp; metrics</summary>' +
      '<div class="wd-grid2"><div>' + steps + '</div><div>' + metrics + '</div></div></details>';

    return '<div class="wd-card ' + (approved ? 'wd-card-ok' : 'wd-card-no') + '">' +
      head + plan + thesis + details + '</div>';
  }

  function statsBlock(s) {
    var html = '<div class="wd-grid2 wd-bottom">';
    var j = s.journal_today;
    if (j) {
      html += '<div class="sa-panel"><h4>Today</h4>' +
        '<p>' + esc(j.counts.taken) + ' taken · ' + esc(j.counts.skipped) + ' skipped · ' +
        esc(j.counts.rejected) + ' rejected</p>' +
        '<p>closed ' + esc(j.closed) + ' · win rate ' + pct(j.win_rate) +
        ' · expectancy ' + money(j.expectancy) + '</p>' +
        '<ul class="wd-rules">' + (j.rules || []).map(function (r) {
          return '<li>' + (r[1] ? '☑' : '☐') + ' ' + esc(r[0]) + '</li>';
        }).join('') + '</ul></div>';
    }
    var st = s.stats, g = s.graduation;
    if (st) {
      html += '<div class="sa-panel"><h4>Track record &amp; graduation</h4>' +
        '<p>' + esc(st.n) + ' trades · win rate ' + pct(st.win_rate) +
        ' · PF ' + (st.profit_factor == null ? 'n/a' : num(st.profit_factor)) +
        ' · expectancy ' + money(st.expectancy) + ' (' + num(st.expectancy_r, 2) + 'R)</p>' +
        '<p>total ' + money(st.total_pnl) + ' · max DD ' + pct(st.max_drawdown_pct) + '</p>';
      if (g) {
        html += '<ul class="wd-rules">' + g.criteria.map(function (c) {
          return '<li>' + (c.met ? '☑' : '☐') + ' ' + esc(c.detail) + '</li>';
        }).join('') + '</ul>' +
          '<p class="' + (g.eligible ? 'wd-ok' : 'wd-no') + '">' +
          (g.eligible ? 'Eligible on these metrics (live still needs the multi-lock).'
            : 'Not eligible for live yet — keep paper trading.') + '</p>';
      }
      html += '</div>';
    }
    return html + '</div>';
  }

  function requestTicker(sym) {
    sym = (sym || '').trim().toUpperCase();
    if (!sym) return;
    api('warrior.php?action=request', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym })
    }).then(function (res) {
      var note = document.getElementById('wd-note');
      if (note) note.remove();
      var el = document.createElement('p');
      el.id = 'wd-note';
      el.className = 'sa-muted';
      el.textContent = res.ok ? (sym + ' queued — your running agent will evaluate it shortly.')
        : (res.d.error || 'Could not queue that ticker.');
      mount.prepend(el);
      if (res.ok) setTimeout(load, 6000);
    });
  }

  function wire() {
    var rb = document.getElementById('wd-refresh');
    if (rb) rb.addEventListener('click', load);
    var req = document.getElementById('wd-req');
    var inp = document.getElementById('wd-ticker');
    if (req && inp) {
      req.addEventListener('click', function () { requestTicker(inp.value); });
      inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') requestTicker(inp.value); });
    }
    mount.querySelectorAll('.wd-watch').forEach(function (row) {
      row.addEventListener('click', function () { requestTicker(row.getAttribute('data-sym')); });
    });
  }

  // Public hook: called the first time the ⚡ Warrior sub-tab is opened.
  window.AndyWarriorOpen = function () {
    mount = document.getElementById('warrior-mount');
    if (!mount) return;
    load();
    if (timer) clearInterval(timer);
    // light auto-refresh while the tab exists
    timer = setInterval(function () {
      var pane = document.getElementById('sa-pane-warrior');
      if (pane && !pane.classList.contains('hidden')) load();
    }, 30000);
  };
})();
