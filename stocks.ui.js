/* ═══════════════════════════════════════════════════════════════════════
   AndyStockAnalysis — UI layer (views, charts, panels)
   Depends on window.AndyStocks (data + analysis + explanations).
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var rootSection = document.getElementById('stocks');
  if (!rootSection) return;

  var S;            // AndyStocks namespace, resolved at boot
  var A, Data, EXPLAIN;
  var booted = false, watchlistLoaded = false;

  /* ── number / format helpers ── */
  function fmtNum(n, d) {
    if (n == null || isNaN(n)) return '—';
    return Number(n).toLocaleString('en-US', { minimumFractionDigits: d || 0, maximumFractionDigits: d == null ? 2 : d });
  }
  function fmtCur(n, cur) {
    if (n == null || isNaN(n)) return '—';
    return (cur && cur !== 'USD' ? '' : '$') + fmtNum(n, 2) + (cur && cur !== 'USD' ? ' ' + cur : '');
  }
  function fmtPct(n, d) { return n == null || isNaN(n) ? '—' : (n >= 0 ? '+' : '') + fmtNum(n, d == null ? 2 : d) + '%'; }
  function fmtBig(n) {
    if (n == null || isNaN(n)) return '—';
    var abs = Math.abs(n);
    if (abs >= 1e12) return '$' + (n / 1e12).toFixed(2) + 'T';
    if (abs >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
    if (abs >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
    return '$' + fmtNum(n, 0);
  }
  function fmtRatio(n, d) { return n == null || isNaN(n) ? '—' : fmtNum(n, d == null ? 2 : d); }
  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  function ago(ts) {
    if (!ts) return '';
    var diff = Date.now() / 1000 - ts;
    if (diff < 3600) return Math.max(1, Math.round(diff / 60)) + 'm ago';
    if (diff < 86400) return Math.round(diff / 3600) + 'h ago';
    return Math.round(diff / 86400) + 'd ago';
  }

  /* ── theme colors for charts ── */
  function colors() {
    var cs = getComputedStyle(document.documentElement);
    var dark = document.documentElement.dataset.theme === 'dark';
    return {
      text: (cs.getPropertyValue('--ink-2') || '#56655d').trim(),
      grid: dark ? 'rgba(255,255,255,0.05)' : 'rgba(33,48,42,0.06)',
      border: dark ? 'rgba(255,255,255,0.12)' : 'rgba(33,48,42,0.13)',
      up: '#26a269', down: '#d64045',
      green: (cs.getPropertyValue('--green') || '#2e6b4e').trim(),
      clay: (cs.getPropertyValue('--clay') || '#b85c38').trim(),
      ink3: (cs.getPropertyValue('--ink-3') || '#8b968f').trim()
    };
  }

  /* ── explanation chip: label + value + expandable plain-English ── */
  function metricRow(label, value, explainKey, interp, cls) {
    var row = el('div', 'sa-metric' + (cls ? ' ' + cls : ''));
    var head = el('div', 'sa-metric-head');
    var lab = el('span', 'sa-metric-label', esc(label));
    if (explainKey && EXPLAIN[explainKey]) {
      var info = el('button', 'sa-info', 'ⓘ');
      info.setAttribute('aria-label', 'Explain ' + label);
      lab.appendChild(info);
    }
    var val = el('span', 'sa-metric-value', value);
    head.appendChild(lab); head.appendChild(val);
    row.appendChild(head);
    if (explainKey && EXPLAIN[explainKey]) {
      var exp = el('div', 'sa-metric-explain hidden');
      exp.innerHTML = '<p>' + esc(EXPLAIN[explainKey]) + '</p>' +
        (interp ? '<p class="sa-interp"><strong>This stock:</strong> ' + esc(interp) + '</p>' : '');
      row.appendChild(exp);
      row.querySelector('.sa-info').addEventListener('click', function (e) {
        e.stopPropagation();
        exp.classList.toggle('hidden');
      });
    }
    return row;
  }
  function panel(id, title) {
    var p = document.getElementById(id);
    p.innerHTML = '';
    p.appendChild(el('div', 'sa-panel-head', '<h4>' + esc(title) + '</h4>'));
    var body = el('div', 'sa-panel-body');
    p.appendChild(body);
    return body;
  }

  /* ═══ WATCHLIST VIEW ═══════════════════════════════════════════════════ */
  function sparkline(spark, up) {
    if (!spark || spark.length < 2) return '';
    var w = 90, h = 30, min = Math.min.apply(null, spark), max = Math.max.apply(null, spark);
    var rng = (max - min) || 1;
    var pts = spark.map(function (v, i) {
      return (i / (spark.length - 1) * w).toFixed(1) + ',' + (h - (v - min) / rng * h).toFixed(1);
    }).join(' ');
    var c = up ? '#26a269' : '#d64045';
    return '<svg class="sa-spark" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
      '<polyline points="' + pts + '" fill="none" stroke="' + c + '" stroke-width="1.5"/></svg>';
  }

  function renderWatchlist() {
    var wrap = document.getElementById('sa-watchlist');
    var list = S.getWatchlist();
    if (!list.length) { wrap.innerHTML = '<p class="sa-empty">Your watchlist is empty. Add a ticker above.</p>'; return; }
    // skeletons
    wrap.innerHTML = '';
    list.forEach(function (sym) {
      var card = el('div', 'sa-wl-card sa-loading');
      card.dataset.symbol = sym;
      card.innerHTML = '<div class="sa-wl-top"><span class="sa-wl-sym">' + esc(sym) + '</span>' +
        '<button class="sa-wl-remove" title="Remove" aria-label="Remove ' + esc(sym) + '">✕</button></div>' +
        '<div class="sa-wl-price">Loading…</div>';
      card.addEventListener('click', function (e) {
        if (e.target.closest('.sa-wl-remove')) return;
        openDashboard(sym);
      });
      card.querySelector('.sa-wl-remove').addEventListener('click', function (e) {
        e.stopPropagation();
        var nl = S.getWatchlist().filter(function (x) { return x !== sym; });
        S.setWatchlist(nl); renderWatchlist();
      });
      wrap.appendChild(card);
    });

    Data.quotes(list).then(function (res) {
      var q = res.quotes || {};
      list.forEach(function (sym) {
        var card = wrap.querySelector('.sa-wl-card[data-symbol="' + sym + '"]');
        if (!card) return;
        var d = q[sym];
        card.classList.remove('sa-loading');
        if (!d || !d.ok) {
          card.classList.add('sa-error');
          card.querySelector('.sa-wl-price').textContent = 'Data unavailable';
          return;
        }
        var up = (d.changePct || 0) >= 0;
        card.classList.add(up ? 'up' : 'down');
        card.innerHTML = '<div class="sa-wl-top"><span class="sa-wl-sym">' + esc(sym) + '</span>' +
          '<button class="sa-wl-remove" title="Remove" aria-label="Remove ' + esc(sym) + '">✕</button></div>' +
          '<div class="sa-wl-name">' + esc((d.name || '').slice(0, 30)) + '</div>' +
          '<div class="sa-wl-price">' + fmtCur(d.price, d.currency) + '</div>' +
          '<div class="sa-wl-change ' + (up ? 'up' : 'down') + '">' + fmtPct(d.changePct) +
          ' <span>' + (d.change >= 0 ? '▲' : '▼') + ' ' + fmtNum(Math.abs(d.change || 0), 2) + '</span></div>' +
          sparkline(d.spark, up);
        card.addEventListener('click', function (e) {
          if (e.target.closest('.sa-wl-remove')) return; openDashboard(sym);
        });
        card.querySelector('.sa-wl-remove').addEventListener('click', function (e) {
          e.stopPropagation();
          S.setWatchlist(S.getWatchlist().filter(function (x) { return x !== sym; })); renderWatchlist();
        });
      });
      checkAlerts(q);
    }).catch(function () {
      wrap.querySelectorAll('.sa-wl-card.sa-loading').forEach(function (c) {
        c.classList.remove('sa-loading'); c.classList.add('sa-error');
        c.querySelector('.sa-wl-price').textContent = 'Failed to load';
      });
    });
  }

  /* ═══ DASHBOARD ════════════════════════════════════════════════════════ */
  var dash = { symbol: null, range: '1y', interval: '1d', chart: null, sub: null,
    series: {}, overlays: {}, candles: [], osc: 'rsi', resizeHandler: null };

  var TIMEFRAMES = [
    { label: '1D', range: '1d', interval: '5m' }, { label: '1W', range: '5d', interval: '15m' },
    { label: '1M', range: '1mo', interval: '1d' }, { label: '3M', range: '3mo', interval: '1d' },
    { label: '6M', range: '6mo', interval: '1d' }, { label: '1Y', range: '1y', interval: '1d' },
    { label: '2Y', range: '2y', interval: '1d' }, { label: '5Y', range: '5y', interval: '1wk' },
    { label: 'Max', range: 'max', interval: '1mo' }
  ];

  function showView(which) {
    ['sa-watchlist-view', 'sa-compare-view', 'sa-dash-view'].forEach(function (id) {
      document.getElementById(id).classList.toggle('hidden', id !== which);
    });
  }

  function openDashboard(symbol) {
    dash.symbol = symbol; dash.range = '1y'; dash.interval = '1d';
    showView('sa-dash-view');
    document.getElementById('sa-dash-view').dataset.symbol = symbol;
    window.scrollTo({ top: 0, behavior: 'instant' });
    document.getElementById('sa-dash-header').innerHTML = '<div class="sa-dash-title">' + esc(symbol) + '</div><div class="sa-muted">Loading analysis…</div>';
    renderTimeframes();
    loadChartAndAnalyze();
    loadFundamentals();
    loadNews();
    renderAlertsPanel();
  }

  function renderTimeframes() {
    var tf = document.getElementById('sa-timeframes');
    tf.innerHTML = '';
    TIMEFRAMES.forEach(function (t) {
      var b = el('button', 'sa-tf' + (t.range === dash.range ? ' active' : ''), t.label);
      b.addEventListener('click', function () {
        dash.range = t.range; dash.interval = t.interval;
        tf.querySelectorAll('.sa-tf').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active');
        loadChartAndAnalyze();
      });
      tf.appendChild(b);
    });
  }

  var OVERLAYS = [
    { key: 'sma20', label: 'SMA 20' }, { key: 'sma50', label: 'SMA 50' },
    { key: 'sma200', label: 'SMA 200' }, { key: 'bb', label: 'Bollinger' },
    { key: 'vwap', label: 'VWAP' }, { key: 'psar', label: 'PSAR' },
    { key: 'ichimoku', label: 'Ichimoku' }, { key: 'sr', label: 'S/R levels' },
    { key: 'fib', label: 'Fibonacci' }
  ];
  var OSCILLATORS = [
    { key: 'rsi', label: 'RSI' }, { key: 'macd', label: 'MACD' },
    { key: 'stoch', label: 'Stochastic' }, { key: 'atr', label: 'ATR' },
    { key: 'adx', label: 'ADX' }, { key: 'obv', label: 'OBV' }
  ];

  function renderIndicatorToggles() {
    var wrap = document.getElementById('sa-indicator-toggles');
    wrap.innerHTML = '<span class="sa-toggle-label">Overlays:</span>';
    OVERLAYS.forEach(function (o) {
      if (dash.overlays[o.key] == null) dash.overlays[o.key] = (o.key === 'sma50' || o.key === 'sr');
      var b = el('button', 'sa-chip-toggle' + (dash.overlays[o.key] ? ' active' : ''), o.label);
      b.addEventListener('click', function () {
        dash.overlays[o.key] = !dash.overlays[o.key];
        b.classList.toggle('active', dash.overlays[o.key]);
        rebuildOverlays();
      });
      wrap.appendChild(b);
    });
    var sub = el('span', 'sa-toggle-label', 'Lower:');
    wrap.appendChild(sub);
    OSCILLATORS.forEach(function (o) {
      var b = el('button', 'sa-chip-toggle' + (o.key === dash.osc ? ' active' : ''), o.label);
      b.addEventListener('click', function () {
        dash.osc = o.key;
        wrap.querySelectorAll('.sa-osc').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active');
        buildSubChart();
      });
      b.classList.add('sa-osc');
      wrap.appendChild(b);
    });
  }

  function loadChartAndAnalyze() {
    var status = document.getElementById('sa-chart-status');
    status.textContent = 'Loading chart…';
    Data.chart(dash.symbol, dash.range, dash.interval).then(function (d) {
      if (!d.candles || d.candles.length < 2) { status.textContent = 'Not enough data for this timeframe.'; return; }
      dash.candles = d.candles; dash.currency = d.currency; dash.name = d.name;
      dash.prevClose = (d.prevClose != null && !isNaN(d.prevClose)) ? d.prevClose : null;
      dash.marketPrice = (d.marketPrice != null && !isNaN(d.marketPrice)) ? d.marketPrice : null;
      status.textContent = '';
      buildChart();
      renderIndicatorToggles();
      rebuildOverlays();
      buildSubChart();
      runAnalysis(); // signal, technicals, stats, risk, patterns, backtest, narrative, header
    }).catch(function (e) {
      status.textContent = 'Could not load chart: ' + (e.message || 'error');
    });
  }

  function disposeChart() {
    if (dash.chart) { try { dash.chart.remove(); } catch (e) {} dash.chart = null; }
    if (dash.sub) { try { dash.sub.remove(); } catch (e) {} dash.sub = null; }
    if (dash.resizeHandler) { window.removeEventListener('resize', dash.resizeHandler); dash.resizeHandler = null; }
    dash.series = {}; dash.overlaySeries = {};
  }

  function buildChart() {
    if (!window.LightweightCharts) {
      document.getElementById('sa-chart-status').textContent = 'Chart library failed to load (check your connection).';
      return;
    }
    disposeChart();
    var c = colors();
    var container = document.getElementById('sa-chart');
    container.innerHTML = '';
    var chart = LightweightCharts.createChart(container, {
      autoSize: true,
      layout: { background: { type: 'solid', color: 'transparent' }, textColor: c.text, fontFamily: 'Inter, sans-serif' },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.border },
      timeScale: { borderColor: c.border, timeVisible: dash.interval.indexOf('m') > -1, secondsVisible: false },
      crosshair: { mode: LightweightCharts.CrosshairMode ? LightweightCharts.CrosshairMode.Normal : 0 }
    });
    var candleSeries = chart.addCandlestickSeries({
      upColor: c.up, downColor: c.down, borderUpColor: c.up, borderDownColor: c.down,
      wickUpColor: c.up, wickDownColor: c.down
    });
    candleSeries.setData(dash.candles.map(function (k) {
      return { time: k.t, open: k.o, high: k.h, low: k.l, close: k.c };
    }));
    var volSeries = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: '' });
    volSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volSeries.setData(dash.candles.map(function (k) {
      return { time: k.t, value: k.v, color: k.c >= k.o ? 'rgba(38,162,105,0.4)' : 'rgba(214,64,69,0.4)' };
    }));
    chart.timeScale().fitContent();
    dash.chart = chart; dash.series.candle = candleSeries; dash.series.vol = volSeries;
    dash.resizeHandler = function () { /* autoSize handles width; subchart needs help */ };
  }

  function lineData(arr) {
    var out = [];
    for (var i = 0; i < arr.length; i++) {
      if (arr[i] != null && !isNaN(arr[i])) out.push({ time: dash.candles[i].t, value: arr[i] });
    }
    return out;
  }

  function rebuildOverlays() {
    if (!dash.chart) return;
    dash.overlaySeries = dash.overlaySeries || {};
    // remove existing overlay series + price lines
    Object.keys(dash.overlaySeries).forEach(function (k) {
      try { dash.chart.removeSeries(dash.overlaySeries[k]); } catch (e) {}
    });
    dash.overlaySeries = {};
    (dash.priceLines || []).forEach(function (pl) { try { dash.series.candle.removePriceLine(pl); } catch (e) {} });
    dash.priceLines = [];

    var closes = dash.candles.map(function (k) { return k.c; });
    var highs = dash.candles.map(function (k) { return k.h; });
    var lows = dash.candles.map(function (k) { return k.l; });
    var vols = dash.candles.map(function (k) { return k.v; });
    var c = colors();

    function addLine(key, arr, color, width) {
      var s = dash.chart.addLineSeries({ color: color, lineWidth: width || 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      s.setData(lineData(arr));
      dash.overlaySeries[key] = s;
    }
    if (dash.overlays.sma20) addLine('sma20', A.sma(closes, 20), '#3b82f6');
    if (dash.overlays.sma50) addLine('sma50', A.sma(closes, 50), c.clay);
    if (dash.overlays.sma200) addLine('sma200', A.sma(closes, 200), '#a855f7');
    if (dash.overlays.vwap) addLine('vwap', A.vwap(highs, lows, closes, vols), '#0ea5e9');
    if (dash.overlays.psar) {
      var sar = A.parabolicSAR(highs, lows);
      var s = dash.chart.addLineSeries({ color: c.ink3, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
      // render SAR as dots via markers would be heavy; use a thin dotted line
      s.setData(lineData(sar)); dash.overlaySeries.psar = s;
    }
    if (dash.overlays.bb) {
      var bb = A.bollinger(closes, 20, 2);
      addLine('bbU', bb.upper, 'rgba(120,120,160,0.6)', 1);
      addLine('bbM', bb.middle, 'rgba(120,120,160,0.4)', 1);
      addLine('bbL', bb.lower, 'rgba(120,120,160,0.6)', 1);
    }
    if (dash.overlays.ichimoku) {
      var ich = A.ichimoku(highs, lows, closes);
      addLine('tenkan', ich.tenkan, '#ef4444', 1);
      addLine('kijun', ich.kijun, '#3b82f6', 1);
      addLine('spanA', ich.spanA, 'rgba(38,162,105,0.5)', 1);
      addLine('spanB', ich.spanB, 'rgba(214,64,69,0.4)', 1);
    }
    // Price lines: S/R and Fibonacci
    if (dash.overlays.sr) {
      A.supportResistance(highs, lows).forEach(function (lv) {
        dash.priceLines.push(dash.series.candle.createPriceLine({
          price: lv.price, color: c.ink3, lineWidth: 1, lineStyle: 1,
          axisLabelVisible: true, title: 'S/R'
        }));
      });
    }
    if (dash.overlays.fib) {
      var look = closes.slice(-120);
      var hi = Math.max.apply(null, look), lo = Math.min.apply(null, look);
      A.fibRetrace(hi, lo).forEach(function (f) {
        dash.priceLines.push(dash.series.candle.createPriceLine({
          price: f.price, color: 'rgba(184,92,56,0.5)', lineWidth: 1, lineStyle: 2,
          axisLabelVisible: false, title: 'Fib ' + f.label
        }));
      });
    }
    // Pattern markers
    var pats = A.detectPatterns(dash.candles);
    var markers = pats.map(function (p) {
      return { time: dash.candles[p.idx].t, position: p.dir === 'bearish' ? 'aboveBar' : 'belowBar',
        color: p.dir === 'bullish' ? c.up : p.dir === 'bearish' ? c.down : c.ink3,
        shape: p.dir === 'bullish' ? 'arrowUp' : p.dir === 'bearish' ? 'arrowDown' : 'circle',
        text: p.name };
    });
    if (markers.length) dash.series.candle.setMarkers(markers);
  }

  function buildSubChart() {
    if (!window.LightweightCharts || !dash.candles.length) return;
    var container = document.getElementById('sa-subchart');
    container.innerHTML = '';
    if (dash.sub) { try { dash.sub.remove(); } catch (e) {} dash.sub = null; }
    var c = colors();
    var chart = LightweightCharts.createChart(container, {
      autoSize: true, height: 150,
      layout: { background: { type: 'solid', color: 'transparent' }, textColor: c.text, fontFamily: 'Inter, sans-serif' },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.border },
      timeScale: { borderColor: c.border, timeVisible: dash.interval.indexOf('m') > -1, visible: true }
    });
    var closes = dash.candles.map(function (k) { return k.c; });
    var highs = dash.candles.map(function (k) { return k.h; });
    var lows = dash.candles.map(function (k) { return k.l; });
    var vols = dash.candles.map(function (k) { return k.v; });
    function line(arr, color, w) {
      var s = chart.addLineSeries({ color: color, lineWidth: w || 1.5, priceLineVisible: false });
      s.setData(lineData(arr)); return s;
    }
    function hline(val, color) {
      // a horizontal reference line across the pane
      var s = chart.addLineSeries({ color: color, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      s.setData(dash.candles.map(function (k) { return { time: k.t, value: val }; }));
    }
    var label = '';
    if (dash.osc === 'rsi') { line(A.rsi(closes, 14), '#7c5cff'); hline(70, 'rgba(214,64,69,0.4)'); hline(30, 'rgba(38,162,105,0.4)'); label = 'RSI (14) — 70 overbought / 30 oversold'; }
    else if (dash.osc === 'macd') { var m = A.macd(closes); line(m.macd, '#3b82f6'); line(m.signal, c.clay);
      var hs = chart.addHistogramSeries({ priceLineVisible: false });
      hs.setData(m.hist.map(function (v, i) { return v == null ? null : { time: dash.candles[i].t, value: v, color: v >= 0 ? 'rgba(38,162,105,0.5)' : 'rgba(214,64,69,0.5)' }; }).filter(Boolean));
      label = 'MACD (12,26,9)'; }
    else if (dash.osc === 'stoch') { var st = A.stochastic(highs, lows, closes); line(st.k, '#3b82f6'); line(st.d, c.clay); hline(80, 'rgba(214,64,69,0.4)'); hline(20, 'rgba(38,162,105,0.4)'); label = 'Stochastic (14,3)'; }
    else if (dash.osc === 'atr') { line(A.atr(highs, lows, closes, 14), c.clay); label = 'ATR (14) — average daily $ range'; }
    else if (dash.osc === 'adx') { var ad = A.adx(highs, lows, closes); line(ad.adx, '#7c5cff', 2); line(ad.plusDI, '#26a269', 1); line(ad.minusDI, '#d64045', 1); hline(25, 'rgba(120,120,160,0.4)'); label = 'ADX/DMI — trend strength + direction'; }
    else if (dash.osc === 'obv') { line(A.obv(closes, vols), '#0ea5e9'); label = 'On-Balance Volume'; }
    chart.timeScale().fitContent();
    dash.sub = chart;
    var lbl = document.getElementById('sa-chart-status');
    if (lbl) lbl.textContent = label;
  }

  /* ── Analysis panels ── */
  function runAnalysis() {
    var k = dash.candles;
    var closes = k.map(function (c) { return c.c; });
    var highs = k.map(function (c) { return c.h; });
    var lows = k.map(function (c) { return c.l; });
    var vols = k.map(function (c) { return c.v; });
    var price = closes[closes.length - 1];
    var last = function (a) { return a[a.length - 1]; };

    var ind = {
      price: price,
      rsi: A.rsi(closes, 14), macd: A.macd(closes),
      sma20: A.sma(closes, 20), sma50: A.sma(closes, 50), sma200: A.sma(closes, 200), ema20: A.ema(closes, 20),
      adxObj: A.adx(highs, lows, closes), stochObj: A.stochastic(highs, lows, closes),
      cci: A.cci(highs, lows, closes), willr: A.williamsR(highs, lows, closes),
      atr: A.atr(highs, lows, closes, 14), bb: A.bollinger(closes, 20, 2),
      mfi: A.mfi(highs, lows, closes, vols), roc: A.roc(closes, 12)
    };
    var sigCtx = { closes: closes, rsi: ind.rsi, macd: ind.macd, sma20: ind.sma20, sma50: ind.sma50,
      sma200: ind.sma200, ema20: ind.ema20, adx: ind.adxObj.adx, plusDI: ind.adxObj.plusDI,
      minusDI: ind.adxObj.minusDI, stochK: ind.stochObj.k, cci: ind.cci, willr: ind.willr, price: price };
    var signal = A.computeSignals(sigCtx);

    renderHeader(price);
    renderSignalPanel(signal);
    renderGamePlan(ind, signal, closes, highs, lows, price, last);
    renderTechnicals(ind, last);
    renderStats(closes, price);
    renderRisk(closes, highs, lows, price, last(ind.atr));
    renderPatterns();
    renderBacktest(closes);
    renderNarrative(ind, signal, closes, price, last);
    renderAIPanel(ind, signal, price);
  }

  function renderHeader(price) {
    var h = document.getElementById('sa-dash-header');
    var k = dash.candles;
    // Current price + the TRUE prior-session close, so the daily change is the same
    // no matter which chart timeframe is selected (was previously computed off the
    // last two candles, which made it the weekly/intraday change on other timeframes).
    var cur = dash.marketPrice != null ? dash.marketPrice : price;
    var prev = dash.prevClose != null ? dash.prevClose : (k.length > 1 ? k[k.length - 2].c : cur);
    var first = k[0].c;
    var chg = cur - prev, pct = prev ? (chg / prev) * 100 : 0;
    var periodPct = first ? (cur - first) / first * 100 : 0;
    var up = pct >= 0;
    var tfLabel = (TIMEFRAMES.filter(function (t) { return t.range === dash.range; })[0] || {}).label || 'period';
    h.innerHTML =
      '<div class="sa-dash-id"><div class="sa-dash-title">' + esc(dash.symbol) + '</div>' +
      '<div class="sa-muted">' + esc(dash.name || '') + '</div></div>' +
      '<div class="sa-dash-price"><div class="sa-dash-now">' + fmtCur(cur, dash.currency) + '</div>' +
      '<div class="sa-dash-chg ' + (up ? 'up' : 'down') + '">' + (up ? '▲' : '▼') + ' ' + fmtPct(pct) + ' today' +
      ' <span class="sa-muted">· ' + fmtPct(periodPct) + ' over ' + esc(tfLabel) + '</span></div></div>';
  }

  function ratingMeter(score) {
    var pct = Math.round((score + 1) / 2 * 100);
    return '<div class="sa-meter"><div class="sa-meter-track"><div class="sa-meter-fill" style="width:' + pct + '%"></div>' +
      '<div class="sa-meter-needle" style="left:' + pct + '%"></div></div>' +
      '<div class="sa-meter-scale"><span>Bearish</span><span>Neutral</span><span>Bullish</span></div></div>';
  }

  function renderSignalPanel(sig) {
    var p = document.getElementById('sa-signal-panel');
    p.innerHTML = '';
    p.appendChild(el('div', 'sa-panel-head', '<h4>Signal summary — what the indicators collectively show</h4>'));
    var cls = sig.label.indexOf('Bull') > -1 ? 'bull' : sig.label.indexOf('Bear') > -1 ? 'bear' : 'neutral';
    var body = el('div', 'sa-panel-body');
    body.innerHTML =
      '<div class="sa-rating ' + cls + '">' + esc(sig.label) +
      '<span class="sa-rating-counts">' + sig.bull + ' bullish · ' + sig.neutral + ' neutral · ' + sig.bear + ' bearish</span></div>' +
      ratingMeter(sig.score);
    var grid = el('div', 'sa-signal-grid');
    sig.signals.forEach(function (s) {
      grid.appendChild(el('div', 'sa-signal-item ' + s.read,
        '<span class="sa-sig-name">' + esc(s.name) + '</span>' +
        '<span class="sa-sig-dot ' + s.read + '"></span>' +
        '<span class="sa-sig-note">' + esc(s.note) + '</span>'));
    });
    body.appendChild(grid);
    body.appendChild(el('p', 'sa-mini-note', 'An aggregate read, like TradingView\'s technical rating. It counts how many indicators lean each way right now — a snapshot of momentum and trend, not a forecast.'));
    p.appendChild(body);
  }

  /* ── Step-by-step game plan (educational; built from this stock's own levels) ── */
  function renderGamePlan(ind, sig, closes, highs, lows, price, last) {
    var b = panel('sa-plan-panel', 'Step-by-step game plan — when to buy & sell');
    var cur = dash.currency;
    function f(v) { return fmtCur(v, cur); }
    var sma20 = last(ind.sma20), sma50 = last(ind.sma50), sma200 = last(ind.sma200);
    var rsi = last(ind.rsi), atr = last(ind.atr) || price * 0.02;
    var levels = []; try { levels = A.supportResistance(highs, lows) || []; } catch (e) {}
    var supArr = levels.map(function (l) { return l.price; }).filter(function (p) { return p < price; });
    var resArr = levels.map(function (l) { return l.price; }).filter(function (p) { return p > price; });
    var support = supArr.length ? Math.max.apply(null, supArr) : Math.min.apply(null, lows.slice(-20));
    var resistance = resArr.length ? Math.min.apply(null, resArr) : Math.max.apply(null, highs.slice(-20));
    var hi3 = Math.max.apply(null, highs.slice(-63)), lo3 = Math.min.apply(null, lows.slice(-63));
    var up = (price > sma50) && (isNaN(sma200) || price > sma200);
    var trigger, type, stop = null, target = null, zone = '', ref = price, lean = 'flat';
    if (!isNaN(rsi) && rsi < 38 && (isNaN(sma200) || price > sma200)) { type = 'dip'; trigger = 'Oversold pullback in an uptrend'; lean = 'up'; ref = price; zone = f(Math.max(support, price * 0.985)) + '–' + f(price); stop = support - atr; target = !isNaN(sma50) ? sma50 : resistance; }
    else if (up && price <= hi3 * 1.03 && price >= hi3 * 0.97) { type = 'breakout'; trigger = 'Near a breakout'; lean = 'up'; ref = resistance; stop = resistance - 1.5 * atr; target = price + (hi3 - lo3) * 0.5; }
    else if (up && !isNaN(sma50) && price <= sma50 * 1.03) { type = 'pullback'; trigger = 'Pullback toward the 50-day'; lean = 'up'; ref = sma50; zone = f(sma50) + '–' + f(price); stop = sma50 - 1.5 * atr; target = resistance; }
    else if (!isNaN(rsi) && rsi > 75) { type = 'caution'; trigger = 'Overbought — caution'; lean = 'down'; }
    else if (up) { type = 'trend'; trigger = 'Healthy uptrend'; lean = 'up'; ref = sma50; zone = 'pullbacks toward ' + f(sma50); stop = (!isNaN(sma50) ? sma50 : price) - 1.5 * atr; target = resistance; }
    else { type = 'none'; trigger = 'No clean setup right now'; lean = 'down'; }

    var steps = [];
    if (type === 'none') {
      steps.push('No clean setup today — price is below its key averages with no trigger. The disciplined move is usually to WAIT.');
      steps.push('Add it to your watchlist. What would change things: a reclaim of the 50-day (' + f(sma50) + ') or a clear bounce off support (' + f(support) + ').');
      steps.push('Only then look at an entry near support with a stop just below it. Never average down into a falling stock just because it\'s cheaper.');
    } else if (type === 'caution') {
      steps.push('DON\'T chase here — it\'s overbought/extended (RSI ' + (isNaN(rsi) ? '—' : rsi.toFixed(0)) + '). Sit on your hands; chasing green candles is the #1 beginner mistake.');
      steps.push('Set a price alert for a cooldown toward ' + f(!isNaN(sma20) ? sma20 : sma50) + ' (the 20/50-day). Revisit the idea only then.');
      steps.push('If you already own it: consider trimming some into the strength and/or trailing a stop up to lock in gains.');
    } else {
      if (type === 'dip') steps.push('WAIT for the drop to steady near support (' + f(support) + ') — a green day or a higher low — instead of catching a falling knife.');
      else if (type === 'breakout') steps.push('WAIT for a daily CLOSE above ' + f(resistance) + ' on strong volume. No close above it = no trade yet.');
      else if (type === 'pullback') steps.push('WAIT for the pullback to reach the 50-day (' + f(sma50) + ') and actually bounce (a green candle, or it holds).');
      else steps.push('Trend is up — only act on PULLBACKS toward the 50-day (' + f(sma50) + '). Don\'t buy right after a big up day.');
      if (stop != null) { var risk = Math.abs(ref - stop); steps.push('SIZE IT FIRST (most important step): stop at ' + f(stop) + ' means risking ~' + f(risk) + ' per share. Risk only ~1% of your account → shares ≈ (1% of your account) ÷ ' + f(risk) + '.'); }
      if (type === 'breakout') steps.push('ENTER only after it confirms — buy on the close above ' + f(resistance) + ', or on a small pullback back to that level (a buy-stop order automates this).');
      else steps.push('ENTER with a LIMIT order around ' + (zone || ('~' + f(price))) + ' — a limit, not market, so you don\'t overpay on a spike.');
      if (stop != null) steps.push('PROTECT it immediately: place a stop-loss at ' + f(stop) + '. That\'s your "I was wrong" line — honor it, don\'t widen it to hope.');
      if (target != null) steps.push('TAKE PROFITS at the first target near ' + f(target) + ' (around resistance ' + f(resistance) + '). A common move: sell ~half there, then trail a stop on the rest.');
      steps.push('MANAGE: check once a day, not every tick. As it works in your favor, ratchet your stop UP toward break-even — never move it down.');
    }

    b.appendChild(el('div', 'sa-plan-setup ' + lean, 'Detected setup: <strong>' + esc(trigger) + '</strong>'));
    if (type !== 'none' && type !== 'caution') {
      b.appendChild(el('div', 'db-levels',
        '<span><b>Entry</b> ' + (zone || ('~' + f(price))) + '</span>' +
        (stop != null ? '<span><b>Stop</b> ' + f(stop) + '</span>' : '') +
        (target != null ? '<span><b>Target</b> ' + f(target) + '</span>' : '')));
    }
    var ol = el('ol', 'db-plan-list');
    steps.forEach(function (s) { ol.appendChild(el('li', null, esc(s))); });
    b.appendChild(ol);
    b.appendChild(el('p', 'sa-mini-note', 'A generic, educational checklist built from this stock\'s own levels — an example of <em>how</em> to size and manage a trade, <strong>not</strong> a recommendation to buy or sell. Levels are illustrative; you decide and you own the risk.'));
  }

  function interp(metric, val) {
    if (val == null || isNaN(val)) return null;
    switch (metric) {
      case 'rsi': return val > 70 ? 'At ' + val.toFixed(0) + ', it\'s in overbought territory.' : val < 30 ? 'At ' + val.toFixed(0) + ', it\'s oversold.' : 'At ' + val.toFixed(0) + ', it\'s neutral.';
      case 'beta': return val > 1.2 ? 'At ' + val.toFixed(2) + ', it swings more than the market.' : val < 0.8 ? 'At ' + val.toFixed(2) + ', it\'s steadier than the market.' : 'At ' + val.toFixed(2) + ', it roughly tracks the market.';
      case 'pe': return val < 0 ? 'Negative — the company isn\'t profitable on a trailing basis.' : val > 40 ? 'At ' + val.toFixed(1) + ', that\'s a rich valuation (high growth expectations).' : val < 15 ? 'At ' + val.toFixed(1) + ', that\'s relatively cheap.' : 'At ' + val.toFixed(1) + ', that\'s a moderate valuation.';
      case 'sharpe': return val > 1 ? 'At ' + val.toFixed(2) + ', returns have compensated well for risk.' : val < 0 ? 'Negative — risk wasn\'t rewarded over this window.' : 'At ' + val.toFixed(2) + ', risk-adjusted returns are modest.';
      default: return null;
    }
  }

  function renderTechnicals(ind, last) {
    var b = panel('sa-technicals-panel', 'Technical indicators');
    var rows = [
      ['RSI (14)', fmtRatio(last(ind.rsi), 1), 'rsi', interp('rsi', last(ind.rsi))],
      ['MACD histogram', fmtRatio(last(ind.macd.hist), 3), 'macd', last(ind.macd.hist) > 0 ? 'Positive — short-term momentum is upward.' : 'Negative — short-term momentum is downward.'],
      ['SMA 20 / 50 / 200', fmtRatio(last(ind.sma20)) + ' / ' + fmtRatio(last(ind.sma50)) + ' / ' + fmtRatio(last(ind.sma200)), 'sma', null],
      ['EMA 20', fmtRatio(last(ind.ema20)), 'ema', null],
      ['Bollinger (20,2)', fmtRatio(last(ind.bb.lower)) + ' – ' + fmtRatio(last(ind.bb.upper)), 'bollinger', null],
      ['ATR (14)', fmtRatio(last(ind.atr)), 'atr', 'Typical swing of about ' + fmtCur(last(ind.atr), dash.currency) + ' per bar.'],
      ['ADX', fmtRatio(last(ind.adxObj.adx)), 'adx', last(ind.adxObj.adx) > 25 ? 'Above 25 — a real trend is in place.' : 'Below 25 — trend is weak/choppy.'],
      ['Stochastic %K', fmtRatio(last(ind.stochObj.k), 1), 'stochastic', null],
      ['CCI (20)', fmtRatio(last(ind.cci), 1), 'cci', null],
      ['Williams %R', fmtRatio(last(ind.willr), 1), 'willr', null],
      ['Money Flow Index', fmtRatio(last(ind.mfi), 1), 'mfi', null],
      ['ROC (12)', fmtPct(last(ind.roc), 1), 'roc', null]
    ];
    rows.forEach(function (r) { b.appendChild(metricRow(r[0], r[1], r[2], r[3])); });
  }

  function renderStats(closes, price) {
    var b = panel('sa-stats-panel', 'Statistical & quantitative');
    var rets = A.returns(closes);
    var vol = A.std(rets) * Math.sqrt(252) * 100;
    var dd = A.maxDrawdown(closes);
    var cumRet = (closes[closes.length - 1] / closes[0] - 1) * 100;
    var annRet = (Math.pow(closes[closes.length - 1] / closes[0], 252 / closes.length) - 1) * 100;
    var sharpe = A.sharpe(rets, S.RISK_FREE);
    var sortino = A.sortino(rets, S.RISK_FREE);
    var reg = A.linReg(closes);
    b.appendChild(metricRow('Cumulative return (period)', fmtPct(cumRet), null));
    b.appendChild(metricRow('Annualized return', fmtPct(annRet), null));
    b.appendChild(metricRow('Volatility (annualized)', fmtPct(vol), 'volatility', 'Moves about ' + fmtNum(A.std(rets) * 100, 2) + '% on a typical day.'));
    b.appendChild(metricRow('Max drawdown', fmtPct(dd.max * 100), 'maxDrawdown', 'Worst drop from a peak this period.'));
    b.appendChild(metricRow('Current drawdown', fmtPct(dd.current * 100), null, 'How far below the recent peak it sits now.'));
    b.appendChild(metricRow('Sharpe ratio', fmtRatio(sharpe), 'sharpe', interp('sharpe', sharpe)));
    b.appendChild(metricRow('Sortino ratio', fmtRatio(sortino), 'sortino', null));
    b.appendChild(metricRow('Trend (linear regression)', reg.slope > 0 ? 'Up-sloping' : 'Down-sloping', null, 'The best-fit line over this window points ' + (reg.slope > 0 ? 'up' : 'down') + '.'));

    // Beta + correlation vs benchmark + Monte Carlo (async)
    Data.chart(S.BENCHMARK, dash.range === '1d' || dash.range === '5d' ? '1y' : dash.range, '1d').then(function (bd) {
      var bcl = bd.candles.map(function (c) { return c.c; });
      var beta = A.beta(rets, A.returns(bcl));
      var corr = A.correlation(rets, A.returns(bcl));
      b.appendChild(metricRow('Beta vs ' + S.BENCHMARK, fmtRatio(beta), 'beta', interp('beta', beta)));
      b.appendChild(metricRow('Correlation vs ' + S.BENCHMARK, fmtRatio(corr), 'correlation', null));
    }).catch(function () {});

    var mc = A.monteCarlo(price, rets, 60, 1000);
    var mcWrap = el('div', 'sa-mc');
    mcWrap.appendChild(metricRow('Monte Carlo (60 trading days, 1,000 paths)',
      fmtCur(mc.p5, dash.currency) + ' … ' + fmtCur(mc.p95, dash.currency), 'montecarlo',
      '90% of simulated paths land between ' + fmtCur(mc.p5, dash.currency) + ' and ' + fmtCur(mc.p95, dash.currency) + ' (median ' + fmtCur(mc.p50, dash.currency) + '). A statistical illustration, not a prediction.'));
    b.appendChild(mcWrap);
  }

  function renderRisk(closes, highs, lows, price, atr) {
    var b = panel('sa-risk-panel', 'Risk management & position sizing');
    var stop = price - 1.5 * atr, target = price + 3 * atr;
    var rr = (target - price) / (price - stop);
    var calc = el('div', 'sa-calc');
    calc.innerHTML =
      '<div class="sa-calc-row"><label>Account size ($)<input type="number" id="sa-acct" value="10000" min="0"></label>' +
      '<label>Risk per trade (%)<input type="number" id="sa-riskpct" value="1" min="0" max="100" step="0.1"></label></div>' +
      '<div class="sa-calc-out" id="sa-calc-out"></div>';
    b.appendChild(calc);
    function recalc() {
      var acct = parseFloat(document.getElementById('sa-acct').value) || 0;
      var rp = parseFloat(document.getElementById('sa-riskpct').value) || 0;
      var riskDollars = acct * rp / 100;
      var perShare = price - stop;
      var shares = perShare > 0 ? Math.floor(riskDollars / perShare) : 0;
      document.getElementById('sa-calc-out').innerHTML =
        '<div>Risking <strong>' + fmtCur(riskDollars, dash.currency) + '</strong> → buy about <strong>' + shares + ' shares</strong> (' + fmtCur(shares * price, dash.currency) + ' position).</div>' +
        '<div class="sa-muted">Sizing so a hit stop loses only your chosen risk amount.</div>';
    }
    calc.querySelector('#sa-acct').addEventListener('input', recalc);
    calc.querySelector('#sa-riskpct').addEventListener('input', recalc);
    recalc();
    b.appendChild(metricRow('ATR-based stop loss (1.5×ATR)', fmtCur(stop, dash.currency), 'positionSize', 'About ' + fmtPct(-(price - stop) / price * 100) + ' below current price.'));
    b.appendChild(metricRow('Take-profit (3×ATR)', fmtCur(target, dash.currency), null, 'About ' + fmtPct((target - price) / price * 100) + ' above current price.'));
    b.appendChild(metricRow('Risk / reward', fmtRatio(rr) + ' : 1', 'riskReward', rr >= 2 ? 'A 2:1+ setup — reward outweighs risk on these stops.' : 'Below 2:1 on these stops.'));
    var dret = A.returns(closes);
    b.appendChild(metricRow('Average daily move', fmtPct(A.mean(dret.map(Math.abs)) * 100), null, 'On an average day this stock moves about this much in either direction.'));
  }

  function renderPatterns() {
    var b = panel('sa-patterns-panel', 'Candlestick & structure patterns');
    var pats = A.detectPatterns(dash.candles);
    if (!pats.length) { b.appendChild(el('p', 'sa-muted', 'No classic candlestick pattern on the latest bar. (Patterns are best-effort; absence isn\'t a signal.)')); }
    else {
      pats.forEach(function (p) {
        b.appendChild(el('div', 'sa-pattern ' + p.dir,
          '<strong>' + esc(p.name) + '</strong> <span class="sa-tag ' + p.dir + '">' + p.dir + '</span>'));
      });
    }
    // structure: trend state via higher highs/lows + golden/death cross
    var closes = dash.candles.map(function (c) { return c.c; });
    var s50 = A.sma(closes, 50), s200 = A.sma(closes, 200);
    var L = function (a) { return a[a.length - 1]; };
    if (L(s50) != null && L(s200) != null) {
      var golden = L(s50) > L(s200);
      b.appendChild(el('div', 'sa-pattern ' + (golden ? 'bullish' : 'bearish'),
        '<strong>' + (golden ? 'Golden-cross regime' : 'Death-cross regime') + '</strong> — 50-day MA is ' + (golden ? 'above' : 'below') + ' the 200-day.'));
    }
    var recent = closes.slice(-20), older = closes.slice(-40, -20);
    if (older.length) {
      var trendUp = A.mean(recent) > A.mean(older);
      b.appendChild(el('div', 'sa-pattern ' + (trendUp ? 'bullish' : 'bearish'),
        '<strong>' + (trendUp ? 'Higher recent average' : 'Lower recent average') + '</strong> — last 20 bars vs the prior 20.'));
    }
  }

  function renderBacktest(closes) {
    var b = panel('sa-backtest-panel', 'Backtest (hypothetical)');
    var sel = el('div', 'sa-bt-controls');
    sel.innerHTML = '<button class="sa-chip-toggle active" data-st="rsi">RSI 30/70</button>' +
      '<button class="sa-chip-toggle" data-st="ma">50/200 MA cross</button>';
    b.appendChild(sel);
    var out = el('div', 'sa-bt-out');
    b.appendChild(out);
    function run(strategy) {
      var r = A.backtest(closes, strategy);
      out.innerHTML =
        '<div class="sa-bt-grid">' +
        '<div><span>' + r.trades + '</span>trades</div>' +
        '<div><span>' + (r.winRate * 100).toFixed(0) + '%</span>win rate</div>' +
        '<div class="' + (r.totalReturn >= 0 ? 'up' : 'down') + '"><span>' + fmtPct(r.totalReturn * 100) + '</span>strategy</div>' +
        '<div class="' + (r.buyHold >= 0 ? 'up' : 'down') + '"><span>' + fmtPct(r.buyHold * 100) + '</span>buy &amp; hold</div>' +
        '</div><p class="sa-mini-note">Hypothetical, no fees/slippage, over the loaded timeframe. Past results don\'t predict the future.</p>';
    }
    sel.querySelectorAll('.sa-chip-toggle').forEach(function (btn) {
      btn.addEventListener('click', function () {
        sel.querySelectorAll('.sa-chip-toggle').forEach(function (x) { x.classList.remove('active'); });
        btn.classList.add('active');
        run(btn.dataset.st === 'rsi' ? 'rsi' : 'ma');
      });
    });
    run('rsi');
  }

  function renderNarrative(ind, sig, closes, price, last) {
    var p = document.getElementById('sa-narrative-panel');
    p.innerHTML = '';
    p.appendChild(el('div', 'sa-panel-head', '<h4>In plain English</h4>'));
    var rsi = last(ind.rsi), adx = last(ind.adxObj.adx);
    var vol = A.std(A.returns(closes)) * Math.sqrt(252) * 100;
    var trend = last(ind.sma50) != null && price > last(ind.sma50) ? 'above its 50-day average (a near-term uptrend)' : 'below its 50-day average (near-term weakness)';
    var mom = rsi > 70 ? 'momentum is hot — RSI is in overbought territory' : rsi < 30 ? 'momentum is washed out — RSI is oversold' : 'momentum is in a normal range';
    var trendStr = adx > 25 ? 'and the trend has real strength behind it (ADX above 25)' : 'though the trend is currently weak or choppy (ADX below 25)';
    var txt = '<strong>' + esc(dash.symbol) + '</strong> is trading ' + trend + ', ' + trendStr + '. Right now ' + mom +
      '. Annualized volatility is around ' + vol.toFixed(0) + '%, so expect ' + (vol > 40 ? 'large' : vol > 25 ? 'moderate' : 'relatively contained') + ' swings. ' +
      'Across the indicators, the overall read is <strong>' + esc(sig.label.toLowerCase()) + '</strong> (' + sig.bull + ' bullish vs ' + sig.bear + ' bearish signals). ' +
      'Watch the moving averages and the auto support/resistance levels on the chart — a clean break through them is often what shifts the picture.';
    p.appendChild(el('p', 'sa-narrative', txt));
    p.appendChild(el('p', 'sa-mini-note', 'This summary is generated from the numbers above. It describes what the data shows — it is not advice or a forecast.'));
  }

  /* ── Fundamentals ── */
  function loadFundamentals() {
    var b = panel('sa-fundamentals-panel', 'Fundamentals');
    b.innerHTML = '<p class="sa-muted">Loading fundamentals…</p>';
    Data.fundamentals(dash.symbol).then(function (f) {
      b.innerHTML = '';
      if (f.sector) b.appendChild(el('div', 'sa-fund-sector', esc(f.sector) + (f.industry ? ' · ' + esc(f.industry) : '')));
      var rows = [
        ['Market cap', fmtBig(f.marketCap), 'marketCap', null],
        ['P/E (trailing)', fmtRatio(f.peTrailing), 'peTrailing', interp('pe', f.peTrailing)],
        ['Forward P/E', fmtRatio(f.peForward), 'peForward', null],
        ['PEG ratio', fmtRatio(f.peg), 'peg', f.peg != null ? (f.peg < 1 ? 'Below 1 — cheap relative to its growth.' : f.peg > 2 ? 'Above 2 — pricey relative to growth.' : 'Around fair vs growth.') : null],
        ['Price / book', fmtRatio(f.priceToBook), 'priceToBook', null],
        ['Price / sales', fmtRatio(f.priceToSales), 'priceToSales', null],
        ['EPS (trailing)', fmtCur(f.epsTrailing, f.currency), 'eps', null],
        ['Revenue growth', f.revenueGrowth != null ? fmtPct(f.revenueGrowth * 100) : '—', 'revenueGrowth', null],
        ['Earnings growth', f.earningsGrowth != null ? fmtPct(f.earningsGrowth * 100) : '—', 'earningsGrowth', null],
        ['Profit margin', f.profitMargin != null ? fmtPct(f.profitMargin * 100) : '—', 'profitMargin', f.profitMargin != null ? (f.profitMargin > 0.2 ? 'Strong — keeps over 20¢ of every sales dollar.' : f.profitMargin < 0 ? 'Negative — unprofitable.' : 'Modest margin.') : null],
        ['Return on equity', f.roe != null ? fmtPct(f.roe * 100) : '—', 'roe', null],
        ['Return on assets', f.roa != null ? fmtPct(f.roa * 100) : '—', 'roa', null],
        ['Debt / equity', fmtRatio(f.debtToEquity), 'debtToEquity', f.debtToEquity != null ? (f.debtToEquity > 200 ? 'High leverage — carries a lot of debt.' : 'Manageable leverage.') : null],
        ['Current ratio', fmtRatio(f.currentRatio), 'currentRatio', f.currentRatio != null ? (f.currentRatio >= 1 ? 'Above 1 — can cover short-term bills.' : 'Below 1 — tight on short-term liquidity.') : null],
        ['Free cash flow', fmtBig(f.freeCashflow), 'freeCashflow', null],
        ['Dividend yield', f.dividendYield != null ? fmtPct(f.dividendYield * 100) : 'None', 'dividendYield', null],
        ['Beta', fmtRatio(f.beta), 'beta', interp('beta', f.beta)],
        ['52-week range', fmtCur(f.week52Low, f.currency) + ' – ' + fmtCur(f.week52High, f.currency), 'week52', null]
      ];
      rows.forEach(function (r) { b.appendChild(metricRow(r[0], r[1], r[2], r[3])); });
      if (f.nextEarnings) {
        var dt = new Date(f.nextEarnings * 1000).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
        b.appendChild(metricRow('Next earnings', dt, null, 'Earnings days often bring big moves.'));
      }
      if (f.summary) {
        var more = el('details', 'sa-bizsummary');
        more.innerHTML = '<summary>Company profile</summary><p>' + esc(f.summary) + '</p>';
        b.appendChild(more);
      }
    }).catch(function (e) {
      b.innerHTML = '<p class="sa-muted">Fundamentals unavailable for this symbol (' + esc(e.message || '') + '). This is common for ETFs and some tickers.</p>';
    });
  }

  /* ── News + a plain-English read of the likely effect ── */
  var NEWS_POS = ['beat', 'beats', 'tops', 'surge', 'soar', 'jump', 'rally', 'rallies', 'upgrade', 'raises', 'raised', 'record', 'all-time high', 'strong', 'growth', 'outperform', 'buy rating', 'wins', 'awarded', 'approval', 'approved', 'partnership', 'expansion', 'profit', 'gains', 'rises', 'boom', 'bullish', 'breakthrough', 'buyback', 'dividend', 'better than', 'better-than'];
  var NEWS_NEG = ['miss', 'misses', 'missed', 'plunge', 'drop', 'falls', 'slump', 'sinks', 'downgrade', 'cuts', 'cut', 'lawsuit', 'sued', 'probe', 'investigation', 'recall', 'warns', 'warning', 'weak', 'decline', 'loss', 'losses', 'layoff', 'bankruptcy', 'fraud', 'slowdown', 'bearish', 'underperform', 'sell rating', 'halts', 'delay', 'delayed', 'concerns', 'fears', 'slips', 'tumble', 'crash', 'worse than', 'worse-than', 'subpoena', 'antitrust'];
  function newsDir(title) {
    var t = ' ' + String(title || '').toLowerCase() + ' ', s = 0;
    NEWS_POS.forEach(function (w) { if (t.indexOf(w) !== -1) s++; });
    NEWS_NEG.forEach(function (w) { if (t.indexOf(w) !== -1) s--; });
    return s > 0 ? 1 : (s < 0 ? -1 : 0);
  }
  function newsDirTag(dir) {
    if (dir > 0) return '<span class="sa-news-dir up" title="Headline reads positive">📈 may lift</span>';
    if (dir < 0) return '<span class="sa-news-dir down" title="Headline reads negative">📉 may weigh</span>';
    return '<span class="sa-news-dir flat" title="Neutral / unclear">➖ neutral</span>';
  }
  function newsRead(items) {
    var s = 0; items.forEach(function (n) { s += newsDir(n.title); });
    if (s > 0) return { cls: 'up', text: 'Headlines skew positive (upgrades / beats / strong demand) — news like this tends to pull a stock up, but markets often price good news in fast, so a pop can fade if it was expected.' };
    if (s < 0) return { cls: 'down', text: 'Headlines skew negative (downgrades / misses / legal or demand worries) — news like this tends to pressure a stock down, though if it was already feared the drop may be limited or reverse.' };
    return { cls: 'flat', text: 'Headlines look mixed or neutral — no clear directional tilt; moves are more likely to track the overall market than these stories.' };
  }
  function loadNews() {
    var b = panel('sa-news-panel', 'Recent news → likely effect');
    b.innerHTML = '<p class="sa-muted">Loading headlines…</p>';
    Data.news(dash.symbol).then(function (d) {
      b.innerHTML = '';
      if (!d.news || !d.news.length) { b.appendChild(el('p', 'sa-muted', 'No recent headlines found.')); return; }
      var read = newsRead(d.news);
      b.appendChild(el('p', 'sa-news-read ' + read.cls, '<b>News read:</b> ' + esc(read.text)));
      d.news.forEach(function (n) {
        var item = el('a', 'sa-news-item');
        item.href = n.link; item.target = '_blank'; item.rel = 'noopener';
        item.innerHTML = '<div class="sa-news-title">' + newsDirTag(newsDir(n.title)) + ' ' + esc(n.title) + '</div>' +
          '<div class="sa-news-meta">' + esc(n.publisher) + ' · ' + ago(n.time) + '</div>';
        b.appendChild(item);
      });
      b.appendChild(el('p', 'sa-mini-note', 'Automated keyword read of the headlines — an interpretation, not a prediction.'));
    }).catch(function () {
      b.innerHTML = '<p class="sa-muted">Couldn\'t load news right now.</p>';
    });
  }

  /* ── AI analysis (optional, reuses chat.php key via stocks? no — call chat.php) ── */
  function renderAIPanel(ind, sig, price) {
    var p = document.getElementById('sa-ai-panel');
    p.innerHTML = '';
    p.appendChild(el('div', 'sa-panel-head', '<h4>AI-written analysis <span class="sa-beta">optional</span></h4>'));
    var body = el('div', 'sa-panel-body');
    var btn = el('button', 'btn btn-ghost btn-small', '✨ Generate AI analysis');
    var out = el('div', 'sa-ai-out');
    body.appendChild(btn); body.appendChild(out);
    body.appendChild(el('p', 'sa-mini-note', 'Sends the computed metrics to Claude for a plain-English write-up. Educational only. Requires the site\'s AI key to be configured; otherwise this button will say so.'));
    p.appendChild(body);
    btn.addEventListener('click', function () {
      btn.disabled = true; btn.textContent = 'Thinking…'; out.textContent = '';
      var last = function (a) { return a[a.length - 1]; };
      var summary = 'Stock ' + dash.symbol + ' at ' + fmtCur(price, dash.currency) +
        '. RSI ' + fmtRatio(last(ind.rsi), 0) + ', ADX ' + fmtRatio(last(ind.adxObj.adx), 0) +
        ', MACD hist ' + fmtRatio(last(ind.macd.hist), 3) + ', price vs SMA50 ' + (price > last(ind.sma50) ? 'above' : 'below') +
        ', vs SMA200 ' + (price > last(ind.sma200) ? 'above' : 'below') +
        '. Aggregate signal: ' + sig.label + ' (' + sig.bull + ' bullish / ' + sig.bear + ' bearish).';
      var prompt = 'You are a financial educator. In 2 short paragraphs, plain English, explain what this technical setup is showing a beginner and what to watch. Do NOT give buy/sell advice; frame as education. Data: ' + summary;
      fetch('chat.php', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: [{ role: 'user', content: prompt }] })
      }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (res.ok && res.d.reply) out.textContent = res.d.reply;
          else out.innerHTML = '<span class="sa-muted">AI analysis isn\'t available right now (' + esc(res.d.error || 'the site AI key may not be set') + ').</span>';
        }).catch(function () { out.innerHTML = '<span class="sa-muted">Couldn\'t reach the AI service.</span>'; })
        .finally(function () { btn.disabled = false; btn.textContent = '✨ Generate AI analysis'; });
    });
  }

  /* ── Alerts (price / RSI) ── */
  function getAlerts() { try { return JSON.parse(localStorage.getItem(S.ALERT_KEY)) || []; } catch (e) { return []; } }
  function setAlerts(a) { try { localStorage.setItem(S.ALERT_KEY, JSON.stringify(a)); } catch (e) {} }
  function renderAlertsPanel() {
    var b = panel('sa-alerts-panel', 'Alerts');
    var form = el('div', 'sa-alert-form');
    form.innerHTML =
      '<select id="sa-alert-type"><option value="price_above">Price above</option>' +
      '<option value="price_below">Price below</option><option value="rsi_above">RSI above</option>' +
      '<option value="rsi_below">RSI below</option></select>' +
      '<input type="number" id="sa-alert-val" placeholder="value" step="0.01">' +
      '<button class="btn btn-primary btn-small" id="sa-alert-add">Set alert</button>';
    b.appendChild(form);
    var listWrap = el('div', 'sa-alert-list');
    b.appendChild(listWrap);
    b.appendChild(el('p', 'sa-mini-note', 'Alerts check when you refresh the watchlist or revisit. In-browser only.'));
    function draw() {
      listWrap.innerHTML = '';
      var mine = getAlerts().filter(function (a) { return a.symbol === dash.symbol; });
      if (!mine.length) { listWrap.appendChild(el('p', 'sa-muted', 'No alerts set for ' + esc(dash.symbol) + '.')); return; }
      getAlerts().forEach(function (a, i) {
        if (a.symbol !== dash.symbol) return;
        var row = el('div', 'sa-alert-item', '<span>' + esc(a.type.replace('_', ' ')) + ' ' + a.value + (a.triggered ? ' ✓ triggered' : '') + '</span>');
        var x = el('button', 'sa-wl-remove', '✕');
        x.addEventListener('click', function () { var all = getAlerts(); all.splice(i, 1); setAlerts(all); draw(); });
        row.appendChild(x); listWrap.appendChild(row);
      });
    }
    form.querySelector('#sa-alert-add').addEventListener('click', function () {
      var type = document.getElementById('sa-alert-type').value;
      var val = parseFloat(document.getElementById('sa-alert-val').value);
      if (isNaN(val)) return;
      var all = getAlerts(); all.push({ symbol: dash.symbol, type: type, value: val, triggered: false });
      setAlerts(all); document.getElementById('sa-alert-val').value = ''; draw();
    });
    draw();
  }
  function checkAlerts(quotes) {
    var all = getAlerts(); var changed = false; var fired = [];
    all.forEach(function (a) {
      if (a.triggered) return;
      var q = quotes[a.symbol]; if (!q || !q.ok) return;
      var hit = (a.type === 'price_above' && q.price > a.value) || (a.type === 'price_below' && q.price < a.value);
      if (hit) { a.triggered = true; changed = true; fired.push(a.symbol + ' ' + a.type.replace('_', ' ') + ' ' + a.value); }
    });
    if (changed) { setAlerts(all); if (fired.length) setTimeout(function () { alert('📈 Alert: ' + fired.join('; ')); }, 100); }
  }

  /* ═══ COMPARISON VIEW ══════════════════════════════════════════════════ */
  function renderCompare() {
    showView('sa-compare-view');
    window.scrollTo({ top: 0, behavior: 'instant' });
    var list = S.getWatchlist();
    var table = document.getElementById('sa-compare-table');
    table.innerHTML = '<tr><th>Symbol</th><th>Price</th><th>Chg %</th><th>P/E</th><th>Mkt cap</th><th>Beta</th><th>Div %</th></tr>';
    var legend = document.getElementById('sa-compare-legend');
    legend.innerHTML = '';
    var palette = ['#26a269', '#b85c38', '#3b82f6', '#a855f7', '#0ea5e9', '#eab308', '#ec4899', '#14b8a6'];

    Data.quotes(list).then(function (res) {
      var q = res.quotes || {};
      list.forEach(function (sym) {
        var d = q[sym] || {};
        var tr = el('tr');
        tr.innerHTML = '<td class="sa-cmp-sym">' + esc(sym) + '</td><td>' + fmtCur(d.price, d.currency) + '</td>' +
          '<td class="' + ((d.changePct || 0) >= 0 ? 'up' : 'down') + '">' + fmtPct(d.changePct) + '</td>' +
          '<td data-f="pe">…</td><td data-f="mc">…</td><td data-f="beta">…</td><td data-f="div">…</td>';
        tr.dataset.symbol = sym;
        table.appendChild(tr);
      });
      list.forEach(function (sym) {
        Data.fundamentals(sym).then(function (f) {
          var tr = table.querySelector('tr[data-symbol="' + sym + '"]'); if (!tr) return;
          tr.querySelector('[data-f="pe"]').textContent = fmtRatio(f.peTrailing);
          tr.querySelector('[data-f="mc"]').textContent = fmtBig(f.marketCap);
          tr.querySelector('[data-f="beta"]').textContent = fmtRatio(f.beta);
          tr.querySelector('[data-f="div"]').textContent = f.dividendYield != null ? fmtPct(f.dividendYield * 100) : '—';
        }).catch(function () {});
      });
    });

    // Normalized performance chart (rebased to 100)
    if (window.LightweightCharts) {
      var container = document.getElementById('sa-compare-chart');
      container.innerHTML = '';
      var c = colors();
      var chart = LightweightCharts.createChart(container, {
        autoSize: true, height: 320,
        layout: { background: { type: 'solid', color: 'transparent' }, textColor: c.text, fontFamily: 'Inter, sans-serif' },
        grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
        rightPriceScale: { borderColor: c.border }, timeScale: { borderColor: c.border }
      });
      list.forEach(function (sym, i) {
        Data.chart(sym, '1y', '1d').then(function (d) {
          if (!d.candles || !d.candles.length) return;
          var base = d.candles[0].c;
          var s = chart.addLineSeries({ color: palette[i % palette.length], lineWidth: 2, priceLineVisible: false, lastValueVisible: true });
          s.setData(d.candles.map(function (k) { return { time: k.t, value: k.c / base * 100 }; }));
          legend.appendChild(el('span', 'sa-legend-item', '<span class="sa-legend-dot" style="background:' + palette[i % palette.length] + '"></span>' + esc(sym)));
          chart.timeScale().fitContent();
        }).catch(function () {});
      });
    }
  }

  /* ═══ BOOT + theme re-render ═══════════════════════════════════════════ */
  function wire() {
    document.getElementById('sa-add-form').addEventListener('submit', function (e) {
      e.preventDefault();
      var input = document.getElementById('sa-add-input');
      var sym = (input.value || '').trim().toUpperCase();
      if (!/^[A-Z0-9.\-\^=]{1,15}$/.test(sym)) { input.value = ''; return; }
      var wl = S.getWatchlist();
      if (wl.indexOf(sym) === -1) { wl.push(sym); S.setWatchlist(wl); }
      input.value = '';
      renderWatchlist();
    });
    document.getElementById('sa-refresh').addEventListener('click', renderWatchlist);
    document.getElementById('sa-compare-btn').addEventListener('click', renderCompare);
    document.getElementById('sa-compare-back').addEventListener('click', function () { showView('sa-watchlist-view'); });
    document.getElementById('sa-dash-back').addEventListener('click', function () { disposeChart(); showView('sa-watchlist-view'); renderWatchlist(); });

    // Re-theme charts when the site theme toggles
    var tt = document.getElementById('theme-toggle');
    if (tt) tt.addEventListener('click', function () {
      setTimeout(function () {
        if (!document.getElementById('sa-dash-view').classList.contains('hidden') && dash.candles.length) {
          buildChart(); rebuildOverlays(); buildSubChart();
        }
        if (!document.getElementById('sa-compare-view').classList.contains('hidden')) renderCompare();
      }, 60);
    });
  }

  function loadWatchlistOnce() {
    if (watchlistLoaded) return;
    watchlistLoaded = true;
    renderWatchlist();
  }

  // Boot when the Stocks section becomes active (lazy — saves API calls)
  function observeActivation() {
    var obs = new MutationObserver(function () {
      if (rootSection.classList.contains('active')) loadWatchlistOnce();
    });
    obs.observe(rootSection, { attributes: true, attributeFilter: ['class'] });
    if (rootSection.classList.contains('active')) loadWatchlistOnce();
  }

  window.AndyStocksUI = {
    boot: function () {
      if (booted) return; booted = true;
      S = window.AndyStocks; A = S.A; Data = S.Data; EXPLAIN = S.EXPLAIN;
      wire();
      observeActivation();
    }
  };
  // If stocks.js already ran, boot now; else it will call us.
  if (window.AndyStocks) window.AndyStocksUI.boot();
})();
