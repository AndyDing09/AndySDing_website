/* ═══════════════════════════════════════════════════════════════════════
   Paper Trading Desk (Phase 4) — order ticket + positions + orders + journal.
   HUMAN-IN-THE-LOOP: every order goes through Review → Confirm; nothing is ever
   auto-submitted. Requires a signed-in user with a connected Alpaca account.
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var stocks = document.getElementById('stocks');
  if (!stocks) return;
  var panel, booted = false;
  var ctx = { user: null, modes: [] };

  function el(t, c, h) { var e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; }
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  function money(v) { return v == null || isNaN(v) ? '—' : '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function pct(v) { return v == null || isNaN(v) ? '—' : (v >= 0 ? '+' : '') + (Number(v) * 100).toFixed(2) + '%'; }
  function api(url, opts) { return fetch(url, opts).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); }); }

  function mount() {
    if (panel) return;
    panel = el('section', 'desk-trade');
    var sc = document.querySelector('.desk-score');
    var anchor = sc || document.querySelector('.desk-brief') || document.getElementById('desk-account');
    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(panel, anchor.nextSibling);
    else stocks.querySelector('.stocks-inner').prepend(panel);
  }

  function render() {
    mount();
    if (!ctx.user) {
      panel.innerHTML = '<div class="db-head"><div><span class="db-eyebrow">PAPER TRADING DESK</span>' +
        '<h3 class="db-title">Trade with your analysis on one screen</h3></div></div>' +
        '<p class="sa-muted">Sign in and connect an Alpaca account in the panel above to place paper orders.</p>';
      return;
    }
    if (!ctx.modes.length) {
      panel.innerHTML = '<div class="db-head"><div><span class="db-eyebrow">PAPER TRADING DESK</span>' +
        '<h3 class="db-title">Trade with your analysis on one screen</h3></div></div>' +
        '<p class="sa-muted">Connect an Alpaca account above (Connect / manage Alpaca) to place paper orders.</p>';
      return;
    }
    var mode = ctx.modes.indexOf('paper') !== -1 ? 'paper' : ctx.modes[0];
    panel.innerHTML =
      '<div class="db-head"><div><span class="db-eyebrow">PAPER TRADING DESK</span>' +
        '<h3 class="db-title">Order ticket</h3></div>' +
        (ctx.modes.length > 1
          ? '<select id="tr-mode" class="tr-mode">' + ctx.modes.map(function (m) { return '<option value="' + m + '"' + (m === mode ? ' selected' : '') + '>' + m.toUpperCase() + '</option>'; }).join('') + '</select>'
          : '<span class="db-chip ' + (mode === 'live' ? 'bear' : 'neutral') + '">' + mode.toUpperCase() + '</span>') +
      '</div>' +
      '<p class="db-disclaimer"><strong>Educational paper trading — not advice.</strong> Every order requires your explicit ' +
      'confirmation; nothing is auto-submitted. Most active traders underperform a simple index fund.</p>' +
      '<div class="tr-ticket">' +
        '<div class="tr-row">' +
          '<label>Symbol<input id="tr-sym" placeholder="AAPL" maxlength="12" autocomplete="off"></label>' +
          '<label>Side<select id="tr-side"><option value="buy">Buy</option><option value="sell">Sell</option></select></label>' +
          '<label>Qty<input id="tr-qty" type="number" min="0" step="1" value="1"></label>' +
          '<label>Type<select id="tr-type"><option value="market">Market</option><option value="limit">Limit</option><option value="stop">Stop</option><option value="stop_limit">Stop-limit</option></select></label>' +
        '</div>' +
        '<div class="tr-row tr-prices">' +
          '<label class="tr-lp hidden">Limit $<input id="tr-lp" type="number" min="0" step="0.01"></label>' +
          '<label class="tr-sp hidden">Stop $<input id="tr-sp" type="number" min="0" step="0.01"></label>' +
        '</div>' +
        '<label class="tr-note">Rationale / which desk idea (optional, journaled)<input id="tr-note" placeholder="e.g. desk bull case on NVDA breakout"></label>' +
        '<button class="btn btn-primary btn-small" id="tr-review">Review order →</button>' +
        '<div id="tr-confirm"></div>' +
        '<p class="desk-status" id="tr-status"></p>' +
      '</div>' +
      '<div class="tr-cols">' +
        '<div><h4 class="db-section">Positions</h4><div id="tr-positions" class="sa-muted">Loading…</div></div>' +
        '<div><h4 class="db-section">Recent orders</h4><div id="tr-orders" class="sa-muted">Loading…</div></div>' +
      '</div>' +
      '<h4 class="db-section">Trade journal</h4><div id="tr-journal"></div>';

    panel.querySelector('#tr-type').addEventListener('change', function () {
      panel.querySelector('.tr-lp').classList.toggle('hidden', !(this.value === 'limit' || this.value === 'stop_limit'));
      panel.querySelector('.tr-sp').classList.toggle('hidden', !(this.value === 'stop' || this.value === 'stop_limit'));
    });
    panel.querySelector('#tr-review').addEventListener('click', review);
    loadPositions(curMode()); loadOrders(curMode()); loadJournal();
  }

  function curMode() {
    var sel = document.getElementById('tr-mode');
    return sel ? sel.value : (ctx.modes.indexOf('paper') !== -1 ? 'paper' : ctx.modes[0]);
  }
  function orderFromForm() {
    return {
      mode: curMode(),
      symbol: (document.getElementById('tr-sym').value || '').trim().toUpperCase(),
      side: document.getElementById('tr-side').value,
      qty: parseFloat(document.getElementById('tr-qty').value) || 0,
      type: document.getElementById('tr-type').value,
      limit_price: parseFloat(document.getElementById('tr-lp').value) || undefined,
      stop_price: parseFloat(document.getElementById('tr-sp').value) || undefined,
      rationale: document.getElementById('tr-note').value || ''
    };
  }

  function review() {
    var st = document.getElementById('tr-status'); st.textContent = ''; st.className = 'desk-status';
    var o = orderFromForm();
    if (!o.symbol || o.qty <= 0) { st.textContent = 'Enter a symbol and quantity.'; st.className = 'desk-status err'; return;}
    var box = document.getElementById('tr-confirm'); box.innerHTML = '<p class="sa-muted">Checking…</p>';
    api('trade.php', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign({ action: 'preview' }, o)) })
      .then(function (res) {
        if (!res.ok || !res.d.preview) { box.innerHTML = ''; st.textContent = res.d.error || 'Could not preview.'; st.className = 'desk-status err'; return; }
        var p = res.d.preview, ord = p.order;
        var warn = (p.enough === false) ? '<div class="tr-warn">⚠ Estimated cost exceeds your buying power.</div>' : '';
        box.innerHTML =
          '<div class="tr-review">' +
            '<div class="tr-review-head">Review — <strong>' + esc(ord.side.toUpperCase()) + ' ' + esc(ord.qty) + ' ' + esc(ord.symbol) + '</strong> · ' + esc(ord.type.replace('_', '-')) + ' · ' + esc(p.mode.toUpperCase()) + '</div>' +
            '<div class="tr-review-grid">' +
              '<span>Ref price <b>' + money(p.ref_price) + '</b></span>' +
              '<span>Est. cost <b>' + money(p.est_cost) + '</b></span>' +
              '<span>Buying power <b>' + money(p.buying_power) + '</b></span>' +
            '</div>' + warn +
            '<div class="tr-confirm-btns">' +
              '<button class="btn btn-primary btn-small" id="tr-confirm-btn">✓ Confirm &amp; submit</button>' +
              '<button class="link-btn" id="tr-cancel">Cancel</button>' +
            '</div>' +
            '<p class="sa-mini-note">You are submitting a real ' + esc(p.mode) + ' order to Alpaca. This is the only step that places it.</p>' +
          '</div>';
        document.getElementById('tr-cancel').addEventListener('click', function () { box.innerHTML = ''; });
        document.getElementById('tr-confirm-btn').addEventListener('click', function () { submit(o); });
      }).catch(function () { box.innerHTML = ''; st.textContent = 'Network error.'; st.className = 'desk-status err'; });
  }

  function submit(o) {
    var st = document.getElementById('tr-status'); var box = document.getElementById('tr-confirm');
    var cbtn = document.getElementById('tr-confirm-btn'); if (cbtn) { cbtn.disabled = true; cbtn.textContent = 'Submitting…'; }
    api('trade.php', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({ action: 'submit', confirm: true, desk_pick: o.rationale ? o.rationale.slice(0, 60) : '' }, o)) })
      .then(function (res) {
        box.innerHTML = '';
        if (res.ok && res.d.ok) {
          st.textContent = '✓ Order ' + (res.d.order.status || 'submitted') + ': ' + o.side + ' ' + o.qty + ' ' + o.symbol + ' (' + res.d.order.mode + ').';
          st.className = 'desk-status ok';
          loadPositions(curMode()); loadOrders(curMode()); loadJournal();
        } else { st.textContent = res.d.error || 'Order rejected.'; st.className = 'desk-status err'; }
      }).catch(function () { st.textContent = 'Network error submitting order.'; st.className = 'desk-status err'; });
  }

  function loadPositions(mode) {
    var box = document.getElementById('tr-positions'); if (!box) return;
    api('trade.php?action=positions&mode=' + mode).then(function (res) {
      if (!res.ok) { box.innerHTML = '<span class="sa-muted">' + (res.d.error || 'Unavailable') + '</span>'; return; }
      var ps = res.d.positions || [];
      if (!ps.length) { box.innerHTML = '<span class="sa-muted">No open positions.</span>'; return; }
      box.innerHTML = '<table class="tr-table"><tr><th>Sym</th><th>Qty</th><th>Avg</th><th>Last</th><th>P/L</th></tr>' +
        ps.map(function (p) {
          var up = (parseFloat(p.unrealized_pl) || 0) >= 0;
          return '<tr><td>' + esc(p.symbol) + '</td><td>' + esc(p.qty) + '</td><td>' + money(p.avg_entry) + '</td><td>' + money(p.current) +
            '</td><td class="' + (up ? 'up' : 'down') + '">' + money(p.unrealized_pl) + ' (' + pct(p.unrealized_plpc) + ')</td></tr>';
        }).join('') + '</table>';
    }).catch(function () { box.innerHTML = '<span class="sa-muted">Unavailable</span>'; });
  }

  function loadOrders(mode) {
    var box = document.getElementById('tr-orders'); if (!box) return;
    api('trade.php?action=orders&mode=' + mode).then(function (res) {
      if (!res.ok) { box.innerHTML = '<span class="sa-muted">' + (res.d.error || 'Unavailable') + '</span>'; return; }
      var os = res.d.orders || [];
      if (!os.length) { box.innerHTML = '<span class="sa-muted">No orders yet.</span>'; return; }
      box.innerHTML = '<table class="tr-table"><tr><th>Sym</th><th>Side</th><th>Qty</th><th>Type</th><th>Status</th></tr>' +
        os.slice(0, 12).map(function (o) {
          return '<tr><td>' + esc(o.symbol) + '</td><td>' + esc(o.side) + '</td><td>' + esc(o.qty) + '</td><td>' + esc((o.type || '').replace('_', '-')) + '</td><td>' + esc(o.status) + '</td></tr>';
        }).join('') + '</table>';
    }).catch(function () { box.innerHTML = '<span class="sa-muted">Unavailable</span>'; });
  }

  function loadJournal() {
    var box = document.getElementById('tr-journal'); if (!box) return;
    box.innerHTML =
      '<form class="tr-jform" id="tr-jform">' +
        '<input id="tr-j-sym" placeholder="symbol" maxlength="12" style="max-width:90px">' +
        '<input id="tr-j-note" placeholder="note / rationale">' +
        '<button class="btn btn-ghost btn-small" type="submit">Log note</button>' +
      '</form><div id="tr-jlist"></div>';
    document.getElementById('tr-jform').addEventListener('submit', function (e) {
      e.preventDefault();
      var sym = (document.getElementById('tr-j-sym').value || '').trim().toUpperCase();
      var note = document.getElementById('tr-j-note').value || '';
      if (!sym || !note) return;
      api('trade.php', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'journal_add', symbol: sym, side: 'buy', qty: 0, rationale: note }) })
        .then(function () { document.getElementById('tr-j-sym').value = ''; document.getElementById('tr-j-note').value = ''; drawJournal(); });
    });
    drawJournal();
  }
  function drawJournal() {
    var list = document.getElementById('tr-jlist'); if (!list) return;
    api('trade.php?action=journal').then(function (res) {
      var j = (res.d && res.d.journal) || [];
      if (!j.length) { list.innerHTML = '<span class="sa-muted">No journal entries yet.</span>'; return; }
      list.innerHTML = j.map(function (e) {
        var dt = new Date((e.created_at || 0) * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        return '<div class="tr-jentry"><span class="tr-jsym">' + esc(e.symbol) + '</span> ' + esc(e.rationale || '') +
          '<span class="tr-jdate">' + dt + '</span></div>';
      }).join('');
    });
  }

  function init() {
    api('auth.php?action=me').then(function (res) {
      ctx.user = (res.d && res.d.user) || null;
      if (!ctx.user) { render(); return; }
      api('broker.php?action=status').then(function (s) {
        ctx.modes = (s.ok && s.d.modes) ? Object.keys(s.d.modes) : [];
        render();
      }).catch(function () { ctx.modes = []; render(); });
    }).catch(function () { render(); });
  }
  function boot() { if (booted) return; booted = true; init(); }
  function maybe() { if (stocks.classList.contains('active')) boot(); }
  new MutationObserver(maybe).observe(stocks, { attributes: true, attributeFilter: ['class'] });
  maybe();

  // let the account panel tell us to refresh after connect/login
  window.AndyDeskTradeRefresh = function () { booted = false; boot(); };
})();
