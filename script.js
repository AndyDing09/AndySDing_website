/* ═══════════════════════════════════════════════
   ANDY S. DING — PERSONAL WEBSITE SCRIPTS
═══════════════════════════════════════════════ */

/* ── Section navigation ── */
(function initNav() {
  const sections = document.querySelectorAll('.section');
  const navLinks = document.querySelectorAll('.nav-link, .drawer-link, .btn[data-section], .nav-logo');

  const TITLES = {
    home:      'Andy S. Ding — Aspiring Environmental Engineer',
    about:     'About — Andy S. Ding',
    blog:      'Blog — Andy S. Ding',
    post:      'Blog — Andy S. Ding',
    research:  'Research — Andy S. Ding',
    resume:    'Résumé — Andy S. Ding',
    interests: 'Interests — Andy S. Ding'
  };

  window.showSection = function (id, push) {
    sections.forEach(s => s.classList.remove('active'));
    const target = document.getElementById(id);
    if (target) {
      target.classList.add('active');
      window.scrollTo({ top: 0, behavior: 'instant' });
    }
    document.querySelectorAll('.nav-link, .drawer-link').forEach(l => {
      // The post view belongs to the Blog tab
      const navId = id === 'post' ? 'blog' : id;
      l.classList.toggle('active', l.dataset.section === navId);
    });
    if (TITLES[id]) document.title = TITLES[id];
    /* Keep the URL shareable and the back button working */
    if (push !== false) history.pushState({ section: id }, '', '#' + id);
  };

  navLinks.forEach(link => {
    link.addEventListener('click', e => {
      const id = link.dataset.section;
      if (id) {
        e.preventDefault();
        showSection(id);
        closeMobileDrawer();
      }
    });
  });

  if (sections.length) {
    window.addEventListener('popstate', () => {
      const id = location.hash.replace('#', '') || 'home';
      if (document.getElementById(id)) showSection(id, false);
    });
    const hash = window.location.hash.replace('#', '');
    if (hash && document.getElementById(hash)) showSection(hash, false);
    else showSection('home', false);
  }
})();

/* ── Theme toggle (dark / light) ── */
(function initTheme() {
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  const root = document.documentElement;
  function paint() {
    btn.textContent = root.dataset.theme === 'dark' ? '☀️' : '🌙';
  }
  btn.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('asd-theme', root.dataset.theme);
    paint();
  });
  paint();
})();

/* ── Scroll-reveal for cards ── */
(function initReveal() {
  const els = document.querySelectorAll(
    '.blog-card, .project-card, .papers-block, .resume-block, .interest-card, .project-section'
  );
  if (!els.length || !('IntersectionObserver' in window)) return;
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('revealed');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.08 });
  els.forEach(el => {
    el.classList.add('reveal');
    observer.observe(el);
  });
})();

/* ── Mobile hamburger / drawer ── */
const hamburger     = document.getElementById('hamburger');
const mobileDrawer  = document.getElementById('mobile-drawer');
const drawerOverlay = document.getElementById('drawer-overlay');

function closeMobileDrawer() {
  if (!hamburger) return;
  hamburger.classList.remove('open');
  mobileDrawer.classList.remove('open');
  drawerOverlay.classList.remove('visible');
}
if (hamburger && mobileDrawer && drawerOverlay) {
  hamburger.addEventListener('click', () => {
    const isOpen = mobileDrawer.classList.toggle('open');
    hamburger.classList.toggle('open', isOpen);
    drawerOverlay.classList.toggle('visible', isOpen);
  });
  drawerOverlay.addEventListener('click', closeMobileDrawer);
}

