/* ═══════════════════════════════════════════════════════════════════════
   AndyStockAnalysis — markets dashboard
   Educational only. Not financial advice.

   Layout of this file:
     1. CONFIG          — watchlist + benchmark (easy to edit)
     2. DATA LAYER      — fetch via stocks.php, in-memory cache (swappable)
     3. ANALYSIS ENGINE — pure indicator/stat/pattern/signal functions
     4. EXPLANATIONS    — plain-English meaning for every metric
     5. UI              — watchlist, dashboard, charts, panels, compare
═══════════════════════════════════════════════════════════════════════ */
(function initStocks() {
  'use strict';
  var root = document.getElementById('stocks');
  if (!root) return; // not on this page

  /* ═══ 1. CONFIG ═══════════════════════════════════════════════════════ */
  var DEFAULT_WATCHLIST = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'TSLA', 'SPY'];
  var BENCHMARK = 'SPY';           // used for beta / correlation
  var RISK_FREE = 0.043;           // annual risk-free rate for Sharpe (~T-bill)
  var WL_KEY = 'asd-stocks-watchlist';
  var ALERT_KEY = 'asd-stocks-alerts';

  function getWatchlist() {
    try {
      var s = JSON.parse(localStorage.getItem(WL_KEY));
      if (Array.isArray(s) && s.length) return s;
    } catch (e) {}
    return DEFAULT_WATCHLIST.slice();
  }
  function setWatchlist(list) {
    try { localStorage.setItem(WL_KEY, JSON.stringify(list)); } catch (e) {}
  }

  /* ═══ 2. DATA LAYER (abstracted — swap stocks.php for any provider) ═══ */
  var cache = {};
  function cached(key, ttlMs, fetcher) {
    var now = Date.now();
    if (cache[key] && now - cache[key].t < ttlMs) return Promise.resolve(cache[key].v);
    return fetcher().then(function (v) { cache[key] = { t: now, v: v }; return v; });
  }
  function api(params) {
    var qs = Object.keys(params).map(function (k) {
      return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]);
    }).join('&');
    return fetch('stocks.php?' + qs).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d && d.error ? d.error : 'Request failed');
        return d;
      });
    });
  }
  var Data = {
    quotes: function (symbols) {
      return cached('q:' + symbols.join(','), 45000, function () {
        return api({ action: 'quotes', symbols: symbols.join(',') });
      });
    },
    chart: function (symbol, range, interval) {
      return cached('c:' + symbol + range + interval, 90000, function () {
        return api({ action: 'chart', symbol: symbol, range: range, interval: interval });
      });
    },
    fundamentals: function (symbol) {
      return cached('f:' + symbol, 3600000, function () {
        return api({ action: 'fundamentals', symbol: symbol });
      });
    },
    news: function (symbol) {
      return cached('n:' + symbol, 600000, function () {
        return api({ action: 'news', symbol: symbol });
      });
    }
  };

  /* ═══ 3. ANALYSIS ENGINE (pure functions) ═══════════════════════════════ */
  var A = {};
  A.sma = function (v, p) {
    var out = []; var sum = 0;
    for (var i = 0; i < v.length; i++) {
      sum += v[i];
      if (i >= p) sum -= v[i - p];
      out.push(i >= p - 1 ? sum / p : null);
    }
    return out;
  };
  A.ema = function (v, p) {
    var out = []; var k = 2 / (p + 1); var prev = null;
    for (var i = 0; i < v.length; i++) {
      if (v[i] == null) { out.push(null); continue; }
      if (prev == null) { prev = v[i]; out.push(i >= p - 1 ? prev : null); }
      else { prev = v[i] * k + prev * (1 - k); out.push(prev); }
    }
    return out;
  };
  A.wma = function (v, p) {
    var out = []; var denom = p * (p + 1) / 2;
    for (var i = 0; i < v.length; i++) {
      if (i < p - 1) { out.push(null); continue; }
      var s = 0;
      for (var j = 0; j < p; j++) s += v[i - j] * (p - j);
      out.push(s / denom);
    }
    return out;
  };
  A.stddev = function (v, p) {
    var out = [];
    for (var i = 0; i < v.length; i++) {
      if (i < p - 1) { out.push(null); continue; }
      var m = 0, j;
      for (j = 0; j < p; j++) m += v[i - j];
      m /= p;
      var s = 0;
      for (j = 0; j < p; j++) s += Math.pow(v[i - j] - m, 2);
      out.push(Math.sqrt(s / p));
    }
    return out;
  };
  A.rsi = function (closes, p) {
    p = p || 14;
    var out = [null]; var gain = 0, loss = 0, i;
    for (i = 1; i <= p; i++) {
      var ch = closes[i] - closes[i - 1];
      if (ch >= 0) gain += ch; else loss -= ch;
      out.push(null);
    }
    var ag = gain / p, al = loss / p;
    out[p] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
    for (i = p + 1; i < closes.length; i++) {
      var c = closes[i] - closes[i - 1];
      var g = c > 0 ? c : 0, l = c < 0 ? -c : 0;
      ag = (ag * (p - 1) + g) / p;
      al = (al * (p - 1) + l) / p;
      out.push(al === 0 ? 100 : 100 - 100 / (1 + ag / al));
    }
    return out;
  };
  A.macd = function (closes, fast, slow, sig) {
    fast = fast || 12; slow = slow || 26; sig = sig || 9;
    var ef = A.ema(closes, fast), es = A.ema(closes, slow);
    var line = closes.map(function (_, i) {
      return (ef[i] != null && es[i] != null) ? ef[i] - es[i] : null;
    });
    var valid = line.filter(function (x) { return x != null; });
    var sigValid = A.ema(valid, sig);
    var signal = []; var k = 0;
    for (var i = 0; i < line.length; i++) {
      if (line[i] == null) signal.push(null);
      else { signal.push(sigValid[k]); k++; }
    }
    var hist = line.map(function (x, i) {
      return (x != null && signal[i] != null) ? x - signal[i] : null;
    });
    return { macd: line, signal: signal, hist: hist };
  };
  A.bollinger = function (closes, p, mult) {
    p = p || 20; mult = mult || 2;
    var mid = A.sma(closes, p), sd = A.stddev(closes, p);
    return {
      middle: mid,
      upper: mid.map(function (m, i) { return m != null ? m + mult * sd[i] : null; }),
      lower: mid.map(function (m, i) { return m != null ? m - mult * sd[i] : null; })
    };
  };
  A.trueRange = function (h, l, c) {
    var tr = [h[0] - l[0]];
    for (var i = 1; i < c.length; i++) {
      tr.push(Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1])));
    }
    return tr;
  };
  A.atr = function (h, l, c, p) {
    p = p || 14;
    var tr = A.trueRange(h, l, c);
    return A.ema(tr, p); // Wilder-ish smoothing via EMA approximation
  };
  A.adx = function (h, l, c, p) {
    p = p || 14;
    var plusDM = [0], minusDM = [0], tr = A.trueRange(h, l, c);
    for (var i = 1; i < c.length; i++) {
      var up = h[i] - h[i - 1], dn = l[i - 1] - l[i];
      plusDM.push(up > dn && up > 0 ? up : 0);
      minusDM.push(dn > up && dn > 0 ? dn : 0);
    }
    function wilder(arr) {
      var o = []; var sum = 0, i;
      for (i = 0; i < arr.length; i++) {
        if (i < p) { sum += arr[i]; o.push(i === p - 1 ? sum : null); }
        else { sum = o[i - 1] - o[i - 1] / p + arr[i]; o.push(sum); }
      }
      return o;
    }
    var trS = wilder(tr), pS = wilder(plusDM), mS = wilder(minusDM);
    var plusDI = [], minusDI = [], dx = [];
    for (var j = 0; j < c.length; j++) {
      if (trS[j] == null || trS[j] === 0) { plusDI.push(null); minusDI.push(null); dx.push(null); continue; }
      var pdi = 100 * pS[j] / trS[j], mdi = 100 * mS[j] / trS[j];
      plusDI.push(pdi); minusDI.push(mdi);
      dx.push((pdi + mdi) === 0 ? 0 : 100 * Math.abs(pdi - mdi) / (pdi + mdi));
    }
    var adx = A.ema(dx.map(function (x) { return x == null ? 0 : x; }), p);
    return { adx: adx, plusDI: plusDI, minusDI: minusDI };
  };
  A.stochastic = function (h, l, c, p, sp) {
    p = p || 14; sp = sp || 3;
    var k = [];
    for (var i = 0; i < c.length; i++) {
      if (i < p - 1) { k.push(null); continue; }
      var hh = -Infinity, ll = Infinity;
      for (var j = 0; j < p; j++) { hh = Math.max(hh, h[i - j]); ll = Math.min(ll, l[i - j]); }
      k.push(hh === ll ? 50 : 100 * (c[i] - ll) / (hh - ll));
    }
    var kv = k.filter(function (x) { return x != null; });
    var dv = A.sma(kv, sp); var idx = 0;
    var d = k.map(function (x) { return x == null ? null : dv[idx++]; });
    return { k: k, d: d };
  };
  A.stochRSI = function (closes, p) {
    p = p || 14;
    var r = A.rsi(closes, p);
    var out = [];
    for (var i = 0; i < r.length; i++) {
      if (i < 2 * p || r[i] == null) { out.push(null); continue; }
      var hh = -Infinity, ll = Infinity;
      for (var j = 0; j < p; j++) { if (r[i - j] != null) { hh = Math.max(hh, r[i - j]); ll = Math.min(ll, r[i - j]); } }
      out.push(hh === ll ? 0 : 100 * (r[i] - ll) / (hh - ll));
    }
    return out;
  };
  A.cci = function (h, l, c, p) {
    p = p || 20;
    var tp = c.map(function (_, i) { return (h[i] + l[i] + c[i]) / 3; });
    var ma = A.sma(tp, p), out = [];
    for (var i = 0; i < tp.length; i++) {
      if (ma[i] == null) { out.push(null); continue; }
      var md = 0;
      for (var j = 0; j < p; j++) md += Math.abs(tp[i - j] - ma[i]);
      md /= p;
      out.push(md === 0 ? 0 : (tp[i] - ma[i]) / (0.015 * md));
    }
    return out;
  };
  A.williamsR = function (h, l, c, p) {
    p = p || 14; var out = [];
    for (var i = 0; i < c.length; i++) {
      if (i < p - 1) { out.push(null); continue; }
      var hh = -Infinity, ll = Infinity;
      for (var j = 0; j < p; j++) { hh = Math.max(hh, h[i - j]); ll = Math.min(ll, l[i - j]); }
      out.push(hh === ll ? -50 : -100 * (hh - c[i]) / (hh - ll));
    }
    return out;
  };
  A.roc = function (closes, p) {
    p = p || 12;
    return closes.map(function (c, i) { return i >= p ? 100 * (c - closes[i - p]) / closes[i - p] : null; });
  };
  A.obv = function (closes, vol) {
    var out = [0];
    for (var i = 1; i < closes.length; i++) {
      out.push(out[i - 1] + (closes[i] > closes[i - 1] ? vol[i] : closes[i] < closes[i - 1] ? -vol[i] : 0));
    }
    return out;
  };
  A.vwap = function (h, l, c, vol) {
    var cumPV = 0, cumV = 0, out = [];
    for (var i = 0; i < c.length; i++) {
      var tp = (h[i] + l[i] + c[i]) / 3;
      cumPV += tp * vol[i]; cumV += vol[i];
      out.push(cumV ? cumPV / cumV : null);
    }
    return out;
  };
  A.mfi = function (h, l, c, vol, p) {
    p = p || 14;
    var tp = c.map(function (_, i) { return (h[i] + l[i] + c[i]) / 3; });
    var out = [null];
    for (var i = 1; i < c.length; i++) {
      if (i < p) { out.push(null); continue; }
      var pos = 0, neg = 0;
      for (var j = 0; j < p; j++) {
        var idx = i - j;
        var flow = tp[idx] * vol[idx];
        if (tp[idx] > tp[idx - 1]) pos += flow; else if (tp[idx] < tp[idx - 1]) neg += flow;
      }
      out.push(neg === 0 ? 100 : 100 - 100 / (1 + pos / neg));
    }
    return out;
  };
  A.adLine = function (h, l, c, vol) {
    var out = [], prev = 0;
    for (var i = 0; i < c.length; i++) {
      var mfm = (h[i] === l[i]) ? 0 : ((c[i] - l[i]) - (h[i] - c[i])) / (h[i] - l[i]);
      prev += mfm * vol[i];
      out.push(prev);
    }
    return out;
  };
  A.keltner = function (h, l, c, p, mult) {
    p = p || 20; mult = mult || 2;
    var mid = A.ema(c, p), atr = A.atr(h, l, c, p);
    return {
      middle: mid,
      upper: mid.map(function (m, i) { return m != null && atr[i] != null ? m + mult * atr[i] : null; }),
      lower: mid.map(function (m, i) { return m != null && atr[i] != null ? m - mult * atr[i] : null; })
    };
  };
  A.parabolicSAR = function (h, l, step, max) {
    step = step || 0.02; max = max || 0.2;
    var sar = [], ep, af = step, up = true;
    sar[0] = l[0]; ep = h[0];
    for (var i = 1; i < h.length; i++) {
      var prev = sar[i - 1];
      var cur = prev + af * (ep - prev);
      if (up) {
        if (l[i] < cur) { up = false; cur = ep; ep = l[i]; af = step; }
        else { if (h[i] > ep) { ep = h[i]; af = Math.min(af + step, max); } }
      } else {
        if (h[i] > cur) { up = true; cur = ep; ep = h[i]; af = step; }
        else { if (l[i] < ep) { ep = l[i]; af = Math.min(af + step, max); } }
      }
      sar[i] = cur;
    }
    return sar;
  };
  A.ichimoku = function (h, l, c) {
    function midOf(per) {
      return c.map(function (_, i) {
        if (i < per - 1) return null;
        var hh = -Infinity, ll = Infinity;
        for (var j = 0; j < per; j++) { hh = Math.max(hh, h[i - j]); ll = Math.min(ll, l[i - j]); }
        return (hh + ll) / 2;
      });
    }
    var tenkan = midOf(9), kijun = midOf(26), b = midOf(52);
    var spanA = c.map(function (_, i) { return (tenkan[i] != null && kijun[i] != null) ? (tenkan[i] + kijun[i]) / 2 : null; });
    return { tenkan: tenkan, kijun: kijun, spanA: spanA, spanB: b };
  };
  A.pivots = function (h, l, c) {
    var p = (h + l + c) / 3;
    return {
      classic: { p: p, r1: 2 * p - l, s1: 2 * p - h, r2: p + (h - l), s2: p - (h - l), r3: h + 2 * (p - l), s3: l - 2 * (h - p) },
      fib: { p: p, r1: p + 0.382 * (h - l), s1: p - 0.382 * (h - l), r2: p + 0.618 * (h - l), s2: p - 0.618 * (h - l), r3: p + (h - l), s3: p - (h - l) }
    };
  };
  A.fibRetrace = function (hi, lo) {
    var d = hi - lo;
    return [
      { label: '0% (high)', price: hi }, { label: '23.6%', price: hi - 0.236 * d },
      { label: '38.2%', price: hi - 0.382 * d }, { label: '50%', price: hi - 0.5 * d },
      { label: '61.8%', price: hi - 0.618 * d }, { label: '78.6%', price: hi - 0.786 * d },
      { label: '100% (low)', price: lo }
    ];
  };
  // Auto support/resistance via local extrema clustering
  A.supportResistance = function (h, l, lookback) {
    lookback = lookback || 3;
    var piv = [];
    for (var i = lookback; i < h.length - lookback; i++) {
      var isHigh = true, isLow = true;
      for (var j = 1; j <= lookback; j++) {
        if (h[i] < h[i - j] || h[i] < h[i + j]) isHigh = false;
        if (l[i] > l[i - j] || l[i] > l[i + j]) isLow = false;
      }
      if (isHigh) piv.push({ price: h[i], type: 'r' });
      if (isLow) piv.push({ price: l[i], type: 's' });
    }
    // cluster nearby levels (within 1.5%)
    piv.sort(function (a, b) { return a.price - b.price; });
    var levels = [];
    piv.forEach(function (pv) {
      var near = levels.find(function (lv) { return Math.abs(lv.price - pv.price) / pv.price < 0.015; });
      if (near) { near.price = (near.price * near.count + pv.price) / (near.count + 1); near.count++; }
      else levels.push({ price: pv.price, count: 1 });
    });
    return levels.filter(function (lv) { return lv.count >= 2; })
      .sort(function (a, b) { return b.count - a.count; }).slice(0, 6);
  };

  /* ── Statistics ── */
  A.returns = function (closes) {
    var r = [];
    for (var i = 1; i < closes.length; i++) r.push(closes[i] / closes[i - 1] - 1);
    return r;
  };
  A.mean = function (a) { return a.reduce(function (s, x) { return s + x; }, 0) / (a.length || 1); };
  A.std = function (a) {
    var m = A.mean(a);
    return Math.sqrt(a.reduce(function (s, x) { return s + Math.pow(x - m, 2); }, 0) / (a.length || 1));
  };
  A.maxDrawdown = function (closes) {
    var peak = closes[0], maxDD = 0, curDD = 0;
    for (var i = 0; i < closes.length; i++) {
      if (closes[i] > peak) peak = closes[i];
      var dd = (closes[i] - peak) / peak;
      if (dd < maxDD) maxDD = dd;
      if (i === closes.length - 1) curDD = dd;
    }
    return { max: maxDD, current: curDD };
  };
  A.beta = function (assetRet, benchRet) {
    var n = Math.min(assetRet.length, benchRet.length);
    var a = assetRet.slice(-n), b = benchRet.slice(-n);
    var ma = A.mean(a), mb = A.mean(b), cov = 0, varB = 0;
    for (var i = 0; i < n; i++) { cov += (a[i] - ma) * (b[i] - mb); varB += Math.pow(b[i] - mb, 2); }
    return varB === 0 ? null : cov / varB;
  };
  A.correlation = function (a, b) {
    var n = Math.min(a.length, b.length);
    a = a.slice(-n); b = b.slice(-n);
    var ma = A.mean(a), mb = A.mean(b), num = 0, da = 0, db = 0;
    for (var i = 0; i < n; i++) { num += (a[i] - ma) * (b[i] - mb); da += Math.pow(a[i] - ma, 2); db += Math.pow(b[i] - mb, 2); }
    return (da === 0 || db === 0) ? 0 : num / Math.sqrt(da * db);
  };
  A.sharpe = function (rets, rf) {
    var ann = A.mean(rets) * 252 - rf;
    var vol = A.std(rets) * Math.sqrt(252);
    return vol === 0 ? null : ann / vol;
  };
  A.sortino = function (rets, rf) {
    var ann = A.mean(rets) * 252 - rf;
    var down = rets.filter(function (r) { return r < 0; });
    var dd = Math.sqrt(A.mean(down.map(function (r) { return r * r; })) || 0) * Math.sqrt(252);
    return dd === 0 ? null : ann / dd;
  };
  A.linReg = function (closes) {
    var n = closes.length, sx = 0, sy = 0, sxy = 0, sxx = 0;
    for (var i = 0; i < n; i++) { sx += i; sy += closes[i]; sxy += i * closes[i]; sxx += i * i; }
    var slope = (n * sxy - sx * sy) / (n * sxx - sx * sx);
    var intercept = (sy - slope * sx) / n;
    var fitted = closes.map(function (_, i) { return intercept + slope * i; });
    var resid = closes.map(function (c, i) { return c - fitted[i]; });
    var se = A.std(resid);
    return { slope: slope, intercept: intercept, fitted: fitted, se: se };
  };
  A.monteCarlo = function (lastPrice, rets, days, paths) {
    days = days || 60; paths = paths || 500;
    var mu = A.mean(rets), sigma = A.std(rets);
    var finals = [];
    for (var p = 0; p < paths; p++) {
      var price = lastPrice;
      for (var d = 0; d < days; d++) {
        // Box-Muller normal
        var u1 = Math.random() || 1e-9, u2 = Math.random();
        var z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
        price *= Math.exp((mu - 0.5 * sigma * sigma) + sigma * z);
      }
      finals.push(price);
    }
    finals.sort(function (a, b) { return a - b; });
    var pct = function (q) { return finals[Math.floor(q * (finals.length - 1))]; };
    return { p5: pct(0.05), p25: pct(0.25), p50: pct(0.5), p75: pct(0.75), p95: pct(0.95),
      mean: A.mean(finals), days: days, paths: paths };
  };

  /* ── Candlestick patterns (check most recent candle) ── */
  A.detectPatterns = function (candles) {
    var found = [];
    var n = candles.length;
    if (n < 3) return found;
    function body(c) { return Math.abs(c.c - c.o); }
    function range(c) { return c.h - c.l; }
    function upperWick(c) { return c.h - Math.max(c.o, c.c); }
    function lowerWick(c) { return Math.min(c.o, c.c) - c.l; }
    var last = candles[n - 1], prev = candles[n - 2], prev2 = candles[n - 3];
    var r = range(last) || 1e-9;
    if (body(last) / r < 0.1) found.push({ name: 'Doji', dir: 'neutral', idx: n - 1 });
    if (lowerWick(last) > 2 * body(last) && upperWick(last) < body(last) && body(last) / r > 0.05)
      found.push({ name: 'Hammer', dir: 'bullish', idx: n - 1 });
    if (upperWick(last) > 2 * body(last) && lowerWick(last) < body(last) && body(last) / r > 0.05)
      found.push({ name: 'Shooting Star', dir: 'bearish', idx: n - 1 });
    if (last.c > last.o && prev.c < prev.o && last.c >= prev.o && last.o <= prev.c)
      found.push({ name: 'Bullish Engulfing', dir: 'bullish', idx: n - 1 });
    if (last.c < last.o && prev.c > prev.o && last.o >= prev.c && last.c <= prev.o)
      found.push({ name: 'Bearish Engulfing', dir: 'bearish', idx: n - 1 });
    if (prev2.c < prev2.o && body(prev) / (range(prev) || 1e-9) < 0.3 && last.c > last.o && last.c > (prev2.o + prev2.c) / 2)
      found.push({ name: 'Morning Star', dir: 'bullish', idx: n - 1 });
    if (prev2.c > prev2.o && body(prev) / (range(prev) || 1e-9) < 0.3 && last.c < last.o && last.c < (prev2.o + prev2.c) / 2)
      found.push({ name: 'Evening Star', dir: 'bearish', idx: n - 1 });
    return found;
  };

  /* ── Aggregate signal (TradingView-style rating) ── */
  A.computeSignals = function (ctx) {
    // ctx: { closes, rsi, macd, sma20, sma50, sma200, ema20, adx, plusDI, minusDI, stochK, cci, willr, price }
    var sig = []; // {name, value, read: 'bullish'|'bearish'|'neutral', note}
    var last = function (a) { return a[a.length - 1]; };
    var price = ctx.price;
    function add(name, read, note) { sig.push({ name: name, read: read, note: note }); }

    var rsi = last(ctx.rsi);
    if (rsi != null) add('RSI (14)', rsi > 70 ? 'bearish' : rsi < 30 ? 'bullish' : 'neutral',
      rsi > 70 ? 'Overbought' : rsi < 30 ? 'Oversold' : 'Neutral zone');
    var mh = last(ctx.macd.hist);
    if (mh != null) add('MACD', mh > 0 ? 'bullish' : mh < 0 ? 'bearish' : 'neutral',
      mh > 0 ? 'Above signal line' : 'Below signal line');
    [['SMA 20', ctx.sma20], ['SMA 50', ctx.sma50], ['SMA 200', ctx.sma200], ['EMA 20', ctx.ema20]].forEach(function (m) {
      var v = last(m[1]);
      if (v != null) add('Price vs ' + m[0], price > v ? 'bullish' : 'bearish', (price > v ? 'Above ' : 'Below ') + m[0]);
    });
    var adx = last(ctx.adx), pdi = last(ctx.plusDI), mdi = last(ctx.minusDI);
    if (adx != null && pdi != null) add('ADX / DMI',
      adx < 20 ? 'neutral' : (pdi > mdi ? 'bullish' : 'bearish'),
      adx < 20 ? 'Weak/no trend' : (pdi > mdi ? 'Trending up' : 'Trending down') + ' (ADX ' + adx.toFixed(0) + ')');
    var sk = last(ctx.stochK);
    if (sk != null) add('Stochastic', sk > 80 ? 'bearish' : sk < 20 ? 'bullish' : 'neutral',
      sk > 80 ? 'Overbought' : sk < 20 ? 'Oversold' : 'Mid-range');
    var cci = last(ctx.cci);
    if (cci != null) add('CCI', cci > 100 ? 'bullish' : cci < -100 ? 'bearish' : 'neutral',
      cci > 100 ? 'Strong up' : cci < -100 ? 'Strong down' : 'Neutral');
    var wr = last(ctx.willr);
    if (wr != null) add('Williams %R', wr > -20 ? 'bearish' : wr < -80 ? 'bullish' : 'neutral',
      wr > -20 ? 'Overbought' : wr < -80 ? 'Oversold' : 'Mid-range');
    // Golden/death cross
    if (last(ctx.sma50) != null && last(ctx.sma200) != null)
      add('50/200 MA cross', last(ctx.sma50) > last(ctx.sma200) ? 'bullish' : 'bearish',
        last(ctx.sma50) > last(ctx.sma200) ? 'Golden cross regime' : 'Death cross regime');

    var bull = sig.filter(function (s) { return s.read === 'bullish'; }).length;
    var bear = sig.filter(function (s) { return s.read === 'bearish'; }).length;
    var neut = sig.filter(function (s) { return s.read === 'neutral'; }).length;
    var score = (bull - bear) / (sig.length || 1);
    var label = score > 0.5 ? 'Strong Bullish' : score > 0.15 ? 'Bullish' :
      score < -0.5 ? 'Strong Bearish' : score < -0.15 ? 'Bearish' : 'Neutral';
    return { signals: sig, bull: bull, bear: bear, neutral: neut, score: score, label: label };
  };

  /* ── Backtest: RSI mean-reversion or MA crossover ── */
  A.backtest = function (closes, strategy) {
    var pos = 0, entry = 0, trades = [], equity = 1;
    var rsi = A.rsi(closes, 14);
    var sma50 = A.sma(closes, 50), sma200 = A.sma(closes, 200);
    for (var i = 1; i < closes.length; i++) {
      var buy = false, sell = false;
      if (strategy === 'rsi') {
        if (rsi[i] != null && rsi[i - 1] != null) {
          if (rsi[i] < 30 && pos === 0) buy = true;
          if (rsi[i] > 70 && pos === 1) sell = true;
        }
      } else { // ma cross
        if (sma50[i] != null && sma200[i] != null && sma50[i - 1] != null) {
          if (sma50[i] > sma200[i] && sma50[i - 1] <= sma200[i - 1] && pos === 0) buy = true;
          if (sma50[i] < sma200[i] && sma50[i - 1] >= sma200[i - 1] && pos === 1) sell = true;
        }
      }
      if (buy) { pos = 1; entry = closes[i]; }
      else if (sell) { var ret = closes[i] / entry - 1; equity *= (1 + ret); trades.push(ret); pos = 0; }
    }
    if (pos === 1) { var r = closes[closes.length - 1] / entry - 1; equity *= (1 + r); trades.push(r); }
    var wins = trades.filter(function (t) { return t > 0; }).length;
    // buy & hold comparison
    var bh = closes[closes.length - 1] / closes[0] - 1;
    return {
      trades: trades.length, winRate: trades.length ? wins / trades.length : 0,
      totalReturn: equity - 1, buyHold: bh,
      avgTrade: trades.length ? A.mean(trades) : 0
    };
  };

  /* ═══ 4. EXPLANATIONS ═══════════════════════════════════════════════════ */
  var EXPLAIN = {
    rsi: 'Relative Strength Index — momentum on a 0–100 scale. Above 70 is often called "overbought" (price may have run up fast); below 30 "oversold" (may have fallen fast). It measures speed, not direction of value.',
    macd: 'Moving Average Convergence Divergence — compares a fast and slow moving average. When the MACD line is above its signal line (positive histogram), short-term momentum is rising; below, it\'s falling.',
    sma: 'Simple Moving Average — the average closing price over N days. Price above a rising average is a basic uptrend sign; below a falling one, a downtrend.',
    ema: 'Exponential Moving Average — like an SMA but weighted toward recent prices, so it reacts faster to new moves.',
    bollinger: 'Bollinger Bands — a moving average with bands 2 standard deviations above/below. Price near the upper band = stretched high; near the lower = stretched low. Bands widen when volatility rises.',
    atr: 'Average True Range — the typical size of a day\'s price swing in dollars. Bigger ATR = more volatile. Useful for setting stop-losses that fit how much the stock actually moves.',
    adx: 'ADX measures trend STRENGTH (not direction) from 0–100. Below 20 = weak/choppy; above 25 = a real trend. The +DI/−DI lines show whether buyers or sellers are in control.',
    stochastic: 'Stochastic Oscillator — where today\'s close sits within the recent high-low range, 0–100. Above 80 overbought, below 20 oversold. Good for spotting short-term turns.',
    stochrsi: 'Stochastic RSI — applies the stochastic formula to RSI for a more sensitive overbought/oversold read.',
    cci: 'Commodity Channel Index — how far price is from its average. Above +100 = unusually strong; below −100 = unusually weak.',
    willr: 'Williams %R — like stochastic, inverted (−100 to 0). Above −20 overbought, below −80 oversold.',
    roc: 'Rate of Change — the percent price has moved over N days. Positive = upward momentum.',
    obv: 'On-Balance Volume — adds volume on up days, subtracts on down days. A rising OBV suggests buying pressure is confirming the price move.',
    vwap: 'Volume-Weighted Average Price — the average price weighted by volume. Traders watch whether price is above (bullish intraday) or below it.',
    mfi: 'Money Flow Index — like RSI but includes volume. Above 80 overbought, below 20 oversold, with a "is money flowing in?" angle.',
    ad: 'Accumulation/Distribution — uses where price closes in its range plus volume to gauge whether shares are being accumulated (bought) or distributed (sold).',
    keltner: 'Keltner Channels — an EMA with bands set by ATR. Similar to Bollinger Bands but volatility-based; price riding the upper band signals strong momentum.',
    sar: 'Parabolic SAR — dots that trail price; they flip sides when the short-term trend reverses. Often used to trail a stop.',
    ichimoku: 'Ichimoku Cloud — a system showing trend, support/resistance and momentum at once. Price above the "cloud" is bullish, below is bearish.',
    pivots: 'Pivot Points — reference support/resistance levels for the next session, derived from the prior period\'s high, low and close.',
    fib: 'Fibonacci Retracement — horizontal levels (23.6%, 38.2%, 50%, 61.8%) where a pullback often pauses, drawn between a recent high and low.',
    sr: 'Support & Resistance — price areas the stock has repeatedly bounced off (support) or stalled at (resistance). Breaks of these levels often matter.',
    marketCap: 'Market Capitalization — the total value of all shares (price × shares outstanding). Roughly, the size of the company.',
    peTrailing: 'Price-to-Earnings (trailing) — price divided by the last 12 months of earnings per share. Higher = investors pay more per dollar of profit (growth expectations or overvaluation).',
    peForward: 'Forward P/E — same idea using forecast earnings. Lower than trailing P/E suggests earnings are expected to grow.',
    peg: 'PEG Ratio — P/E divided by earnings growth. Around 1 is often considered fair; below 1 may be cheap relative to growth.',
    priceToBook: 'Price-to-Book — price vs. the company\'s net asset value. Below 1 can mean undervalued (or troubled); high P/B is common for asset-light tech.',
    priceToSales: 'Price-to-Sales — price vs. revenue. Useful for companies with little or no profit yet.',
    eps: 'Earnings Per Share — profit divided by shares. The "E" in P/E.',
    revenueGrowth: 'Revenue Growth — how fast sales are growing year-over-year.',
    earningsGrowth: 'Earnings Growth — how fast profits are growing year-over-year.',
    profitMargin: 'Profit Margin — what fraction of revenue becomes profit. Higher is generally healthier.',
    roe: 'Return on Equity — profit generated per dollar of shareholder equity. Higher = more efficient use of investors\' money.',
    roa: 'Return on Assets — profit per dollar of assets. Efficiency of the whole asset base.',
    debtToEquity: 'Debt-to-Equity — borrowed money vs. shareholder equity. High values mean more leverage and more risk.',
    currentRatio: 'Current Ratio — short-term assets vs. short-term bills. Above 1 means it can cover near-term obligations.',
    freeCashflow: 'Free Cash Flow — cash left after running and investing in the business. Positive and growing is a strong sign.',
    dividendYield: 'Dividend Yield — annual dividend as a percent of price. Income return; 0% means no dividend.',
    beta: 'Beta — how much the stock moves relative to the market. 1 = moves with the market; above 1 = more volatile; below 1 = steadier.',
    week52: '52-Week Range — the lowest and highest price over the past year. Shows where today sits in that band.',
    volatility: 'Volatility (annualized) — how much the price swings, as a yearly percentage. Higher = bigger ups and downs.',
    maxDrawdown: 'Maximum Drawdown — the worst peak-to-trough drop over the period. Shows the pain an investor would have endured.',
    sharpe: 'Sharpe Ratio — return earned per unit of risk (volatility). Above 1 is good, above 2 is excellent; negative means you weren\'t paid for the risk.',
    sortino: 'Sortino Ratio — like Sharpe but only counts downside volatility, since upside swings aren\'t really "risk".',
    correlation: 'Correlation — how closely two stocks move together, from −1 to +1. Near +1 means they rise and fall in sync (less diversification benefit).',
    montecarlo: 'Monte Carlo Simulation — runs thousands of random future price paths based on past behavior to show a RANGE of outcomes. It is a statistical illustration, NOT a prediction.',
    positionSize: 'Position Sizing — how many shares to buy so that, if your stop-loss is hit, you only lose your chosen risk amount. Core risk discipline.',
    riskReward: 'Risk/Reward Ratio — potential profit divided by potential loss. 2:1 means you aim to make twice what you risk.'
  };

  /* ═══ 5. UI ═════════════════════════════════════════════════════════════ */
  // (defined in stocks.ui.js — kept here as a single module via the global)
  window.AndyStocks = { Data: Data, A: A, EXPLAIN: EXPLAIN, getWatchlist: getWatchlist,
    setWatchlist: setWatchlist, BENCHMARK: BENCHMARK, RISK_FREE: RISK_FREE,
    DEFAULT_WATCHLIST: DEFAULT_WATCHLIST, ALERT_KEY: ALERT_KEY };

  // Lightweight self-tests (run with ?satest=1)
  if (location.search.indexOf('satest=1') !== -1) {
    var t = [1,2,3,4,5,6,7,8,9,10];
    console.assert(A.sma(t,2)[1] === 1.5, 'sma');
    console.assert(Math.abs(A.mean([2,4,6]) - 4) < 1e-9, 'mean');
    console.assert(A.rsi([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15],14).slice(-1)[0] === 100, 'rsi all-up=100');
    console.assert(A.maxDrawdown([10,8,12,6]).max < 0, 'drawdown negative');
    console.log('AndyStocks self-tests ran.');
  }

  if (window.AndyStocksUI) window.AndyStocksUI.boot();
})();
