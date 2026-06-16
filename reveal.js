/* ═══════════════════════════════════════════════════════════════════════
   Editorial motion — scroll reveal + magnetic nav labels.
   Presentation-only, dependency-free. Both effects no-op under
   prefers-reduced-motion. Wrapping is done at runtime so no HTML/content
   changes are needed (the visible text is identical).
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ── Magnetic nav labels: wrap each link's text in a clip window + duplicate ── */
  function wrapMagnetic() {
    var links = document.querySelectorAll('.nav-link, .drawer-link');
    links.forEach(function (a) {
      if (a.querySelector('.nav-magnetic')) return;       // already wrapped
      var label = (a.textContent || '').trim();
      if (!label) return;
      var outer = document.createElement('span');
      outer.className = 'nav-magnetic';
      outer.setAttribute('data-text', label);
      var inner = document.createElement('span');
      inner.textContent = label;                          // identical text
      outer.appendChild(inner);
      a.textContent = '';
      a.appendChild(outer);
    });
  }

  /* ── Scroll reveal: fade + rise as elements enter view ── */
  function setupReveal() {
    if (reduce || !('IntersectionObserver' in window)) return;
    var sel = '.section-inner, .project-card, .interest-card, .blog-card, .resume-block, ' +
              '.papers-block, .project-section, .timeline-item, .hero-readout';
    var els = [].slice.call(document.querySelectorAll(sel));
    if (!els.length) return;
    els.forEach(function (el) { el.classList.add('reveal'); });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('reveal-in'); io.unobserve(e.target); }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.06 });
    els.forEach(function (el) { io.observe(el); });

    // SPA safety: when a tab/section becomes .active, reveal its items immediately
    // so content inside a previously-hidden section is never stuck invisible.
    var sections = document.querySelectorAll('.section');
    if (sections.length) {
      var mo = new MutationObserver(function (muts) {
        muts.forEach(function (m) {
          var s = m.target;
          if (s.classList && s.classList.contains('active')) {
            s.querySelectorAll('.reveal').forEach(function (el) { el.classList.add('reveal-in'); });
          }
        });
      });
      sections.forEach(function (s) { mo.observe(s, { attributes: true, attributeFilter: ['class'] }); });
    }
    // Safety: if anything is still hidden after load (e.g. in an inactive SPA
    // tab), reveal it so content is never stuck invisible.
    window.addEventListener('load', function () {
      setTimeout(function () {
        els.forEach(function (el) {
          if (!el.classList.contains('reveal-in')) {
            var r = el.getBoundingClientRect();
            if (r.top < window.innerHeight && r.bottom > 0) el.classList.add('reveal-in');
          }
        });
      }, 400);
    });
  }

  function init() { wrapMagnetic(); setupReveal(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
