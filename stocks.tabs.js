/* ═══════════════════════════════════════════════════════════════════════
   Stocks lab sub-tabs
   Two views inside the Stocks section: "Stock lookup" (watchlist → per-stock
   chart + analysis) and "Research & trading desk" (the long morning briefing,
   scorecard, account, paper trading). Keeps the lookup view clean — clicking a
   stock shows just its chart + analysis, never the briefing.
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var stocks = document.getElementById('stocks');
  if (!stocks) return;
  var deskOpened = false;

  var warriorOpened = false;

  function show(pane) {
    // Toggle every pane by id (sa-pane-<pane>) so adding tabs needs no edits here.
    stocks.querySelectorAll('.sa-pane').forEach(function (p) {
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
    if (pane === 'warrior' && !warriorOpened) {
      warriorOpened = true;
      if (window.AndyWarriorOpen) setTimeout(window.AndyWarriorOpen, 0);
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