/* ═══════════════════════════════════════════════
   BLOG — published post loaded from blog.php
   (Andy edits it from the private dev page;
   the public site is read-only.)
═══════════════════════════════════════════════ */
(function initBlog() {
  if (!document.getElementById('blog-card')) return; // not on this page

  var DEFAULT_POST = {
    title: 'Welcome to my blog',
    content:
      '<p>Hi, I\'m Andy — welcome to my blog.</p>' +
      '<p>This is where I\'ll be writing about the things I\'m working on and thinking about: ' +
      'building and field-testing <strong>Project Kymarion</strong> (our autonomous boat that maps ' +
      'microplastic pollution along the Massachusetts coast), what I\'m learning in robotics and ' +
      'research, and the occasional detour into swimming, debate, or whatever else has my attention.</p>' +
      '<h2>Why a blog?</h2>' +
      '<p>Research generates a lot of stories that never make it into a paper — sensors that fail at ' +
      'the worst possible moment, deployments that almost work, small wins that feel huge. I want to ' +
      'document those while they\'re fresh, and hopefully make ocean research feel a little more ' +
      'accessible along the way.</p>' +
      '<blockquote>First real field log coming soon. In the meantime, say hi in the comments below — ' +
      'I read every one.</blockquote>',
    updated: null
  };

  /* ── Elements ── */
  var cardDate     = document.getElementById('card-date');
  var cardTitle    = document.getElementById('card-title');
  var cardExcerpt  = document.getElementById('card-excerpt');
  var cardReadtime = document.getElementById('card-readtime');
  var cardOpen     = document.getElementById('card-open');

  var postBack     = document.getElementById('post-back');
  var postTitle    = document.getElementById('post-title');
  var postDate     = document.getElementById('post-date');
  var postStats    = document.getElementById('post-stats');
  var postBody     = document.getElementById('post-body');
  var cardViews    = document.getElementById('card-views');
  var postViews    = document.getElementById('post-views');

  /* ── Helpers ── */
  function textOf(html) {
    var div = document.createElement('div');
    div.innerHTML = html;
    return (div.textContent || '').trim();
  }
  function readTime(text) {
    var words = text ? text.split(/\s+/).length : 0;
    return Math.max(1, Math.round(words / 200));
  }
  function fmtDate(ms) {
    return new Date(ms).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
  }

  /* ── Render the post + its card preview ── */
  function render(post) {
    var text = textOf(post.content);
    var mins = readTime(text);
    var dateText = post.updated ? fmtDate(post.updated) : fmtDate(Date.now());

    cardTitle.textContent = post.title;
    cardExcerpt.textContent = text.length > 200 ? text.slice(0, 200).trimEnd() + '…' : text;
    cardDate.textContent = dateText;
    cardReadtime.textContent = '🕐 ' + mins + ' min read';

    postTitle.textContent = post.title;
    postBody.innerHTML = post.content; // trusted: authored by Andy, sanitized server-side
    postDate.textContent = dateText;
    postStats.textContent = mins + ' min read';
  }

  render(DEFAULT_POST);

  /* Load the published post from the server */
  if (location.protocol !== 'file:') {
    fetch('blog.php')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.title && d.content) {
          render({ title: d.title, content: d.content, updated: d.updated ? d.updated * 1000 : null });
        }
      })
      .catch(function () { /* keep the default post */ });
  }

  /* ── View count ── */
  function paintViews(n) {
    var txt = '👁 ' + (n === 1 ? '1 view' : n + ' views');
    if (cardViews) cardViews.textContent = txt;
    if (postViews) postViews.textContent = txt;
  }

  if (location.protocol !== 'file:') {
    fetch('views.php')
      .then(function(r) { return r.json(); })
      .then(function(d) { if (typeof d.views === 'number') paintViews(d.views); })
      .catch(function() {});
  }

  /* ── Wire up ── */
  var openPost = function () {
    showSection('post');
    if (location.protocol !== 'file:' && !sessionStorage.getItem('asd-viewed-post-1')) {
      sessionStorage.setItem('asd-viewed-post-1', '1');
      fetch('views.php', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'view'})
      })
        .then(function(r) { return r.json(); })
        .then(function(d) { if (typeof d.views === 'number') paintViews(d.views); })
        .catch(function() {});
    }
  };
  cardOpen.addEventListener('click', openPost);
  document.getElementById('blog-card').addEventListener('click', function (e) {
    if (e.target.closest('button')) return;
    openPost();
  });
  postBack.addEventListener('click', function () { showSection('blog'); });
})();

