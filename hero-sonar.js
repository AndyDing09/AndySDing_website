/* ═══════════════════════════════════════════════════════════════════════
   Hero signature — a live survey chart.
   Faint bathymetric contours and scattered depth soundings (the static
   chart), plus a magenta vessel tracing a 6-waypoint survey track — the
   same 3-convergence + 3-control design Kymarion runs. Theme-aware,
   pauses off-tab and off-section, renders one static frame under
   reduced motion.
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var canvas = document.getElementById('hero-sonar');
  if (!canvas || !canvas.getContext) return;
  var ctx = canvas.getContext('2d');
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var home = document.getElementById('home');

  var W = 0, H = 0, DPR = 1, raf = null;
  var chart = null;              // offscreen static layer (contours + soundings)
  var ink = [18, 38, 44], teal = [20, 108, 116], magenta = [168, 44, 106];
  var dark = false;

  function cssVar(name, fb) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (v && v.trim()) || fb;
  }
  function hexToRgb(hex) {
    hex = (hex || '').replace('#', '').trim();
    if (hex.length === 3) hex = hex.split('').map(function (c) { return c + c; }).join('');
    var n = parseInt(hex, 16);
    if (isNaN(n) || hex.length !== 6) return [18, 38, 44];
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function rgba(c, a) { return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'; }
  function refreshColors() {
    ink = hexToRgb(cssVar('--ink', '#12262c'));
    teal = hexToRgb(cssVar('--green', '#146c74'));
    magenta = hexToRgb(cssVar('--clay', '#a82c6a'));
    dark = document.documentElement.dataset.theme === 'dark';
  }

  /* Seeded PRNG so the chart is identical every visit (it's a chart, not confetti) */
  function lcg(seed) {
    var s = seed >>> 0;
    return function () { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  }

  /* ── Static chart layer: contours + soundings ── */
  function drawChart() {
    chart = document.createElement('canvas');
    chart.width = Math.max(1, W * DPR);
    chart.height = Math.max(1, H * DPR);
    var c = chart.getContext('2d');
    c.setTransform(DPR, 0, 0, DPR, 0, 0);

    var rnd = lcg(20260703);
    var lineA = dark ? 0.10 : 0.075;

    /* Shoals: nested distorted iso-lines around three centers, kept right of
       the headline so the text column stays clean. */
    var shoals = [
      { x: W * 0.74, y: H * 0.28, r: Math.min(W, H) * 0.16, n: 5 },
      { x: W * 0.60, y: H * 0.76, r: Math.min(W, H) * 0.20, n: 6 },
      { x: W * 0.92, y: H * 0.60, r: Math.min(W, H) * 0.13, n: 4 },
    ];
    shoals.forEach(function (s) {
      var w1 = 2 + Math.floor(rnd() * 3), w2 = 3 + Math.floor(rnd() * 4);
      var p1 = rnd() * Math.PI * 2, p2 = rnd() * Math.PI * 2;
      var a1 = 0.10 + rnd() * 0.08, a2 = 0.05 + rnd() * 0.05;
      for (var k = s.n; k >= 1; k--) {
        var R = s.r * (k / s.n);
        c.beginPath();
        for (var i = 0; i <= 96; i++) {
          var th = (i / 96) * Math.PI * 2;
          var r = R * (1 + a1 * Math.sin(w1 * th + p1) + a2 * Math.sin(w2 * th + p2));
          var x = s.x + r * Math.cos(th), y = s.y + r * Math.sin(th) * 0.82;
          if (i === 0) c.moveTo(x, y); else c.lineTo(x, y);
        }
        c.closePath();
        if (k === 1) { c.fillStyle = rgba(teal, dark ? 0.05 : 0.04); c.fill(); }
        c.strokeStyle = rgba(ink, lineA);
        c.lineWidth = 1;
        c.stroke();
      }
    });

    /* Depth soundings: small mono numbers scattered across open water */
    c.font = '10px "IBM Plex Mono", monospace';
    c.fillStyle = rgba(ink, dark ? 0.20 : 0.15);
    for (var i = 0; i < 46; i++) {
      var x = rnd() * W, y = rnd() * H;
      var d = 3 + Math.floor(rnd() * 55);
      if (x < W * 0.48 && y > H * 0.20 && y < H * 0.88) continue; /* keep the text column clean */
      c.fillText(String(d), x, y);
    }
  }

  /* ── Survey track: 6 stations, vessel, sampling pings ── */
  var track = { pts: [], lens: [], total: 1 };
  function buildTrack() {
    var pts = [
      [W * 1.01, H * 0.14],
      [W * 0.84, H * 0.34],
      [W * 0.93, H * 0.60],
      [W * 0.70, H * 0.50],
      [W * 0.64, H * 0.80],
      [W * 0.44, H * 0.90],
    ];
    var lens = [0], total = 0;
    for (var i = 1; i < pts.length; i++) {
      total += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
      lens.push(total);
    }
    track = { pts: pts, lens: lens, total: total || 1 };
  }
  function pointAt(dist) {
    var p = track.pts, l = track.lens;
    for (var i = 1; i < p.length; i++) {
      if (dist <= l[i]) {
        var t = (dist - l[i - 1]) / (l[i] - l[i - 1] || 1);
        return {
          x: p[i - 1][0] + (p[i][0] - p[i - 1][0]) * t,
          y: p[i - 1][1] + (p[i][1] - p[i - 1][1]) * t,
          a: Math.atan2(p[i][1] - p[i - 1][1], p[i][0] - p[i - 1][0]),
        };
      }
    }
    var n = p.length - 1;
    return { x: p[n][0], y: p[n][1], a: 0 };
  }

  var LOOP = 52000, HOLD = 3000;   /* ms per survey pass + hold before restart */
  var t0 = null;

  function drawStations(dist, prog) {
    ctx.font = '10px "IBM Plex Mono", monospace';
    for (var i = 0; i < track.pts.length; i++) {
      var p = track.pts[i], sampled = track.lens[i] <= dist;
      var col = sampled ? teal : ink;
      ctx.strokeStyle = rgba(col, sampled ? 0.8 : 0.35);
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(p[0] - 5, p[1]); ctx.lineTo(p[0] + 5, p[1]);
      ctx.moveTo(p[0], p[1] - 5); ctx.lineTo(p[0], p[1] + 5);
      ctx.stroke();
      ctx.fillStyle = rgba(col, sampled ? 0.75 : 0.35);
      ctx.fillText('WP-' + (i + 1), p[0] + 9, p[1] - 6);

      /* sampling ping: ring expanding for ~1.6s after arrival */
      if (sampled && prog < 1) {
        var since = (dist - track.lens[i]) / track.total * LOOP;
        if (since >= 0 && since < 1600) {
          var k = since / 1600;
          ctx.beginPath();
          ctx.arc(p[0], p[1], 6 + k * 26, 0, Math.PI * 2);
          ctx.strokeStyle = rgba(magenta, 0.5 * (1 - k));
          ctx.lineWidth = 1.4;
          ctx.stroke();
        }
      }
    }
  }

  function drawFrame(now) {
    if (t0 === null) t0 = now;
    var t = (now - t0) % (LOOP + HOLD);
    var prog = Math.min(t / LOOP, 1);
    var dist = prog * track.total;
    var fade = t > LOOP ? 1 - (t - LOOP) / HOLD : 1;

    ctx.clearRect(0, 0, W, H);
    if (chart) ctx.drawImage(chart, 0, 0, W, H);

    ctx.save();
    ctx.globalAlpha = fade;

    /* Planned route — dashed, quiet */
    ctx.beginPath();
    track.pts.forEach(function (p, i) { i === 0 ? ctx.moveTo(p[0], p[1]) : ctx.lineTo(p[0], p[1]); });
    ctx.setLineDash([3, 7]);
    ctx.strokeStyle = rgba(ink, dark ? 0.26 : 0.20);
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.setLineDash([]);

    /* Surveyed portion — solid teal up to the vessel */
    var v = pointAt(dist);
    ctx.beginPath();
    ctx.moveTo(track.pts[0][0], track.pts[0][1]);
    for (var i = 1; i < track.pts.length && track.lens[i] <= dist; i++) {
      ctx.lineTo(track.pts[i][0], track.pts[i][1]);
    }
    ctx.lineTo(v.x, v.y);
    ctx.strokeStyle = rgba(teal, dark ? 0.55 : 0.45);
    ctx.lineWidth = 1.6;
    ctx.stroke();

    drawStations(dist, prog);

    /* Vessel: magenta diamond on heading */
    if (prog < 1) {
      ctx.save();
      ctx.translate(v.x, v.y);
      ctx.rotate(v.a + Math.PI / 4);
      ctx.fillStyle = rgba(magenta, 0.95);
      ctx.fillRect(-4.5, -4.5, 9, 9);
      ctx.restore();
    }
    ctx.restore();
  }

  function drawStatic() {
    /* Reduced motion: the finished survey — full track, all stations sampled */
    ctx.clearRect(0, 0, W, H);
    if (chart) ctx.drawImage(chart, 0, 0, W, H);
    ctx.beginPath();
    track.pts.forEach(function (p, i) { i === 0 ? ctx.moveTo(p[0], p[1]) : ctx.lineTo(p[0], p[1]); });
    ctx.strokeStyle = rgba(teal, 0.45);
    ctx.lineWidth = 1.6;
    ctx.stroke();
    drawStations(track.total + 1, 1);
  }

  function resize() {
    W = canvas.clientWidth; H = canvas.clientHeight;
    if (!W || !H) return;
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, W * DPR);
    canvas.height = Math.max(1, H * DPR);
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    refreshColors();
    drawChart();
    buildTrack();
  }

  function frame(now) {
    if (W !== canvas.clientWidth || H !== canvas.clientHeight) resize();
    if (W && H) drawFrame(now);
    raf = requestAnimationFrame(frame);
  }

  function start() { if (raf == null && !reduce) raf = requestAnimationFrame(frame); }
  function stop() { if (raf != null) { cancelAnimationFrame(raf); raf = null; } }
  function syncRun() {
    if ((!home || home.classList.contains('active')) && !document.hidden) start(); else stop();
  }

  window.addEventListener('resize', function () { resize(); if (reduce) drawStatic(); });
  document.addEventListener('visibilitychange', syncRun);
  if (home) new MutationObserver(syncRun).observe(home, { attributes: true, attributeFilter: ['class'] });
  /* Re-ink on theme toggle */
  new MutationObserver(function () {
    refreshColors(); drawChart();
    if (reduce) drawStatic();
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

  function boot() { resize(); if (reduce) drawStatic(); else syncRun(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
