/* ═══════════════════════════════════════════════════════════════════════
   Hero signature — a slow rotating wireframe globe (the "model").
   Spins continuously and leans toward the cursor, so the hero feels alive
   and reactive (dashcreative-style). Pure canvas, theme-aware, ~60fps,
   pauses off-tab, and renders a single static frame under reduced-motion.
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var canvas = document.getElementById('hero-sonar');
  if (!canvas || !canvas.getContext) return;
  var ctx = canvas.getContext('2d');
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var home = document.getElementById('home');

  var W = 0, H = 0, DPR = 1, t = 0, raf = null;
  var spin = 0;                          // continuous Y rotation
  var tiltX = -0.35, tiltY = 0;          // eased mouse lean
  var tgtX = -0.35, tgtY = 0;            // targets from cursor

  function cssVar(name, fb) { var v = getComputedStyle(document.documentElement).getPropertyValue(name); return (v && v.trim()) || fb; }
  function hexToRgb(hex) {
    hex = (hex || '').replace('#', '').trim();
    if (hex.length === 3) hex = hex.split('').map(function (c) { return c + c; }).join('');
    var n = parseInt(hex, 16);
    if (isNaN(n) || hex.length !== 6) return [63, 91, 80];
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  var accent = [63, 91, 80], warm = [200, 140, 70];
  function refreshColors() { accent = hexToRgb(cssVar('--green', '#3f5b50')); warm = hexToRgb(cssVar('--clay', '#8a6f53')); }
  function rgba(c, a) { return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'; }

  function resize() {
    W = canvas.clientWidth; H = canvas.clientHeight;
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, W * DPR);
    canvas.height = Math.max(1, H * DPR);
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    refreshColors();
  }

  // rotate a unit-sphere point by current tilt/spin, return projected screen pt
  function project(lat, lon, cx, cy, R) {
    var x = Math.cos(lat) * Math.cos(lon),
        y = Math.sin(lat),
        z = Math.cos(lat) * Math.sin(lon);
    // rotate Y (spin + horizontal lean)
    var ry = spin + tiltY, cy0 = Math.cos(ry), sy0 = Math.sin(ry);
    var x1 = x * cy0 + z * sy0, z1 = -x * sy0 + z * cy0;
    // rotate X (vertical lean)
    var cx0 = Math.cos(tiltX), sx0 = Math.sin(tiltX);
    var y1 = y * cx0 - z1 * sx0, z2 = y * sx0 + z1 * cx0;
    var fov = 2.6, scale = fov / (fov + z2);
    return { x: cx + x1 * R * scale, y: cy + y1 * R * scale, z: z2, s: scale };
  }

  function strokePath(getPt, n, depthBoost) {
    ctx.beginPath();
    var zSum = 0;
    for (var i = 0; i <= n; i++) {
      var p = getPt(i / n);
      if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
      zSum += p.z;
    }
    var zAvg = zSum / (n + 1);                     // -1 (back) .. 1 (front)
    var a = (0.10 + (zAvg + 1) / 2 * 0.42) * (depthBoost || 1);
    ctx.strokeStyle = rgba(accent, a);
    ctx.lineWidth = 0.6 + (zAvg + 1) / 2 * 0.9;
    ctx.stroke();
  }

  function drawGlobe() {
    var cx = W * 0.70, cy = H * 0.46;
    var R = Math.max(120, Math.min(W * 0.26, H * 0.42, 280));
    var TWO = Math.PI * 2, i, j;

    // meridians (longitude lines)
    var MER = 14;
    for (i = 0; i < MER; i++) {
      (function (lon) {
        strokePath(function (u) { return project(-Math.PI / 2 + u * Math.PI, lon, cx, cy, R); }, 26);
      })((i / MER) * TWO);
    }
    // parallels (latitude rings)
    var PAR = 7;
    for (j = 1; j < PAR; j++) {
      (function (lat) {
        strokePath(function (u) { return project(lat, u * TWO, cx, cy, R); }, 48);
      })(-Math.PI / 2 + (j / PAR) * Math.PI);
    }

    // a few orbiting nodes + a warm core point (the "live" accent)
    for (i = 0; i < 5; i++) {
      var lon = spin * 1.6 + i * (TWO / 5);
      var lat = Math.sin(t * 0.5 + i) * 0.5;
      var p = project(lat, lon, cx, cy, R * 1.04);
      var fade = (p.z + 1) / 2;
      ctx.beginPath(); ctx.arc(p.x, p.y, 1.6 + fade * 2.2, 0, TWO);
      ctx.fillStyle = rgba(i === 0 ? warm : accent, 0.25 + fade * 0.6); ctx.fill();
    }
  }

  function frame() {
    ctx.clearRect(0, 0, W, H);
    if (!reduce) {
      spin += 0.0032;
      tiltX += (tgtX - tiltX) * 0.05;
      tiltY += (tgtY - tiltY) * 0.05;
      t += 0.016;
    }
    drawGlobe();
    if (!reduce) raf = requestAnimationFrame(frame);
  }

  function start() { if (raf == null && !reduce) raf = requestAnimationFrame(frame); }
  function stop() { if (raf != null) { cancelAnimationFrame(raf); raf = null; } }
  function syncRun() { if (home && home.classList.contains('active') && !document.hidden) start(); else stop(); }

  window.addEventListener('resize', function () { resize(); if (reduce) frame(); });
  var pointerTarget = home || canvas;
  pointerTarget.addEventListener('pointermove', function (e) {
    var rect = canvas.getBoundingClientRect();
    var nx = (e.clientX - rect.left) / Math.max(1, rect.width) - 0.5;
    var ny = (e.clientY - rect.top) / Math.max(1, rect.height) - 0.5;
    tgtY = nx * 0.9;            // lean horizontally toward cursor
    tgtX = -0.35 - ny * 0.7;    // lean vertically toward cursor
  });
  pointerTarget.addEventListener('pointerleave', function () { tgtX = -0.35; tgtY = 0; });
  document.addEventListener('visibilitychange', syncRun);
  if (home) new MutationObserver(syncRun).observe(home, { attributes: true, attributeFilter: ['class'] });

  function boot() { resize(); if (reduce) frame(); else syncRun(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