/* ═══════════════════════════════════════════════
   LIKE + SHARE — likes stored server-side
═══════════════════════════════════════════════ */
(function initEngage() {
  const likeBtn = document.getElementById('like-btn');
  const shareBtn = document.getElementById('share-btn');
  if (!likeBtn) return;

  const LIKED_KEY = 'asd-liked-post-1';
  let liked = localStorage.getItem(LIKED_KEY) === '1';
  let count = null;

  function paint() {
    likeBtn.innerHTML = (liked ? '❤️' : '🤍') + ' <span id="like-count">' + (count === null ? '' : count) + '</span>';
    likeBtn.classList.toggle('liked', liked);
    likeBtn.setAttribute('aria-pressed', liked ? 'true' : 'false');
  }

  fetch('likes.php')
    .then(r => { if (!r.ok) throw new Error(); return r.json(); })
    .then(d => { count = d.likes || 0; paint(); })
    .catch(() => { likeBtn.style.display = 'none'; });

  likeBtn.addEventListener('click', () => {
    liked = !liked;
    localStorage.setItem(LIKED_KEY, liked ? '1' : '0');
    if (count !== null) count = Math.max(0, count + (liked ? 1 : -1));
    paint(); // optimistic
    fetch('likes.php', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: liked ? 'like' : 'unlike' })
    })
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(d => { count = d.likes; paint(); })
      .catch(() => {});
  });

  if (shareBtn) {
    shareBtn.addEventListener('click', () => {
      const url = 'https://www.andysding.com/#post';
      const data = { title: document.title, url: url };
      if (navigator.share) {
        navigator.share(data).catch(() => {});
      } else {
        navigator.clipboard.writeText(url).then(() => {
          const original = shareBtn.innerHTML;
          shareBtn.innerHTML = '✓ Link copied';
          setTimeout(() => { shareBtn.innerHTML = original; }, 1800);
        });
      }
    });
  }

  paint();
})();

