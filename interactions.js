/* ═══════════════════════════════════════════════════════════════════════
   Micro-interactions — the "professional", reactive feel.
   • Magnetic buttons / nav / toggles (pull toward the cursor)
   • Subtle 3D tilt on cards + the photo
   • Hero parallax + a glow that follows the cursor
   Disabled entirely on touch devices and under prefers-reduced-motion.
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var fine = window.matchMedia && matchMedia('(pointer: fine)').matches;
  if (reduce || !fine) return;

  var MAG = '.btn, .nav-logo, #theme-toggle, .project-more, .cta-btn';
  var TILT = '.interest-card, .blog-card, .photo-frame';

  function bindMagnetic(el) {
    if (el.dataset.mag || el.closest('#stocks')) return; el.dataset.mag = '1';
    el.style.transition = 'transform 0.18s cubic-bezier(.2,.7,.3,1)';
    el.addEventListener('pointermove', function (e) {
      var r = el.getBoundingClientRect();
      var mx = e.clientX - (r.left + r.width / 2);
      var my = e.clientY - (r.top + r.height / 2);
      el.style.transform = 'translate(' + (mx * 0.22).toFixed(1) + 'px,' + (my * 0.32).toFixed(1) + 'px)';
    });
    el.addEventListener('pointerleave', function () { el.style.transform = ''; });
  }

  function bindTilt(el) {
    if (el.dataset.tilt || el.closest('#stocks')) return; el.dataset.tilt = '1';
    el.style.transition = 'transform 0.22s ease';
    el.style.transformStyle = 'preserve-3d';
    el.addEventListener('pointermove', function (e) {
      var r = el.getBoundingClientRect();
      var px = (e.clientX - r.left) / r.width - 0.5;
      var py = (e.clientY - r.top) / r.height - 0.5;
      el.style.transform = 'perspective(900px) rotateX(' + (-py * 4).toFixed(2) + 'deg) rotateY(' + (px * 5).toFixed(2) + 'deg)';
    });
    el.addEventListener('pointerleave', function () { el.style.transform = ''; });
  }

  function scan(root) {
    (root || document).querySelectorAll(MAG).forEach(bindMagnetic);
    (root || document).querySelectorAll(TILT).forEach(bindTilt);
  }

  // Hero parallax + cursor-tracking glow (CSS reads --mx/--my on #home)
  function heroParallax() {
    var home = document.getElementById('home');
    var hero = document.querySelector('.hero-container');
    if (!home) return;
    home.addEventListener('pointermove', function (e) {
      var r = home.getBoundingClientRect();
      var nx = (e.clientX - r.left) / Math.max(1, r.width);
      var ny = (e.clientY - r.top) / Math.max(1, r.height);
      home.style.setProperty('--mx', (nx * 100).toFixed(1) + '%');
      home.style.setProperty('--my', (ny * 100).toFixed(1) + '%');
      if (hero) hero.style.transform = 'translate(' + ((nx - 0.5) * -10).toFixed(1) + 'px,' + ((ny - 0.5) * -7).toFixed(1) + 'px)';
    });
    home.addEventListener('pointerleave', function () { if (hero) hero.style.transform = ''; });
    if (hero) hero.style.transition = 'transform 0.5s cubic-bezier(.2,.7,.3,1)';
  }

  function init() {
    scan(document);
    heroParallax();
    // Re-scan when a section becomes active (desk/stocks add buttons + cards lazily)
    document.querySelectorAll('.section').forEach(function (s) {
      new MutationObserver(function () { if (s.classList.contains('active')) scan(s); })
        .observe(s, { attributes: true, attributeFilter: ['class'] });
    });
    // Catch dynamically rendered desk/stock nodes
    var main = document.getElementById('main');
    if (main) {
      var deb;
      new MutationObserver(function () { clearTimeout(deb); deb = setTimeout(function () { scan(document); }, 300); })
        .observe(main, { childList: true, subtree: true });
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
