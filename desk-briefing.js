/* ═══════════════════════════════════════════════════════════════════════
   Pro Research Desk — daily briefing (Phase 2)
   Synthesizes multiple "desk" perspectives (technical, momentum, trend,
   volatility/quant, valuation, macro, news) into a market overview and
   two-sided RESEARCH IDEAS — each with a thesis, bull case, bear case, key
   levels, and what would invalidate it. Educational only; no buy/sell verdict,
   no confidence scores. Reuses window.AndyStocks (data + analysis engine).
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var stocks = document.getElementById('stocks');
  if (!stocks) return;

  var S, A, Data;
  var INDICES = [['SPY', 'S&P 500'], ['QQQ', 'Nasdaq 100'], ['DIA', 'Dow 30'], ['^VIX', 'VIX']];
  var built = false, panel;

  function el(t, c, h) { var e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; }
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  function last(a) { return a && a.length ? a[a.length - 1] : null; }
  function n2(v) { return v == null || isNaN(v) ? '—' : Number(v).toFixed(2); }
  function pct(v) { return v == null || isNaN(v) ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%'; }
  function money(v) { return v == null || isNaN(v) ? '—' : '$' + Number(v).toFixed(2); }

  function mount() {
    if (panel) return;
    panel = el('section', 'desk-brief');
    panel.innerHTML =
      '<div class="db-head">' +
        '<div><span class="db-eyebrow">RESEARCH DESK</span>' +
        '<h3 class="db-title">Today\'s briefing</h3></div>' +
        '<button class="btn btn-primary btn-small" id="db-run">Run today’s briefing</button>' +
      '</div>' +
      '<p class="db-disclaimer">Educational analysis only — <strong>not financial advice</strong> and not a prediction. ' +
      'Every idea shows both sides and what would change it. Most active traders underperform a simple index fund. ' +
      'Do your own research.</p>' +
      '<div id="db-body"></div>';
    var disc = document.getElementById('sa-disclaimer');
    var acct = document.getElementById('desk-account');
    var anchor = acct || disc;
    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(panel, anchor.nextSibling);
    else stocks.querySelector('.stocks-inner').prepend(panel);
    document.getElementById('db-run').addEventListener('click', run);
  }

  /* ── One symbol → a two-sided idea built from the analysis engine ── */
  function analyzeSymbol(sym) {
    return Data.chart(sym, '6mo', '1d').then(function (d) {
      if (!d.candles || d.candles.length < 60) return null;
      var k = d.candles;
      var closes = k.map(function (c) { return c.c; });
      var highs = k.map(function (c) { return c.h; });
      var lows = k.map(function (c) { return c.l; });
      var vols = k.map(function (c) { return c.v; });
      var price = last(closes);
      var rsi = last(A.rsi(closes, 14));
      var macd = A.macd(closes); var mh = last(macd.hist);
      var sma20 = last(A.sma(closes, 20)), sma50 = last(A.sma(closes, 50)), sma200 = last(A.sma(closes, 200));
      var adxO = A.adx(highs, lows, closes); var adx = last(adxO.adx), pdi = last(adxO.plusDI), mdi = last(adxO.minusDI);
      var atr = last(A.atr(highs, lows, closes, 14));
      var bb = A.bollinger(closes, 20, 2); var bbU = last(bb.upper), bbL = last(bb.lower);
      var sr = A.supportResistance(highs, lows);
      var vol = A.std(A.returns(closes)) * Math.sqrt(252) * 100;

      // nearest support below / resistance above
      var supports = sr.filter(function (l) { return l.price < price; }).sort(function (a, b) { return b.price - a.price; });
      var resists = sr.filter(function (l) { return l.price > price; }).sort(function (a, b) { return a.price - b.price; });
      var nearSup = supports.length ? supports[0].price : (sma50 || lows[lows.length - 1]);
      var nearRes = resists.length ? resists[0].price : (bbU || highs[highs.length - 1]);

      var bull = [], bear = [];
      // Technical / trend desk
      if (sma50 != null && price > sma50) bull.push('Trading above its 50-day average — near-term uptrend.');
      else if (sma50 != null) bear.push('Below its 50-day average — near-term downtrend.');
      if (sma200 != null && price > sma200) bull.push('Above the 200-day average — longer-term trend is up.');
      else if (sma200 != null) bear.push('Below the 200-day average — longer-term trend is down.');
      if (sma50 != null && sma200 != null) {
        if (sma50 > sma200) bull.push('50-day is above the 200-day (golden-cross regime).');
        else bear.push('50-day is below the 200-day (death-cross regime).');
      }
      // Momentum desk
      if (mh != null && mh > 0) bull.push('MACD histogram positive — momentum rising.');
      else if (mh != null) bear.push('MACD histogram negative — momentum fading.');
      if (rsi != null) {
        if (rsi > 70) bear.push('RSI ' + rsi.toFixed(0) + ' — overbought; pullback risk.');
        else if (rsi < 30) bull.push('RSI ' + rsi.toFixed(0) + ' — oversold; possible bounce.');
        else bull.push('RSI ' + rsi.toFixed(0) + ' — neutral, room to move either way.');
      }
      // Trend strength desk
      if (adx != null) {
        if (adx > 25 && pdi > mdi) bull.push('ADX ' + adx.toFixed(0) + ' with +DI on top — a real uptrend, not chop.');
        else if (adx > 25 && mdi > pdi) bear.push('ADX ' + adx.toFixed(0) + ' with −DI on top — a real downtrend.');
        else bear.push('ADX ' + adx.toFixed(0) + ' — weak/choppy trend; breakouts may fail.');
      }
      // Volatility / quant desk
      if (atr != null) bear.push('Average daily swing ~' + money(atr) + ' (ATR) — size positions for that.');
      if (bbU != null && price >= bbU) bear.push('At/above the upper Bollinger band — stretched.');
      if (bbL != null && price <= bbL) bull.push('At/below the lower Bollinger band — stretched to the downside.');
      if (vol) (vol > 45 ? bear : bull).push('Annualized volatility ~' + vol.toFixed(0) + '% — ' + (vol > 45 ? 'high; expect big swings.' : 'moderate.'));

      return {
        sym: sym, name: d.name, price: price, currency: d.currency,
        rsi: rsi, adx: adx, mh: mh, sma50: sma50, sma200: sma200, atr: atr, vol: vol,
        bull: bull, bear: bear, nearSup: nearSup, nearRes: nearRes,
        fundamentals: null
      };
    }).catch(function () { return null; });
  }

  function deskChip(label, lean) {
    return '<span class="db-chip ' + lean + '">' + esc(label) + '</span>';
  }

  function ideaCard(a) {
    var c = el('article', 'db-idea');
    // desk lean chips
    var techLean = (a.sma50 != null && a.price > a.sma50) ? 'bull' : 'bear';
    var momLean = a.rsi == null ? 'neutral' : a.rsi > 70 ? 'bear' : a.rsi < 30 ? 'bull' : 'neutral';
    var trendLean = a.adx == null ? 'neutral' : a.adx > 25 ? 'bull' : 'neutral';
    var fund = a.fundamentals;
    var valLean = 'neutral', valTxt = 'Valuation —';
    if (fund && fund.peTrailing != null) {
      valLean = fund.peTrailing < 0 ? 'bear' : fund.peTrailing > 40 ? 'bear' : fund.peTrailing < 18 ? 'bull' : 'neutral';
      valTxt = 'P/E ' + n2(fund.peTrailing);
    }
    var agree = (techLean === 'bull' && momLean !== 'bear' && valLean !== 'bear');
    var split = !(techLean === momLean && (valLean === 'neutral' || valLean === techLean));

    c.innerHTML =
      '<div class="db-idea-head">' +
        '<div class="db-idea-id"><span class="db-idea-sym">' + esc(a.sym) + '</span>' +
        '<span class="db-idea-name">' + esc((a.name || '').slice(0, 32)) + '</span></div>' +
        '<span class="db-idea-price">' + money(a.price) + '</span>' +
      '</div>' +
      '<div class="db-desks">' +
        deskChip('Technical ' + (techLean === 'bull' ? '↑' : '↓'), techLean) +
        deskChip('Momentum (RSI ' + (a.rsi != null ? a.rsi.toFixed(0) : '—') + ')', momLean) +
        deskChip('Trend (ADX ' + (a.adx != null ? a.adx.toFixed(0) : '—') + ')', trendLean) +
        deskChip(valTxt, valLean) +
      '</div>' +
      '<p class="db-consensus">' + (split
        ? '⚖ The desks are <strong>split</strong> on this one — read both sides.'
        : '➤ The desks mostly <strong>agree</strong> here, but it’s still an idea to scrutinize, not a signal.') + '</p>' +
      '<div class="db-cases">' +
        '<div class="db-case bull"><h5>Bull case</h5><ul>' +
          (a.bull.length ? a.bull.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') : '<li>No strong bullish signals right now.</li>') +
        '</ul></div>' +
        '<div class="db-case bear"><h5>Bear case &amp; risks</h5><ul>' +
          (a.bear.length ? a.bear.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') : '<li>No strong bearish signals right now.</li>') +
        '</ul></div>' +
      '</div>' +
      '<div class="db-levels">' +
        '<span><b>Key support</b> ' + money(a.nearSup) + '</span>' +
        '<span><b>Key resistance</b> ' + money(a.nearRes) + '</span>' +
      '</div>' +
      '<p class="db-invalidate"><b>What would change the picture:</b> a daily close below ' + money(a.nearSup) +
        ' weakens the bull case; a close above ' + money(a.nearRes) + ' weakens the bear case.</p>';
    return c;
  }

  function run() {
    mount();
    var body = document.getElementById('db-body');
    var btn = document.getElementById('db-run');
    btn.disabled = true; btn.textContent = 'Running…';
    body.innerHTML = '<p class="sa-muted">The desk is reviewing the market and your watchlist…</p>';

    // 1) Market overview (indices + VIX + regime)
    var marketP = Data.quotes(['SPY', 'QQQ', 'DIA', '^VIX']).then(function (r) { return r.quotes || {}; }).catch(function () { return {}; });
    var spyTrendP = Data.chart('SPY', '6mo', '1d').then(function (d) {
      if (!d.candles) return null;
      var cl = d.candles.map(function (c) { return c.c; });
      return { price: last(cl), sma50: last(A.sma(cl, 50)) };
    }).catch(function () { return null; });

    var wl = S.getWatchlist();
    var ideasP = Promise.all(wl.map(analyzeSymbol)).then(function (rs) { return rs.filter(Boolean); });
    var fundP = Promise.all(wl.map(function (s) { return Data.fundamentals(s).catch(function () { return null; }); }));

    Promise.all([marketP, spyTrendP, ideasP, fundP]).then(function (res) {
      var mkt = res[0], spy = res[1], ideas = res[2], funds = res[3];
      // attach fundamentals
      var fundBySym = {};
      funds.forEach(function (f) { if (f && f.symbol) fundBySym[f.symbol] = f; });
      ideas.forEach(function (a) { a.fundamentals = fundBySym[a.sym] || null; });

      body.innerHTML = '';

      // Market overview
      var vix = mkt['^VIX'] && mkt['^VIX'].price;
      var regime = 'mixed';
      if (vix != null && spy) {
        var spyUp = spy.sma50 != null && spy.price > spy.sma50;
        if (vix < 16 && spyUp) regime = 'calm / risk-on — low volatility, index above its 50-day';
        else if (vix > 26) regime = 'stressed / risk-off — elevated volatility (VIX ' + vix.toFixed(0) + ')';
        else regime = (spyUp ? 'constructive' : 'cautious') + ' — VIX ' + vix.toFixed(0) + ', index ' + (spyUp ? 'above' : 'below') + ' its 50-day';
      }
      var ov = el('div', 'db-overview');
      var cells = INDICES.map(function (ix) {
        var q = mkt[ix[0]];
        var up = q && (q.changePct || 0) >= 0;
        return '<div class="db-ov-cell"><span class="db-ov-name">' + esc(ix[1]) + '</span>' +
          '<span class="db-ov-val">' + (q && q.ok ? money(q.price) : '—') + '</span>' +
          '<span class="db-ov-chg ' + (up ? 'up' : 'down') + '">' + (q && q.ok ? pct(q.changePct) : '') + '</span></div>';
      }).join('');
      ov.innerHTML = '<div class="db-ov-grid">' + cells + '</div>' +
        '<p class="db-regime"><b>Macro desk read:</b> market regime looks <strong>' + esc(regime) + '</strong>. ' +
        'This frames risk appetite — it is context, not a trade.</p>';
      body.appendChild(el('h4', 'db-section', 'Market overview'));
      body.appendChild(ov);

      // Consensus across watchlist
      var bullCount = ideas.filter(function (a) { return a.sma50 != null && a.price > a.sma50; }).length;
      var summary = el('p', 'db-summary',
        'Across your ' + ideas.length + ' watchlist names, <strong>' + bullCount + '</strong> are above their 50-day average and <strong>' +
        (ideas.length - bullCount) + '</strong> are below. Where the desks line up vs. disagree is flagged on each card. ' +
        'These are <strong>ideas to investigate</strong>, not recommendations.');
      body.appendChild(el('h4', 'db-section', 'Research ideas'));
      body.appendChild(summary);

      var grid = el('div', 'db-idea-grid');
      ideas.forEach(function (a) { grid.appendChild(ideaCard(a)); });
      body.appendChild(grid);

      // optional AI synthesis
      var aiWrap = el('div', 'db-ai');
      aiWrap.innerHTML = '<button class="btn btn-ghost btn-small" id="db-ai-btn">✨ Written synthesis (AI)</button><div class="db-ai-out"></div>' +
        '<p class="sa-mini-note">Optional. Asks Claude to summarize the above two-sidedly, for education. Uses the site AI key if set.</p>';
      body.appendChild(aiWrap);
      document.getElementById('db-ai-btn').addEventListener('click', function () { aiSynthesis(ideas, regime); });

      btn.disabled = false; btn.textContent = '↻ Re-run briefing';
    }).catch(function () {
      body.innerHTML = '<p class="sa-muted">Couldn’t build the briefing right now — try again shortly.</p>';
      btn.disabled = false; btn.textContent = 'Run today’s briefing';
    });
  }

  function aiSynthesis(ideas, regime) {
    var out = document.querySelector('.db-ai-out');
    var btn = document.getElementById('db-ai-btn');
    btn.disabled = true; btn.textContent = 'Thinking…';
    var lines = ideas.map(function (a) {
      return a.sym + ': price ' + money(a.price) + ', RSI ' + (a.rsi != null ? a.rsi.toFixed(0) : '—') +
        ', ADX ' + (a.adx != null ? a.adx.toFixed(0) : '—') + ', ' + (a.sma50 != null && a.price > a.sma50 ? 'above' : 'below') + ' 50d.';
    }).join(' ');
    var prompt = 'You are a balanced markets educator writing a brief desk note for a student. Market regime: ' + regime +
      '. Watchlist: ' + lines + ' In 2 short paragraphs, plain English, summarize what to watch today and name the biggest two-sided tension. ' +
      'Do NOT give buy/sell advice or price targets; stay educational and two-sided. End by reminding that this is not advice.';
    fetch('chat.php', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: [{ role: 'user', content: prompt }] }) })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        out.textContent = (res.ok && res.d.reply) ? res.d.reply : (res.d.error || 'AI synthesis isn’t available right now.');
      }).catch(function () { out.textContent = 'Couldn’t reach the AI service.'; })
      .finally(function () { btn.disabled = false; btn.textContent = '✨ Written synthesis (AI)'; });
  }

  function boot() {
    if (built) return;
    if (!window.AndyStocks) return;
    built = true;
    S = window.AndyStocks; A = S.A; Data = S.Data;
    mount();
  }
  function maybe() { if (stocks.classList.contains('active')) boot(); }
  new MutationObserver(maybe).observe(stocks, { attributes: true, attributeFilter: ['class'] });
  maybe();
})();
