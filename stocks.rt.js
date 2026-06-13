/* ═══════════════════════════════════════════════════════════════════════
   AndyStockAnalysis — near-real-time price updates
   Polls stocks.php?action=realtime (Finnhub, key hidden server-side) and
   live-updates the prices already on screen. ~2s on an open stock, ~10s for
   the watchlist. Completely dormant unless a Finnhub key is configured, so
   the site falls back to delayed Yahoo data with zero change.

   NOTE: this is near-real-time (~1-2s), not sub-millisecond — that is a hard
   physical limit for any web dashboard (see the chat with Andy). Free Finnhub
   data is IEX real-time, a slice of total volume. Monitor here; execute in a
   real broker.
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  if (!document.getElementById('stocks')) return;

  var enabled = false;
  var timer = null;
  var last = {};

  function fmtUsd(n) {
    return '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function fmtPct(n) { return (n >= 0 ? '+' : '') + Number(n).toFixed(2) + '%'; }

  /* Find the symbols currently on screen and the elements that show them. */
  function targets() {
    var out = [];
    var dash = document.getElementById('sa-dash-view');
    var wl = document.getElementById('sa-watchlist-view');
    if (dash && !dash.classList.contains('hidden') && dash.getAttribute('data-symbol')) {
      out.push({ sym: dash.getAttribute('data-symbol'), priceEl: dash.querySelector('.sa-dash-now'), dash: true });
    } else if (wl && !wl.classList.contains('hidden')) {
      wl.querySelectorAll('.sa-wl-card[data-symbol]').forEach(function (c) {
        out.push({
          sym: c.getAttribute('data-symbol'),
          priceEl: c.querySelector('.sa-wl-price'),
          chgEl: c.querySelector('.sa-wl-change'),
          card: c
        });
      });
    }
    return out;
  }

  function flash(el, up) {
    if (!el) return;
    el.style.transition = 'none';
    el.style.color = up ? '#1f8b50' : '#d64045';
    requestAnimationFrame(function () {
      el.style.transition = 'color 0.9s ease';
      el.style.color = '';
    });
  }

  function liveBadge(q) {
    var header = document.getElementById('sa-dash-header');
    if (!header) return;
    var badge = document.getElementById('sa-live-badge');
    if (!badge) {
      badge = document.createElement('div');
      badge.id = 'sa-live-badge';
      badge.className = 'sa-live-badge';
      header.appendChild(badge);
    }
    badge.innerHTML = '<span class="sa-live-dot"></span> LIVE · ' + fmtPct(q.changePct) + ' today';
  }

  function apply(t, q) {
    if (!q || !q.ok || q.price == null) return;
    var prev = last[t.sym];
    var up = prev == null ? (q.changePct >= 0) : (q.price >= prev);
    last[t.sym] = q.price;
    if (t.priceEl) { t.priceEl.textContent = fmtUsd(q.price); flash(t.priceEl, up); }
    if (t.chgEl && q.changePct != null) {
      t.chgEl.className = 'sa-wl-change ' + (q.changePct >= 0 ? 'up' : 'down');
      t.chgEl.innerHTML = fmtPct(q.changePct) + ' <span>' + (q.change >= 0 ? '▲' : '▼') +
        ' ' + Math.abs(q.change || 0).toFixed(2) + '</span>';
    }
    if (t.card) { t.card.classList.toggle('up', q.changePct >= 0); t.card.classList.toggle('down', q.changePct < 0); }
    if (t.dash) liveBadge(q);
  }

  function poll() {
    if (!enabled) return;
    var ts = targets();
    if (!ts.length) { schedule(); return; }
    var syms = [];
    ts.forEach(function (t) { if (syms.indexOf(t.sym) === -1) syms.push(t.sym); });
    fetch('stocks.php?action=realtime&symbols=' + encodeURIComponent(syms.join(',')))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.enabled && d.quotes) {
          ts.forEach(function (t) { apply(t, d.quotes[t.sym]); });
        }
      })
      .catch(function () {})
      .finally(schedule);
  }

  function schedule() {
    clearTimeout(timer);
    if (document.hidden) { return; } // pause when tab not visible
    var dash = document.getElementById('sa-dash-view');
    var onDash = dash && !dash.classList.contains('hidden');
    timer = setTimeout(poll, onDash ? 2000 : 10000);
  }

  function swapLabel() {
    var disc = document.getElementById('sa-disclaimer');
    if (!disc) return;
    if (/delayed/i.test(disc.innerHTML)) {
      disc.innerHTML = disc.innerHTML.replace(
        /Prices are delayed[^.]*\./i,
        'Prices update <strong>live</strong> via Finnhub (IEX real-time, ~1–2s) — monitor here, place trades in your broker.'
      );
    }
  }

  function init() {
    fetch('stocks.php?action=rtstatus')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        enabled = !!(d && d.enabled);
        if (!enabled) return;
        swapLabel();
        document.addEventListener('visibilitychange', function () { if (!document.hidden) poll(); });
        poll();
      })
      .catch(function () { /* stays on delayed Yahoo */ });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
