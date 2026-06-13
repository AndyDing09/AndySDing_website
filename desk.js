/* ═══════════════════════════════════════════════════════════════════════
   Trading Desk — accounts + private Alpaca connection (Phase 1)
   Injects an account panel at the top of the Stocks tab. Talks to auth.php
   and broker.php. Keys are entered here and sent once over HTTPS to be
   encrypted+stored server-side; they are never stored in the browser and
   never returned by the server.
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var stocks = document.getElementById('stocks');
  if (!stocks) return;

  var state = { user: null, configured: true, status: null };
  var panel;

  function h(html) { var d = document.createElement('div'); d.innerHTML = html.trim(); return d.firstChild; }
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  function api(url, opts) {
    return fetch(url, opts).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, status: r.status, d: d }; }); });
  }

  function mount() {
    panel = document.getElementById('desk-account');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'desk-account';
      panel.className = 'desk-account';
      var slot = document.getElementById('desk-slot-account');
      if (slot) { slot.appendChild(panel); }
      else {
        var disc = document.getElementById('sa-disclaimer');
        if (disc && disc.parentNode) disc.parentNode.insertBefore(panel, disc.nextSibling);
        else stocks.querySelector('.stocks-inner').prepend(panel);
      }
    }
  }

  function render() {
    mount();
    if (window.AndyDeskTradeRefresh) setTimeout(window.AndyDeskTradeRefresh, 0); // refresh trade panel on auth/connect changes
    if (!state.configured) {
      panel.innerHTML = '<div class="desk-row"><span class="desk-badge off">Desk offline</span>' +
        '<span class="desk-muted">The trading desk isn\'t configured on the server yet.</span></div>';
      return;
    }
    if (!state.user) { renderAuth(); return; }
    renderAccount();
  }

  function renderAuth() {
    panel.innerHTML =
      '<div class="desk-head"><span class="desk-badge">🔒 Trading Desk</span>' +
      '<span class="desk-muted">Sign in to connect your Alpaca paper account. Invite-only.</span></div>' +
      '<form class="desk-form" id="desk-auth-form">' +
        '<input id="desk-user" placeholder="username" autocomplete="username" />' +
        '<input id="desk-pass" type="password" placeholder="password (8+ chars)" autocomplete="current-password" />' +
        '<input id="desk-invite" placeholder="invite code (sign-up only)" />' +
        '<div class="desk-form-btns">' +
          '<button type="submit" class="btn btn-primary btn-small" data-mode="login">Log in</button>' +
          '<button type="button" class="btn btn-ghost btn-small" id="desk-signup">Sign up</button>' +
        '</div>' +
      '</form>' +
      '<p class="desk-status" id="desk-auth-status"></p>';
    var form = document.getElementById('desk-auth-form');
    form.addEventListener('submit', function (e) { e.preventDefault(); doAuth('login'); });
    document.getElementById('desk-signup').addEventListener('click', function () { doAuth('signup'); });
  }

  function doAuth(action) {
    var st = document.getElementById('desk-auth-status');
    st.textContent = 'Working…'; st.className = 'desk-status';
    api('auth.php', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: action,
        username: document.getElementById('desk-user').value,
        password: document.getElementById('desk-pass').value,
        invite: document.getElementById('desk-invite').value
      })
    }).then(function (res) {
      if (res.ok && res.d.user) { state.user = res.d.user; loadStatus().then(render); }
      else { st.textContent = res.d.error || 'Could not sign in.'; st.className = 'desk-status err'; }
    }).catch(function () { st.textContent = 'Network error.'; st.className = 'desk-status err'; });
  }

  function renderAccount() {
    var modes = (state.status && state.status.modes) || {};
    var connected = Object.keys(modes);
    panel.innerHTML =
      '<div class="desk-head">' +
        '<span class="desk-badge on">🔒 ' + esc(state.user.username) + '</span>' +
        (connected.length ? '<span class="desk-muted">Connected: ' +
            connected.map(function (m) { return m.toUpperCase() + ' ' + esc(modes[m]); }).join(' · ') + '</span>'
          : '<span class="desk-muted">No broker connected yet.</span>') +
        '<button class="link-btn" id="desk-logout">Log out</button>' +
      '</div>' +
      '<div class="desk-acct" id="desk-acct"></div>' +
      '<details class="desk-connect"><summary>＋ Connect / manage Alpaca</summary>' +
        '<div class="desk-connect-body">' +
          '<div class="desk-modes">' +
            '<label><input type="radio" name="desk-mode" value="paper" checked> Paper <span class="desk-muted">(recommended)</span></label>' +
            '<label><input type="radio" name="desk-mode" value="live"> Live <span class="desk-warn">real money</span></label>' +
          '</div>' +
          '<div id="desk-live-warn" class="desk-live-warn hidden">' +
            '<strong>⚠ Live trading uses real money.</strong> This tool can place orders but <em>never</em> auto-submits — you confirm every one. ' +
            'You are trusting this site to hold keys that move real money. Paper is strongly recommended for the experiment. ' +
            '<label class="desk-ack"><input type="checkbox" id="desk-live-ack"> I understand and want to connect live keys.</label>' +
          '</div>' +
          '<input id="desk-key" placeholder="Alpaca API Key ID" autocomplete="off" />' +
          '<input id="desk-secret" type="password" placeholder="Alpaca API Secret" autocomplete="off" />' +
          '<button class="btn btn-primary btn-small" id="desk-connect-btn">Verify &amp; connect</button>' +
          (connected.length ? '<button class="link-btn danger" id="desk-disconnect">Disconnect ' + connected[0].toUpperCase() + '</button>' : '') +
          '<p class="desk-status" id="desk-connect-status"></p>' +
          '<p class="desk-fine">Keys are sent once over HTTPS, encrypted on the server, and never shown again. ' +
          'Get free paper keys at alpaca.markets → Paper Trading → API Keys. ' +
          '<strong>Firstrade can\'t be connected</strong> (no official API).</p>' +
        '</div>' +
      '</details>';

    document.getElementById('desk-logout').addEventListener('click', function () {
      api('auth.php', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'logout' }) })
        .then(function () { state.user = null; state.status = null; render(); });
    });
    panel.querySelectorAll('input[name="desk-mode"]').forEach(function (r) {
      r.addEventListener('change', function () {
        document.getElementById('desk-live-warn').classList.toggle('hidden', this.value !== 'live');
      });
    });
    document.getElementById('desk-connect-btn').addEventListener('click', doConnect);
    var dc = document.getElementById('desk-disconnect');
    if (dc) dc.addEventListener('click', function () {
      if (!confirm('Disconnect this Alpaca account? Your keys will be deleted from the server.')) return;
      api('broker.php', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'disconnect', mode: connected[0] }) })
        .then(function () { loadStatus().then(render); });
    });
    if (connected.length) loadAccount(connected[0]);
  }

  function doConnect() {
    var mode = (panel.querySelector('input[name="desk-mode"]:checked') || {}).value || 'paper';
    var st = document.getElementById('desk-connect-status');
    if (mode === 'live' && !document.getElementById('desk-live-ack').checked) {
      st.textContent = 'Tick the acknowledgment to connect live keys.'; st.className = 'desk-status err'; return;
    }
    st.textContent = 'Verifying with Alpaca…'; st.className = 'desk-status';
    api('broker.php', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'connect', mode: mode,
        key: document.getElementById('desk-key').value, secret: document.getElementById('desk-secret').value })
    }).then(function (res) {
      if (res.ok && res.d.ok) {
        st.textContent = '✓ Connected ' + mode + ' (' + res.d.masked + ').'; st.className = 'desk-status ok';
        document.getElementById('desk-key').value = ''; document.getElementById('desk-secret').value = '';
        loadStatus().then(render);
      } else { st.textContent = res.d.error || 'Could not connect.'; st.className = 'desk-status err'; }
    }).catch(function () { st.textContent = 'Network error.'; st.className = 'desk-status err'; });
  }

  function loadAccount(mode) {
    var box = document.getElementById('desk-acct');
    if (!box) return;
    box.innerHTML = '<span class="desk-muted">Loading account…</span>';
    api('broker.php?action=account&mode=' + encodeURIComponent(mode)).then(function (res) {
      if (!res.ok || !res.d.account) { box.innerHTML = '<span class="desk-muted">Account unavailable.</span>'; return; }
      var a = res.d.account;
      function money(v) { return v == null ? '—' : '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
      box.innerHTML =
        '<span class="desk-stat"><b>' + money(a.portfolio_value || a.equity) + '</b>portfolio (' + esc(a.mode) + ')</span>' +
        '<span class="desk-stat"><b>' + money(a.cash) + '</b>cash</span>' +
        '<span class="desk-stat"><b>' + money(a.buying_power) + '</b>buying power</span>' +
        '<span class="desk-stat"><b>' + esc(a.status || '—') + '</b>status</span>';
    }).catch(function () { box.innerHTML = '<span class="desk-muted">Account unavailable.</span>'; });
  }

  function loadStatus() {
    return api('broker.php?action=status').then(function (res) {
      state.status = res.ok ? res.d : null;
    }).catch(function () { state.status = null; });
  }

  function init() {
    api('auth.php?action=me').then(function (res) {
      state.configured = res.d ? res.d.configured !== false : true;
      state.user = (res.d && res.d.user) || null;
      if (state.user) loadStatus().then(render);
      else render();
    }).catch(function () { state.configured = false; render(); });
  }

  // Boot when the Stocks section first becomes active (lazy)
  var booted = false;
  function maybeBoot() { if (!booted && stocks.classList.contains('active')) { booted = true; init(); } }
  new MutationObserver(maybeBoot).observe(stocks, { attributes: true, attributeFilter: ['class'] });
  maybeBoot();
})();
