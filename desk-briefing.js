/* ═══════════════════════════════════════════════════════════════════════
   Pro Research Desk — morning briefing (Phase 2, server-built)
   Renders the schedulable briefing from briefing.php: market overview + regime,
   "Stocks to watch today" (ranked, with illustrative entry/stop/target and daily
   news), and the full two-sided idea list. Educational only — not advice, no
   confidence scores; entries are illustrative examples, not recommendations.
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var stocks = document.getElementById('stocks');
  if (!stocks) return;
  var panel, built = false, current = null;

  function el(t, c, h) { var e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; }
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  function money(v) { return v == null || isNaN(v) ? '—' : '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function pct(v) { return v == null || isNaN(v) ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%'; }
  function ago(ts) { if (!ts) return ''; var s = Date.now() / 1000 - ts; if (s < 3600) return Math.max(1, Math.round(s / 60)) + 'm'; if (s < 86400) return Math.round(s / 3600) + 'h'; return Math.round(s / 86400) + 'd'; }

  function mount() {
    if (panel) return;
    panel = el('section', 'desk-brief');
    panel.innerHTML =
      '<div class="db-head"><div><span class="db-eyebrow">RESEARCH DESK</span>' +
      '<h3 class="db-title">Morning briefing</h3><span class="db-stamp" id="db-stamp"></span></div>' +
      '<button class="btn btn-primary btn-small" id="db-run">Load briefing</button></div>' +
      '<p class="db-disclaimer">Educational analysis only — <strong>not financial advice</strong> and not a prediction. ' +
      'Entry/stop levels are <em>illustrative examples of what a trader might watch</em>, not recommendations. ' +
      'Most active traders underperform a simple index fund.</p>' +
      '<div id="db-body"></div>';
    var slot = document.getElementById('desk-slot-brief');
    if (slot) { slot.appendChild(panel); }
    else {
      var anchor = document.getElementById('desk-account') || document.getElementById('sa-disclaimer');
      if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(panel, anchor.nextSibling);
      else stocks.querySelector('.stocks-inner').prepend(panel);
    }
    document.getElementById('db-run').addEventListener('click', run);
    panel.addEventListener('click', function (e) {
      var btn = e.target.closest ? e.target.closest('.db-explain-btn') : null;
      if (btn) explainStock(btn);
    });
  }

  function run() {
    mount();
    var body = document.getElementById('db-body'), btn = document.getElementById('db-run');
    btn.disabled = true; btn.textContent = 'Loading…';
    body.innerHTML = '<p class="sa-muted">Pulling the market, your watch list, and the news…</p>';
    fetch('briefing.php?action=today').then(function (r) { return r.json(); }).then(function (d) {
      if (!d || d.error || !d.market) { body.innerHTML = '<p class="sa-muted">Briefing unavailable right now — try again shortly.</p>'; }
      else { render(d); }
      btn.disabled = false; btn.textContent = '↻ Refresh';
    }).catch(function () { body.innerHTML = '<p class="sa-muted">Couldn’t load the briefing.</p>'; btn.disabled = false; btn.textContent = 'Load briefing'; });
  }

  function render(d) {
    current = d;
    var body = document.getElementById('db-body');
    body.innerHTML = '';
    var stamp = document.getElementById('db-stamp');
    if (stamp && d.generated_at) stamp.textContent = 'as of ' + new Date(d.generated_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });

    // Market overview
    body.appendChild(el('h4', 'db-section', 'Market overview'));
    var ov = el('div', 'db-overview');
    var cells = (d.market.indices || []).map(function (ix) {
      var up = (ix.changePct || 0) >= 0;
      return '<div class="db-ov-cell"><span class="db-ov-name">' + esc(ix.name) + '</span>' +
        '<span class="db-ov-val">' + (ix.price != null ? money(ix.price) : '—') + '</span>' +
        '<span class="db-ov-chg ' + (up ? 'up' : 'down') + '">' + (ix.changePct != null ? pct(ix.changePct) : '') + '</span></div>';
    }).join('');
    ov.innerHTML = '<div class="db-ov-grid">' + cells + '</div>' +
      '<p class="db-regime"><b>Macro desk read:</b> market regime looks <strong>' + esc(d.market.regime) + '</strong>. Context, not a trade.</p>';
    body.appendChild(ov);

    // Stocks to watch today
    body.appendChild(el('h4', 'db-section', 'Stocks to watch today'));
    if (!d.watch || !d.watch.length) {
      body.appendChild(el('p', 'sa-muted', 'No standout setups in the universe today — sometimes the move is to do nothing.'));
    } else {
      var wg = el('div', 'db-idea-grid');
      d.watch.forEach(function (w) { wg.appendChild(watchCard(w)); });
      body.appendChild(wg);
    }

    // Full idea list
    body.appendChild(el('h4', 'db-section', 'All research ideas'));
    var ig = el('div', 'db-idea-grid');
    (d.ideas || []).forEach(function (a) { ig.appendChild(ideaCard(a)); });
    body.appendChild(ig);

    // AI synthesis
    var aiWrap = el('div', 'db-ai');
    aiWrap.innerHTML = '<button class="btn btn-ghost btn-small" id="db-ai-btn">✨ Written synthesis (AI)</button><div class="db-ai-out"></div>' +
      '<p class="sa-mini-note">Optional, two-sided educational summary via the site AI key.</p>';
    body.appendChild(aiWrap);
    document.getElementById('db-ai-btn').addEventListener('click', function () { aiSynthesis(d); });
  }

  function dirTag(dir) {
    if (dir > 0) return '<span class="db-news-dir up" title="Headline reads positive">📈 may lift</span>';
    if (dir < 0) return '<span class="db-news-dir down" title="Headline reads negative">📉 may weigh</span>';
    return '<span class="db-news-dir flat" title="Neutral / unclear">➖ neutral</span>';
  }
  function newsHtml(w) {
    var news = w.news, read = w.news_read;
    if (!news || !news.length) return '';
    var leanCls = read && read.lean > 0 ? 'up' : (read && read.lean < 0 ? 'down' : 'flat');
    return '<div class="db-news"><div class="db-news-h">Today’s news → likely effect</div>' +
      (read ? '<p class="db-news-read ' + leanCls + '"><b>News read:</b> ' + esc(read.text) + '</p>' : '') +
      news.map(function (n) {
        return '<a class="db-news-item" href="' + esc(n.link) + '" target="_blank" rel="noopener">' +
          '<span class="db-news-line">' + dirTag(n.dir) + ' ' + esc(n.title) + '</span>' +
          '<span class="db-news-meta">' + esc(n.publisher) + (n.time ? ' · ' + ago(n.time) + ' ago' : '') + '</span></a>';
      }).join('') +
      '<p class="db-news-fine">Automated keyword read of the headlines — an interpretation, not a prediction.</p></div>';
  }

  function entryHtml(e) {
    if (!e) return '';
    return '<div class="db-entry">' +
      '<div class="db-entry-type">' + esc(e.type) + '</div>' +
      '<div class="db-entry-rows">' +
        '<span><b>Entry zone</b> ' + esc(String(e.zone)) + '</span>' +
        (e.stop != null ? '<span><b>Illustrative stop</b> ' + money(e.stop) + '</span>' : '') +
        (e.target != null ? '<span><b>Illustrative target</b> ' + money(e.target) + '</span>' : '') +
      '</div>' +
      '<p class="db-entry-note">' + esc(e.note) + '</p></div>';
  }

  function planHtml(plan, open) {
    if (!plan || !plan.length) return '';
    return '<details class="db-plan"' + (open ? ' open' : '') + '><summary>📋 Step-by-step game plan</summary>' +
      '<ol class="db-plan-list">' + plan.map(function (s) { return '<li>' + esc(s) + '</li>'; }).join('') + '</ol>' +
      '<p class="db-plan-fine">A generic checklist built from the levels above — an example of <em>how</em> a disciplined trader sizes and manages a trade, not a recommendation to take this one.</p></details>';
  }

  function watchCard(w) {
    var c = el('article', 'db-idea db-watch');
    c.innerHTML =
      '<div class="db-idea-head"><div class="db-idea-id"><span class="db-idea-sym">' + esc(w.symbol) + '</span>' +
      '<span class="db-idea-name">' + esc((w.name || '').slice(0, 28)) + '</span></div>' +
      '<span class="db-idea-price">' + money(w.price) + '</span></div>' +
      '<div class="db-trigger">' + esc(w.trigger) + '</div>' +
      entryHtml(w.entry) +
      '<div class="db-cases">' +
        '<div class="db-case bull"><h5>Bull</h5><ul>' + (w.bull || []).map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></div>' +
        '<div class="db-case bear"><h5>Bear &amp; risks</h5><ul>' + (w.bear || []).map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></div>' +
      '</div>' +
      '<div class="db-levels"><span><b>Support</b> ' + money(w.support) + '</span><span><b>Resistance</b> ' + money(w.resistance) + '</span></div>' +
      planHtml(w.plan, true) +
      '<div class="db-explain"><button class="btn btn-ghost btn-small db-explain-btn" data-sym="' + esc(w.symbol) + '">✨ Explain this plan (AI)</button><div class="db-explain-out"></div></div>' +
      newsHtml(w);
    return c;
  }

  function explainStock(btn) {
    var sym = btn.getAttribute('data-sym');
    var out = btn.parentNode.querySelector('.db-explain-out');
    var w = (current && current.watch || []).filter(function (x) { return x.symbol === sym; })[0];
    if (!w) { out.textContent = 'No data for ' + sym + '.'; return; }
    btn.disabled = true; btn.textContent = 'Thinking…';
    var e = w.entry || {};
    var nr = w.news_read ? w.news_read.text : 'no notable news';
    var prompt = 'You are a balanced markets educator writing for a beginner. Turn this desk read on ' + sym +
      ' (' + (w.name || '') + ') into ONE short paragraph (3–5 sentences), plain English.\n' +
      'Setup: ' + (w.trigger || 'n/a') + '. Price ~$' + w.price + ', RSI ' + w.rsi + ', support $' + w.support + ', resistance $' + w.resistance + '.\n' +
      'Illustrative plan — entry: ' + (e.zone || 'n/a') + '; stop: ' + (e.stop != null ? '$' + e.stop : 'n/a') + '; target: ' + (e.target != null ? '$' + e.target : 'n/a') + '.\n' +
      'Steps: ' + (w.plan || []).join(' ') + '\nNews read: ' + nr + '\n' +
      'Explain what the setup means, what you\'d WAIT for before acting, and how you\'d manage risk (sizing + stop). Be explicitly TWO-SIDED — say plainly what would prove the idea wrong. Do NOT give a direct buy/sell recommendation and do NOT promise outcomes. End with a brief "Not advice." ';
    fetch('chat.php', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: [{ role: 'user', content: prompt }] }) })
      .then(function (r) { return r.json().then(function (x) { return { ok: r.ok, x: x }; }); })
      .then(function (res) { out.textContent = (res.ok && res.x.reply) ? res.x.reply : (res.x.error || 'AI explanation isn’t available right now.'); })
      .catch(function () { out.textContent = 'Couldn’t reach the AI service.'; })
      .finally(function () { btn.disabled = false; btn.textContent = '✨ Explain this plan (AI)'; });
  }

  function ideaCard(a) {
    var c = el('article', 'db-idea');
    c.innerHTML =
      '<div class="db-idea-head"><div class="db-idea-id"><span class="db-idea-sym">' + esc(a.symbol) + '</span>' +
      '<span class="db-idea-name">' + esc((a.name || '').slice(0, 28)) + '</span></div>' +
      '<span class="db-idea-price">' + money(a.price) + '</span></div>' +
      (a.trigger ? '<div class="db-trigger sm">' + esc(a.trigger) + '</div>' : '') +
      '<div class="db-cases">' +
        '<div class="db-case bull"><h5>Bull</h5><ul>' + (a.bull || []).map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></div>' +
        '<div class="db-case bear"><h5>Bear &amp; risks</h5><ul>' + (a.bear || []).map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></div>' +
      '</div>' +
      '<div class="db-levels"><span><b>Support</b> ' + money(a.support) + '</span><span><b>Resistance</b> ' + money(a.resistance) + '</span></div>' +
      planHtml(a.plan, false);
    return c;
  }

  function aiSynthesis(d) {
    var out = document.querySelector('.db-ai-out'), btn = document.getElementById('db-ai-btn');
    btn.disabled = true; btn.textContent = 'Thinking…';
    var watch = (d.watch || []).map(function (w) { return w.symbol + ' (' + w.trigger + ', $' + w.price + ')'; }).join('; ');
    var prompt = 'You are a balanced markets educator writing a short morning desk note for a student. Market regime: ' +
      d.market.regime + '. Stocks to watch: ' + watch + '. In 2 short paragraphs, plain English, summarize the day and the single biggest two-sided tension. ' +
      'Do NOT give buy/sell advice or price targets; stay educational and two-sided. End by reminding this is not advice.';
    fetch('chat.php', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: [{ role: 'user', content: prompt }] }) })
      .then(function (r) { return r.json().then(function (x) { return { ok: r.ok, x: x }; }); })
      .then(function (res) { out.textContent = (res.ok && res.x.reply) ? res.x.reply : (res.x.error || 'AI synthesis isn’t available right now.'); })
      .catch(function () { out.textContent = 'Couldn’t reach the AI service.'; })
      .finally(function () { btn.disabled = false; btn.textContent = '✨ Written synthesis (AI)'; });
  }

  window.AndyDeskBriefingRun = function () { run(); };
  function boot() { if (built) return; built = true; mount(); }
  function maybe() { if (stocks.classList.contains('active')) boot(); }
  new MutationObserver(maybe).observe(stocks, { attributes: true, attributeFilter: ['class'] });
  maybe();
})();
