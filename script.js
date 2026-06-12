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

  /* ── Wire up ── */
  var openPost = function () { showSection('post'); };
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
   COMMENTS — stored server-side via comments.php
═══════════════════════════════════════════════ */
(function initComments() {
  var list = document.getElementById('comments-list');
  if (!list) return; // not on this page

  var form      = document.getElementById('comment-form');
  var nameInput = document.getElementById('comment-name');
  var textInput = document.getElementById('comment-text');
  var honeypot  = document.getElementById('comment-website');
  var charCount = document.getElementById('char-count');
  var countEl   = document.getElementById('comments-count');
  var statusEl  = document.getElementById('comment-status');
  var submitBtn = document.getElementById('comment-submit');

  var NAME_KEY = 'asd-comment-name';
  nameInput.value = localStorage.getItem(NAME_KEY) || '';

  function setStatus(msg, kind) {
    statusEl.textContent = msg;
    statusEl.className = 'comment-status' + (kind ? ' ' + kind : '');
  }

  function fmtTime(seconds) {
    var diff = Math.floor(Date.now() / 1000) - seconds;
    if (diff < 60)     return 'just now';
    if (diff < 3600)   return Math.floor(diff / 60) + ' min ago';
    if (diff < 86400)  return Math.floor(diff / 3600) + ' hr ago';
    if (diff < 604800) return Math.floor(diff / 86400) + ' day' + (diff < 172800 ? '' : 's') + ' ago';
    return new Date(seconds * 1000).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  }

  function commentEl(c) {
    var el   = document.createElement('div');
    el.className = 'comment';
    var head = document.createElement('div');
    head.className = 'comment-head';
    var name = document.createElement('span');
    name.className = 'comment-name';
    name.textContent = c.name; // textContent keeps user input safely escaped
    var time = document.createElement('span');
    time.className = 'comment-time';
    time.textContent = fmtTime(c.time);
    head.appendChild(name);
    head.appendChild(time);
    var body = document.createElement('p');
    body.className = 'comment-body';
    body.textContent = c.text;
    el.appendChild(head);
    el.appendChild(body);
    return el;
  }

  function render(comments) {
    list.innerHTML = '';
    countEl.textContent = comments.length ? '(' + comments.length + ')' : '';
    if (!comments.length) {
      var empty = document.createElement('p');
      empty.className = 'comments-empty';
      empty.textContent = 'No comments yet \u2014 be the first!';
      list.appendChild(empty);
      return;
    }
    var i;
    for (i = 0; i < comments.length; i++) {
      list.appendChild(commentEl(comments[i]));
    }
  }

  function loadComments() {
    fetch('comments.php')
      .then(function(r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function(data) { render(data.comments || []); })
      .catch(function() {
        render([]);
        list.innerHTML = '';
        if (location.protocol === 'file:') {
          setStatus('\U0001f4ac Comments work on the live site (they need the server).', '');
          form.classList.add('hidden');
        } else {
          setStatus('\u26a0 Comments couldn\'t load \u2014 try refreshing.', 'err');
        }
      });
  }

  textInput.addEventListener('input', function() {
    charCount.textContent = textInput.value.length + ' / 1500';
  });

  form.addEventListener('submit', function(e) {
    e.preventDefault();
    var text = textInput.value.trim();
    if (!text) return;

    submitBtn.disabled = true;
    submitBtn.textContent = 'Posting\u2026';
    setStatus('', '');
    localStorage.setItem(NAME_KEY, nameInput.value.trim());

    fetch('comments.php', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: nameInput.value.trim(),
        text: text,
        website: honeypot.value
      })
    })
      .then(function(r) { return r.json().then(function(data) { return { ok: r.ok, data: data }; }); })
      .then(function(result) {
        if (!result.ok) throw new Error(result.data.error || 'Something went wrong');
        textInput.value = '';
        charCount.textContent = '0 / 1500';
        setStatus('\u2713 Comment posted \u2014 thanks!', 'ok');
        loadComments();
      })
      .catch(function(err) {
        setStatus('\u26a0 ' + (err.message || 'Could not post your comment \u2014 try again.'), 'err');
      })
      .finally(function() {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Post comment';
      });
  });

  loadComments();
})();
