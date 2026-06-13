/* ═══════════════════════════════════════════════════════════════════════
   Hero signature — "Soundings"
   A live bathymetric contour field (depth chart) with a survey transect and
   waypoints, behind the homepage thesis. Cursor nudges the contours; a slow
   sonar ping sweeps from the moving vessel. Pure canvas, ~60fps, theme-aware,
   and fully static under prefers-reduced-motion.
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var canvas = document.getElementById('hero-sonar');
  if (!canvas || !canvas.getContext) return;
  var ctx = canvas.getContext('2d');
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var home = document.getElementById('home');

  var W = 0, H = 0, DPR = 1, t = 0, raf = null;
  var mouse = { x: 0, y: 0, active: false };

  // Survey transect (normalized coords) — a believable lawnmower-pattern path.
  var waypoints = [
    [0.16, 0.32], [0.30, 0.60], [0.44, 0.40], [0.58, 0.66], [0.72, 0.42], [0.86, 0.58]
  ];

  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }
  function hexToRgb(hex) {
    hex = (hex || '').replace('#', '').trim();
    if (hex.length === 3) hex = hex.split('').map(function (c) { return c + c; }).join('');
    var n = parseInt(hex, 16);
    if (isNaN(n) || hex.length !== 6) return [13, 110, 125];
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  var teal = [13, 110, 125], amber = [166, 83, 9];
  function refreshColors() {
    teal = hexToRgb(cssVar('--green', '#0d6e7d'));
    amber = hexToRgb(cssVar('--clay', '#a65309'));
  }
  function rgba(c, a) { return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'; }

  function resize() {
    W = canvas.clientWidth; H = canvas.clientHeight;
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, W * DPR);
    canvas.height = Math.max(1, H * DPR);
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    refreshColors();
  }

  function drawContours() {
    var cx = W * 0.66, cy = H * 0.46;
    var rings = 9;
    for (var r = rings - 1; r >= 0; r--) {
      var base = 46 + r * 42;
      ctx.beginPath();
      var pts = 80;
      for (var i = 0; i <= pts; i++) {
        var a = (i / pts) * Math.PI * 2;
        var disp = Math.sin(a * 3 + t * 0.6 + r * 0.5) * 11 +
                   Math.sin(a * 5 - t * 0.4 + r) * 6 +
                   Math.cos(a * 2 + t * 0.3) * 9;
        var rad = base + disp;
        var x = cx + Math.cos(a) * rad * 1.2;
        var y = cy + Math.sin(a) * rad * 0.82;
        if (mouse.active) {
          var dx = x - mouse.x, dy = y - mouse.y, d = Math.sqrt(dx * dx + dy * dy);
          if (d < 150 && d > 0.01) { var f = (150 - d) / 150 * 16; x += dx / d * f; y += dy / d * f; }
        }
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.closePath();
      var alpha = 0.05 + ((rings - r) / rings) * 0.13;
      ctx.strokeStyle = rgba(teal, alpha);
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }

  function px(w) { return [w[0] * W, w[1] * H]; }

  function drawSurvey() {
    // dashed transect
    ctx.beginPath();
    waypoints.forEach(function (w, i) { var p = px(w); i === 0 ? ctx.moveTo(p[0], p[1]) : ctx.lineTo(p[0], p[1]); });
    ctx.setLineDash([3, 7]);
    ctx.strokeStyle = rgba(teal, 0.45);
    ctx.lineWidth = 1.3;
    ctx.stroke();
    ctx.setLineDash([]);

    // waypoint markers
    waypoints.forEach(function (w) {
      var p = px(w);
      ctx.beginPath(); ctx.arc(p[0], p[1], 2.6, 0, Math.PI * 2);
      ctx.fillStyle = rgba(teal, 0.85); ctx.fill();
      ctx.beginPath(); ctx.arc(p[0], p[1], 6, 0, Math.PI * 2);
      ctx.strokeStyle = rgba(teal, 0.3); ctx.lineWidth = 1; ctx.stroke();
    });

    // moving vessel along the transect (loops); the live data point in amber
    var segCount = waypoints.length - 1;
    var prog = reduce ? 0.5 : ((t * 0.05) % 1);
    var fs = prog * segCount;
    var si = Math.min(segCount - 1, Math.floor(fs));
    var lt = fs - si;
    var a = px(waypoints[si]), b = px(waypoints[si + 1]);
    var vx = a[0] + (b[0] - a[0]) * lt, vy = a[1] + (b[1] - a[1]) * lt;

    // sonar ping expanding from the vessel
    if (!reduce) {
      var ping = (t * 0.4) % 3;
      var pr = ping * 26;
      ctx.beginPath(); ctx.arc(vx, vy, pr, 0, Math.PI * 2);
      ctx.strokeStyle = rgba(amber, Math.max(0, 0.5 - ping / 6));
      ctx.lineWidth = 1.4; ctx.stroke();
    }
    ctx.beginPath(); ctx.arc(vx, vy, 4, 0, Math.PI * 2);
    ctx.fillStyle = rgba(amber, 0.95); ctx.fill();
  }

  function frame() {
    ctx.clearRect(0, 0, W, H);
    drawContours();
    drawSurvey();
    if (!reduce) { t += 0.016; raf = requestAnimationFrame(frame); }
  }

  function start() { if (raf == null && !reduce) { raf = requestAnimationFrame(frame); } }
  function stop() { if (raf != null) { cancelAnimationFrame(raf); raf = null; } }

  // Only animate while Home is visible (saves battery/CPU on other tabs)
  function syncRun() {
    if (home && home.classList.contains('active') && !document.hidden) start();
    else stop();
  }

  window.addEventListener('resize', function () { resize(); if (reduce) frame(); });
  // Listen on the section (canvas is click-through) so buttons still work and
  // the contours react to the cursor anywhere in the hero.
  var pointerTarget = home || canvas;
  pointerTarget.addEventListener('pointermove', function (e) {
    var rect = canvas.getBoundingClientRect();
    mouse.x = e.clientX - rect.left; mouse.y = e.clientY - rect.top; mouse.active = true;
  });
  pointerTarget.addEventListener('pointerleave', function () { mouse.active = false; });
  document.addEventListener('visibilitychange', syncRun);
  if (home) {
    new MutationObserver(syncRun).observe(home, { attributes: true, attributeFilter: ['class'] });
  }

  // boot
  function boot() {
    resize();
    if (reduce) { frame(); }      // single static frame
    else { syncRun(); }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