/* ═══════════════════════════════════════════════
   COMMENTS v3 — Reddit-style: columns, avatars,
   thread lines, collapse, sort by top/new
════════════════════════════════════════════════ */
(function initComments() {
  var list      = document.getElementById('comments-list');
  if (!list) return;

  var form      = document.getElementById('comment-form');
  var nameInput = document.getElementById('comment-name');
  var textInput = document.getElementById('comment-text');
  var honeypot  = document.getElementById('comment-website');
  var charCount = document.getElementById('char-count');
  var countEl   = document.getElementById('comments-count');
  var statusEl  = document.getElementById('comment-status');
  var submitBtn = document.getElementById('comment-submit');

  var NAME_KEY  = 'asd-comment-name';
  var VOTES_KEY = 'asd-comment-votes';
  var currentSort = 'top';

  nameInput.value = localStorage.getItem(NAME_KEY) || '';

  document.querySelectorAll('.sort-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      document.querySelectorAll('.sort-btn').forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      currentSort = btn.dataset.sort;
      loadComments();
    });
  });

  function getLocalVotes() {
    try { return JSON.parse(localStorage.getItem(VOTES_KEY) || '{}'); } catch(e) { return {}; }
  }
  function setLocalVote(id, dir) {
    var v = getLocalVotes();
    if (dir === 0) delete v[id]; else v[id] = dir;
    localStorage.setItem(VOTES_KEY, JSON.stringify(v));
  }
  function setStatus(msg, kind) {
    statusEl.textContent = msg;
    statusEl.className = 'comment-status' + (kind ? ' ' + kind : '');
  }
  function fmtTime(seconds) {
    var d = new Date(seconds * 1000);
    var diff = Math.floor(Date.now() / 1000) - seconds;
    var abs = d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
    if (diff < 60)     return 'just now';
    if (diff < 3600)   return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400)  return Math.floor(diff / 3600) + 'h ago';
    if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
    return abs;
  }
  function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
  var AVATAR_COLORS = ['#2e6b4e','#b85c38','#5b7fa6','#7a5c8a','#8a7a2e','#3a7a6e'];
  function avatarColor(name) {
    var h = 0, i;
    for (i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) | 0;
    return AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length];
  }
  function makeIcon(path) {
    return '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + path + '"/></svg>';
  }

  function commentEl(c, depth) {
    depth = depth || 0;
    var myVote = getLocalVotes()[c.id] || 0;

    var wrap = document.createElement('div');
    wrap.className = 'comment';
    wrap.id = 'comment-' + c.id;
    wrap.dataset.id = c.id;

    /* vote column */
    var voteCol = document.createElement('div');
    voteCol.className = 'comment-vote-col';

    var upBtn = document.createElement('button');
    upBtn.type = 'button';
    upBtn.className = 'vote-btn vote-up' + (myVote === 1 ? ' active' : '');
    upBtn.setAttribute('aria-label', 'Upvote');
    upBtn.innerHTML = makeIcon('M8 3l5 5H3l5-5z');

    var score = document.createElement('span');
    score.className = 'vote-score' + (c.votes > 0 ? ' pos' : c.votes < 0 ? ' neg' : '');
    score.textContent = c.votes;

    var downBtn = document.createElement('button');
    downBtn.type = 'button';
    downBtn.className = 'vote-btn vote-down' + (myVote === -1 ? ' active' : '');
    downBtn.setAttribute('aria-label', 'Downvote');
    downBtn.innerHTML = makeIcon('M8 13l5-5H3l5 5z');

    voteCol.appendChild(upBtn);
    voteCol.appendChild(score);
    voteCol.appendChild(downBtn);

    /* body column */
    var bodyCol = document.createElement('div');
    bodyCol.className = 'comment-body-col';

    var head = document.createElement('div');
    head.className = 'comment-head';

    var avatar = document.createElement('span');
    avatar.className = 'comment-avatar';
    avatar.style.background = avatarColor(c.name);
    avatar.textContent = (c.name || 'A').charAt(0);

    var name = document.createElement('span');
    name.className = 'comment-name';
    name.textContent = c.name;

    var time = document.createElement('span');
    time.className = 'comment-time';
    time.title = new Date(c.time * 1000).toLocaleString();
    time.textContent = fmtTime(c.time);

    var collapseBtn = document.createElement('button');
    collapseBtn.className = 'collapse-btn';
    collapseBtn.setAttribute('aria-label', 'Collapse thread');
    collapseBtn.innerHTML = makeIcon('M4 6l4 4 4-4') + ' [&#8211;]';

    head.appendChild(avatar);
    head.appendChild(name);
    if (c.name.toLowerCase().indexOf('andy') !== -1 || c.name.toLowerCase().indexOf('ding') !== -1) {
      var flair = document.createElement('span');
      flair.className = 'comment-flair';
      flair.textContent = 'OP';
      head.appendChild(flair);
    }
    head.appendChild(time);
    head.appendChild(collapseBtn);

    var text = document.createElement('p');
    text.className = 'comment-text';
    text.textContent = c.text;

    /* actions */
    var actions = document.createElement('div');
    actions.className = 'comment-actions';

    var replyBtn = document.createElement('button');
    replyBtn.type = 'button';
    replyBtn.className = 'action-btn reply-btn';
    replyBtn.setAttribute('aria-label', 'Reply to ' + escHtml(c.name));
    replyBtn.innerHTML = makeIcon('M2 8s2-4 6-4 6 2 6 4-2 4-6 4c-1 0-2-.2-3-.6L2 14V8z') + ' Reply';

    var shareBtn2 = document.createElement('button');
    shareBtn2.type = 'button';
    shareBtn2.className = 'action-btn';
    shareBtn2.innerHTML = makeIcon('M10 3H6a2 2 0 00-2 2v8a2 2 0 002 2h4') + ' Share';

    actions.appendChild(replyBtn);
    actions.appendChild(shareBtn2);

    var replyFormWrap = document.createElement('div');
    replyFormWrap.className = 'reply-form-wrap hidden';
    replyFormWrap.innerHTML =
      '<form class="comment-form comment-form-reply">' +
        '<input type="text" class="reply-name" maxlength="60" placeholder="Your name (optional)" autocomplete="name" />' +
        '<textarea class="reply-text" maxlength="1500" placeholder="Replying to ' + escHtml(c.name) + '\u2026" required></textarea>' +
        '<div class="comment-form-foot">' +
          '<span class="char-count reply-char-count">0 / 1500</span>' +
          '<div style="display:flex;gap:8px">' +
            '<button type="button" class="btn btn-small btn-ghost reply-cancel">Cancel</button>' +
            '<button type="submit" class="btn btn-primary btn-small reply-submit">Post reply</button>' +
          '</div>' +
        '</div>' +
      '</form>';

    var children = document.createElement('div');
    children.className = 'comment-children';

    bodyCol.appendChild(head);
    bodyCol.appendChild(text);
    bodyCol.appendChild(actions);
    bodyCol.appendChild(replyFormWrap);
    bodyCol.appendChild(children);
    wrap.appendChild(voteCol);
    wrap.appendChild(bodyCol);

    /* collapse */
    collapseBtn.addEventListener('click', function() {
      wrap.classList.toggle('collapsed');
      collapseBtn.innerHTML = wrap.classList.contains('collapsed')
        ? makeIcon('M4 10l4-4 4 4') + ' [+]'
        : makeIcon('M4 6l4 4 4-4') + ' [&#8211;]';
    });

    /* share */
    shareBtn2.addEventListener('click', function() {
      var url = window.location.href.split('#')[0] + '#comment-' + c.id;
      if (navigator.clipboard) {
        navigator.clipboard.writeText(url).then(function() {
          shareBtn2.innerHTML = makeIcon('M5 8l4 4 6-6') + ' Copied!';
          setTimeout(function() { shareBtn2.innerHTML = makeIcon('M10 3H6a2 2 0 00-2 2v8a2 2 0 002 2h4') + ' Share'; }, 1800);
        });
      }
    });

    /* votes */
    function handleVote(dir) {
      var current = getLocalVotes()[c.id] || 0;
      var newDir  = (current === dir) ? 0 : dir;
      c.votes += newDir - current;
      score.textContent = c.votes;
      score.className   = 'vote-score' + (c.votes > 0 ? ' pos' : c.votes < 0 ? ' neg' : '');
      upBtn.classList.toggle('active',   newDir === 1);
      downBtn.classList.toggle('active', newDir === -1);
      setLocalVote(c.id, newDir);
      if (location.protocol === 'file:') return;
      fetch('comments.php', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ action: 'vote', id: c.id, dir: dir })
      })
        .then(function(r) { return r.json(); })
        .then(function(d) {
          if (typeof d.votes === 'number') { c.votes = d.votes; score.textContent = c.votes; score.className = 'vote-score' + (c.votes > 0 ? ' pos' : c.votes < 0 ? ' neg' : ''); }
          if (typeof d.voted === 'number') { upBtn.classList.toggle('active', d.voted === 1); downBtn.classList.toggle('active', d.voted === -1); setLocalVote(c.id, d.voted); }
        }).catch(function() {});
    }
    upBtn.addEventListener('click',   function() { handleVote(1);  });
    downBtn.addEventListener('click', function() { handleVote(-1); });

    /* reply form */
    replyBtn.addEventListener('click', function() {
      replyFormWrap.classList.toggle('hidden');
      if (!replyFormWrap.classList.contains('hidden')) {
        replyFormWrap.querySelector('.reply-name').value = localStorage.getItem(NAME_KEY) || '';
        replyFormWrap.querySelector('.reply-text').focus();
      }
    });
    replyFormWrap.querySelector('.reply-cancel').addEventListener('click', function() { replyFormWrap.classList.add('hidden'); });
    replyFormWrap.querySelector('.reply-text').addEventListener('input', function() {
      replyFormWrap.querySelector('.reply-char-count').textContent = this.value.length + ' / 1500';
    });
    replyFormWrap.querySelector('form').addEventListener('submit', function(e) {
      e.preventDefault();
      var rText = replyFormWrap.querySelector('.reply-text').value.trim();
      if (!rText) return;
      var rName   = replyFormWrap.querySelector('.reply-name').value.trim();
      var rSubmit = replyFormWrap.querySelector('.reply-submit');
      rSubmit.disabled = true; rSubmit.textContent = 'Posting\u2026';
      localStorage.setItem(NAME_KEY, rName);
      fetch('comments.php', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ name: rName, text: rText, parentId: c.id, website: '' })
      })
        .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
        .then(function(res) {
          if (!res.ok) throw new Error(res.data.error || 'Something went wrong');
          replyFormWrap.classList.add('hidden');
          replyFormWrap.querySelector('.reply-text').value = '';
          replyFormWrap.querySelector('.reply-char-count').textContent = '0 / 1500';
          loadComments();
        })
        .catch(function(err) {
          var errEl = replyFormWrap.querySelector('.reply-err');
          if (!errEl) { errEl = document.createElement('p'); errEl.className = 'comment-status err reply-err'; replyFormWrap.querySelector('form').appendChild(errEl); }
          errEl.textContent = '\u26a0 ' + (err.message || 'Could not post.');
        })
        .finally(function() { rSubmit.disabled = false; rSubmit.textContent = 'Post reply'; });
    });

    return { wrap: wrap, children: children };
  }

  function render(allComments) {
    list.innerHTML = '';
    var comments = allComments.filter(function(c) { return !!c.id; });
    var total = comments.length;
    countEl.textContent = total ? String(total) : '';

    if (!total) {
      var empty = document.createElement('p');
      empty.className = 'comments-empty';
      empty.textContent = '\ud83c\udf31 No comments yet \u2014 start the discussion!';
      list.appendChild(empty);
      return;
    }

    var nodes = {}, topLevel = [], i, c, built;
    for (i = 0; i < comments.length; i++) {
      c = comments[i];
      built = commentEl(c, c.parentId ? 1 : 0);
      nodes[c.id] = built;
      if (!c.parentId) topLevel.push({ node: built, data: c });
    }
    for (i = 0; i < comments.length; i++) {
      c = comments[i];
      if (c.parentId && nodes[c.parentId]) nodes[c.parentId].children.appendChild(nodes[c.id].wrap);
    }
    topLevel.sort(function(a, b) {
      if (currentSort === 'new') return b.data.time - a.data.time;
      if (b.data.votes !== a.data.votes) return b.data.votes - a.data.votes;
      return a.data.time - b.data.time;
    });
    var frag = document.createDocumentFragment();
    for (i = 0; i < topLevel.length; i++) frag.appendChild(topLevel[i].node.wrap);
    list.appendChild(frag);
  }

  function loadComments() {
    if (location.protocol === 'file:') {
      render([]);
      setStatus('💬 Comments work on the live site (they need the server).', '');
      form.classList.add('hidden');
      return;
    }
    fetch('comments.php')
      .then(function(r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function(d) { render(d.comments || []); })
      .catch(function() { render([]); setStatus('\u26a0 Comments couldn\u2019t load \u2014 try refreshing.', 'err'); });
  }

  textInput.addEventListener('input', function() { charCount.textContent = textInput.value.length + ' / 1500'; });

  form.addEventListener('submit', function(e) {
    e.preventDefault();
    var text = textInput.value.trim();
    if (!text) return;
    submitBtn.disabled = true; submitBtn.textContent = 'Posting\u2026';
    setStatus('', '');
    localStorage.setItem(NAME_KEY, nameInput.value.trim());
    fetch('comments.php', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ name: nameInput.value.trim(), text: text, parentId: '', website: honeypot.value })
    })
      .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
      .then(function(res) {
        if (!res.ok) throw new Error(res.data.error || 'Something went wrong');
        textInput.value = ''; charCount.textContent = '0 / 1500';
        setStatus('\u2713 Comment posted \u2014 thanks!', 'ok');
        loadComments();
      })
      .catch(function(err) { setStatus('\u26a0 ' + (err.message || 'Could not post \u2014 try again.'), 'err'); })
      .finally(function() { submitBtn.disabled = false; submitBtn.textContent = 'Post comment'; });
  });

  loadComments();
})();
