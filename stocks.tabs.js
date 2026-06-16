/* ═══════════════════════════════════════════════════════════════════════
   Stocks lab sub-tabs
   Three views inside the Stocks section: "Stock lookup" (watchlist → per-stock
   chart + analysis), "Research & trading desk" (the long morning briefing,
   scorecard, account, paper trading), and "AI research analyst" (the embedded
   equity-research agent page). Keeps the lookup view clean — clicking a stock
   shows just its chart + analysis, never the briefing.
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var stocks = document.getElementById('stocks');
  if (!stocks) return;
  var deskOpened = false;
  var researchOpened = false;

  function show(pane) {
    var panes = stocks.querySelectorAll('.sa-pane');
    if (!panes.length) return;
    panes.forEach(function (p) {
      p.classList.toggle('hidden', p.id !== 'sa-pane-' + pane);
    });
    stocks.querySelectorAll('.sa-subtab').forEach(function (b) {
      var on = b.getAttribute('data-pane') === pane;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    if (pane === 'desk' && !deskOpened) {
      deskOpened = true;
      // auto-load the (server-cached, instant) morning briefing the first time
      if (window.AndyDeskBriefingRun) setTimeout(window.AndyDeskBriefingRun, 0);
    }
    if (pane === 'research' && !researchOpened) {
      researchOpened = true;
      // load the agent page only when first opened (defers its fonts + script)
      var frame = document.getElementById('sa-research-frame');
      if (frame && !frame.src && frame.getAttribute('data-src')) {
        frame.src = frame.getAttribute('data-src');
      }
    }
    try { stocks.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (e) {}
  }

  stocks.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('.sa-subtab') : null;
    if (!b) return;
    e.preventDefault();
    show(b.getAttribute('data-pane'));
  });
})();
