/* ═══════════════════════════════════════════════
   KYM — site chat assistant
   Layer 1: built-in FAQ answers (instant, free)
   Layer 2: Claude AI via chat.php (when enabled)
═══════════════════════════════════════════════ */
(function initChatWidget() {
  'use strict';

  var EMAIL = 'andyding09@gmail.com';
  var HISTORY_KEY = 'asd-chat-history';
  var aiAvailable = false;

  /* ─────────────────────────────────────────────
     FAQ knowledge base — keyword scoring
  ───────────────────────────────────────────── */
  var FAQ = [
    {
      kw: { 'kymarion': 3, 'asv': 3, 'boat': 2, 'surface vehicle': 3, 'autonomous': 2, 'ardupilot': 3 },
      a: 'Project Kymarion is Andy\'s ISEF research project — a low-cost autonomous boat he\'s co-developing with his partner Ethan Zhang to map microplastic pollution along the Massachusetts coast. It runs GPS waypoint missions on ArduPilot with a Raspberry Pi, and the whole build costs under $400! 🚤 There\'s a full page about it under the Research tab.'
    },
    {
      kw: { 'luminabone': 3, 'endoscope': 3, 'bone': 2, 'medical imaging': 3, 'surgery': 2, 'photometric': 3 },
      a: 'LuminaBone is Andy\'s medical imaging project (Summer 2026 internship): a 6 mm endoscope that uses near-light photometric stereo — two tiny off-axis LEDs — to build real-time 3D maps of bone surfaces for orthopedic surgery, without dye or expensive stereo cameras. 🔬'
    },
    {
      kw: { 'microplastic': 2, 'microplastics': 2, 'pollution': 2, 'plastic': 2, 'environment': 1 },
      a: 'Microplastics are tiny plastic fragments that build up in coastal waters — and figuring out WHERE they concentrate is an open problem. Andy\'s hypothesis is that they pile up where opposing currents converge. If that\'s predictable, cleanup efforts can target the right spots. That\'s exactly what Project Kymarion is testing! 🌊'
    },
    {
      kw: { 'who is andy': 3, 'about andy': 3, 'whos andy': 3, 'tell me about andy': 3, 'introduce': 2 },
      a: 'Andy is a 10th grader at Weston High School in Massachusetts (Class of 2028) who plans to major in environmental engineering. He builds autonomous robots that study the ocean, captains an FTC robotics team, swims competitively, and competes in DECA and debate. Check out the About tab for the full story!'
    },
    {
      kw: { 'contact': 3, 'email': 3, 'reach': 2, 'get in touch': 3, 'message him': 2, 'talk to andy': 3 },
      a: 'The best way to reach Andy is by email: ' + EMAIL + ' 📧 There are also GitHub and LinkedIn links in the About section.'
    },
    {
      kw: { 'resume': 3, 'résumé': 3, 'cv': 3 },
      a: 'You can download Andy\'s résumé as a PDF — there\'s a green Résumé button floating at the bottom of the page, or visit the Résumé tab for the full picture.'
    },
    {
      kw: { 'school': 2, 'grade': 2, 'high school': 3, 'weston': 3, 'how old': 3, 'age': 2 },
      a: 'Andy is a 10th grader (sophomore) at Weston High School in Weston, Massachusetts — Class of 2028.'
    },
    {
      kw: { 'college': 3, 'major': 3, 'university': 3, 'career': 2, 'future': 1 },
      a: 'Andy plans to major in environmental engineering — he wants to work at the intersection of robotics, hardware, and protecting the environment.'
    },
    {
      kw: { 'ftc': 3, 'robotics': 2, 'first tech': 3, 'gnce': 3, 'robot team': 3 },
      a: 'Andy captains FTC Team 26413 — they qualified for the Massachusetts State Championship, and he was a Dean\'s List Semifinalist. He\'s also founding GNCE Robotics, a nonprofit bringing robotics to more local kids. 🤖'
    },
    {
      kw: { 'swim': 3, 'swimming': 3, 'freestyle': 3, 'sports': 2, 'athlete': 2 },
      a: 'Andy swims varsity and USA Swimming club — he\'s ranked Top 30 in New England in the 50m freestyle (13–14 LCM). He also does track & field.'
    },
    {
      kw: { 'deca': 3, 'debate': 3, 'nsda': 3, 'speech': 2, 'business': 2, 'entrepreneurship': 3 },
      a: 'Andy qualified for DECA\'s International Career Development Conference (he scored 96% on a live business presentation!) and for the Massachusetts NSDA State Tournament in speech & debate. 🎤'
    },
    {
      kw: { 'ethan': 3, 'zhang': 3, 'partner': 2, 'team mate': 2, 'teammate': 2, 'collaborator': 3 },
      a: 'Andy co-develops Project Kymarion with his research partner Ethan Zhang — there\'s a link to Ethan\'s research site in the About section.'
    },
    {
      kw: { 'blog': 3, 'comment': 2, 'post': 2, 'field log': 3, 'journal': 2 },
      a: 'Andy writes a blog right here on the site — field notes about Project Kymarion and what he\'s learning. Head to the Blog tab, and feel free to leave a comment; he reads every one! ✏️'
    },
    {
      kw: { 'who are you': 3, 'what are you': 3, 'are you ai': 3, 'are you a bot': 3, 'are you real': 3, 'your name': 3, 'kym': 3 },
      a: 'I\'m Kym 🌊 — the assistant for Andy\'s website (named after Project Kymarion!). Ask me anything about Andy, his research, or his projects.'
    },
    {
      kw: { 'isef': 3, 'science fair': 3, 'competition': 2 },
      a: 'ISEF is the International Science and Engineering Fair — the world\'s biggest pre-college science competition. Project Kymarion is Andy\'s ISEF project, running Summer 2026 through Summer 2027.'
    },
    {
      kw: { 'hobbies': 3, 'interests': 3, 'free time': 3, 'fun': 1, 'outside': 1 },
      a: 'Outside the lab, Andy swims, runs track, competes in DECA and debate, captains his robotics team, and writes about science for everyday readers. The Interests tab has the full list!'
    },
    {
      kw: { 'website': 2, 'this site': 2, 'built this': 3, 'made this': 3, 'site made': 3 },
      a: 'This is Andy\'s personal site — hand-built with plain HTML, CSS, and JavaScript (no frameworks!), with a little help from Claude. It has his research, blog, résumé, and more.'
    }
  ];

  var SHORT_PATTERNS = [
    { re: /^(hi|hii+|hello|hey|heyo|yo|sup|howdy|good (morning|afternoon|evening))\b/i, a: 'Hi there! 👋 I\'m Kym, the assistant for Andy\'s site. Ask me anything about Andy, Project Kymarion, or his research — or tap one of the questions below.' },
    { re: /^(thanks|thank you|thx|ty|appreciate)/i, a: 'You\'re welcome! Anything else you\'d like to know about Andy or his work? 🌊' },
    { re: /^(bye|goodbye|see ya|cya|later|gtg)/i, a: 'See you around! Thanks for visiting Andy\'s site. 👋' }
  ];

  function escapeRegExp(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function faqAnswer(message) {
    var msg = message.toLowerCase().trim();
    for (var p = 0; p < SHORT_PATTERNS.length; p++) {
      if (SHORT_PATTERNS[p].re.test(msg) && msg.length < 40) return SHORT_PATTERNS[p].a;
    }
    var best = null, bestScore = 0;
    for (var i = 0; i < FAQ.length; i++) {
      var score = 0;
      for (var kw in FAQ[i].kw) {
        var re = new RegExp('\\b' + escapeRegExp(kw) + '\\b', 'i');
        if (re.test(msg)) score += FAQ[i].kw[kw];
      }
      if (score > bestScore) { bestScore = score; best = FAQ[i]; }
    }
    return bestScore >= 3 ? best.a : null;
  }

  var FALLBACK =
    'Hmm, I\'m not sure about that one! I\'m best at questions about Andy, Project Kymarion, and his other work — try one of the suggestions below, or email Andy directly at ' + EMAIL + ' 📧';

  /* ─────────────────────────────────────────────
     Widget DOM
  ───────────────────────────────────────────── */
  var root = document.createElement('div');
  root.className = 'chat-widget';
  root.innerHTML =
    '<button class="chat-fab" id="chat-fab" aria-label="Chat with Kym, the site assistant">💬</button>' +
    '<div class="chat-panel hidden" id="chat-panel" role="dialog" aria-label="Site assistant chat">' +
      '<div class="chat-header">' +
        '<div>' +
          '<div class="chat-title">Kym 🌊</div>' +
          '<div class="chat-sub" id="chat-sub">Andy’s site assistant</div>' +
        '</div>' +
        '<div class="chat-header-btns">' +
          '<button class="chat-icon-btn" id="chat-clear" title="Start over" aria-label="Clear conversation">🗑</button>' +
          '<button class="chat-icon-btn" id="chat-close" title="Close" aria-label="Close chat">✕</button>' +
        '</div>' +
      '</div>' +
      '<div class="chat-messages" id="chat-messages"></div>' +
      '<div class="chat-chips" id="chat-chips"></div>' +
      '<form class="chat-input-row" id="chat-form">' +
        '<input id="chat-input" type="text" maxlength="500" placeholder="Ask me about Andy or his research…" autocomplete="off" />' +
        '<button type="submit" class="chat-send" id="chat-send" aria-label="Send message">➤</button>' +
      '</form>' +
      '<div class="chat-foot">Assistant answers can make mistakes — email <a href="mailto:' + EMAIL + '">Andy</a> for anything important.</div>' +
    '</div>';
  document.body.appendChild(root);

  var fab      = document.getElementById('chat-fab');
  var panel    = document.getElementById('chat-panel');
  var closeBtn = document.getElementById('chat-close');
  var clearBtn = document.getElementById('chat-clear');
  var msgsEl   = document.getElementById('chat-messages');
  var chipsEl  = document.getElementById('chat-chips');
  var form     = document.getElementById('chat-form');
  var inputEl  = document.getElementById('chat-input');
  var subEl    = document.getElementById('chat-sub');

  var CHIPS = [
    'What is Project Kymarion?',
    'Who is Andy?',
    'What’s LuminaBone?',
    'How can I contact Andy?'
  ];

  var WELCOME = 'Hi! I’m Kym, the assistant for Andy’s site. Ask me anything about Andy, Project Kymarion, or his research — or tap a question below. 👋';

  /* ─────────────────────────────────────────────
     State & rendering
  ───────────────────────────────────────────── */
  var history = [];
  try {
    var saved = JSON.parse(sessionStorage.getItem(HISTORY_KEY) || '[]');
    if (Array.isArray(saved)) history = saved;
  } catch (e) { /* fresh start */ }

  function saveHistory() {
    try { sessionStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(-20))); } catch (e) {}
  }

  function bubble(role, text) {
    var el = document.createElement('div');
    el.className = 'chat-msg ' + (role === 'user' ? 'user' : 'bot');
    el.textContent = text; // textContent keeps user/AI output safely escaped
    msgsEl.appendChild(el);
    msgsEl.scrollTop = msgsEl.scrollHeight;
    return el;
  }

  function showTyping() {
    var el = document.createElement('div');
    el.className = 'chat-msg bot chat-typing';
    el.innerHTML = '<span></span><span></span><span></span>';
    msgsEl.appendChild(el);
    msgsEl.scrollTop = msgsEl.scrollHeight;
    return el;
  }

  function renderChips() {
    chipsEl.innerHTML = '';
    CHIPS.forEach(function (q) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'chat-chip';
      b.textContent = q;
      b.addEventListener('click', function () { send(q); });
      chipsEl.appendChild(b);
    });
  }

  function renderHistory() {
    msgsEl.innerHTML = '';
    bubble('bot', WELCOME);
    history.forEach(function (m) { bubble(m.role === 'user' ? 'user' : 'bot', m.content); });
  }

  /* ─────────────────────────────────────────────
     Answering
  ───────────────────────────────────────────── */
  var busy = false;

  function reply(text) {
    history.push({ role: 'assistant', content: text });
    saveHistory();
    bubble('bot', text);
  }

  function send(message) {
    message = (message || '').trim();
    if (!message || busy) return;
    busy = true;
    chipsEl.classList.add('hidden');
    inputEl.value = '';

    history.push({ role: 'user', content: message });
    saveHistory();
    bubble('user', message);

    var typing = showTyping();
    var faq = faqAnswer(message);

    if (faq) {
      // Instant local answer — tiny delay so it feels natural
      setTimeout(function () {
        typing.remove();
        reply(faq);
        busy = false;
      }, 500 + Math.random() * 400);
      return;
    }

    if (!aiAvailable) {
      setTimeout(function () {
        typing.remove();
        reply(FALLBACK);
        chipsEl.classList.remove('hidden');
        busy = false;
      }, 450);
      return;
    }

    fetch('chat.php', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: history.slice(-8) })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        typing.remove();
        if (res.ok && res.data.reply) {
          reply(res.data.reply);
        } else {
          reply(res.data.error || FALLBACK);
        }
      })
      .catch(function () {
        typing.remove();
        reply('I lost my connection for a second — try that again!');
      })
      .finally(function () { busy = false; });
  }

  /* ─────────────────────────────────────────────
     Wiring
  ───────────────────────────────────────────── */
  function openPanel() {
    panel.classList.remove('hidden');
    fab.classList.add('open');
    fab.textContent = '✕';
    renderHistory();
    if (!history.length) renderChips();
    else chipsEl.classList.add('hidden');
    setTimeout(function () { inputEl.focus(); }, 150);
  }
  function closePanel() {
    panel.classList.add('hidden');
    fab.classList.remove('open');
    fab.textContent = '💬';
  }

  fab.addEventListener('click', function () {
    if (panel.classList.contains('hidden')) openPanel();
    else closePanel();
  });
  closeBtn.addEventListener('click', closePanel);

  clearBtn.addEventListener('click', function () {
    history = [];
    saveHistory();
    renderHistory();
    renderChips();
    chipsEl.classList.remove('hidden');
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    send(inputEl.value);
  });

  renderChips();

  /* Check whether the AI layer is enabled */
  if (location.protocol !== 'file:') {
    fetch('chat.php')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        aiAvailable = !!(d && d.ai);
        subEl.textContent = aiAvailable ? 'Andy’s site assistant · AI online' : 'Andy’s site assistant';
      })
      .catch(function () { aiAvailable = false; });
  }
})();
