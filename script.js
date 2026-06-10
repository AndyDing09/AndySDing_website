/* ═══════════════════════════════════════════════
   ANDY S. DING — PERSONAL WEBSITE SCRIPTS
═══════════════════════════════════════════════ */

/* ── Section navigation ── */
(function initNav() {
  const sections = document.querySelectorAll('.section');
  const navLinks = document.querySelectorAll('.nav-link, .drawer-link, .btn[data-section], .nav-logo');

  window.showSection = function (id) {
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
    const hash = window.location.hash.replace('#', '');
    if (hash && document.getElementById(hash)) showSection(hash);
    else showSection('home');
  }
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
if (hamburger) {
  hamburger.addEventListener('click', () => {
    const isOpen = mobileDrawer.classList.toggle('open');
    hamburger.classList.toggle('open', isOpen);
    drawerOverlay.classList.toggle('visible', isOpen);
  });
  drawerOverlay.addEventListener('click', closeMobileDrawer);
}

/* ═══════════════════════════════════════════════
   BLOG — card preview built from the static post
═══════════════════════════════════════════════ */
(function initBlogCard() {
  const body = document.getElementById('post-body');
  const card = document.getElementById('blog-card');
  if (!body || !card) return; // not on this page

  const text  = (body.textContent || '').trim();
  const words = text ? text.split(/\s+/).length : 0;
  const mins  = Math.max(1, Math.round(words / 200));

  document.getElementById('card-title').textContent   = document.getElementById('post-title').textContent;
  document.getElementById('card-date').textContent    = document.getElementById('post-date').textContent;
  document.getElementById('card-excerpt').textContent = text.length > 200 ? text.slice(0, 200).trimEnd() + '…' : text;
  document.getElementById('card-readtime').textContent = '🕐 ' + mins + ' min read';
  document.getElementById('post-stats').textContent    = mins + ' min read';

  const openPost = () => showSection('post');
  document.getElementById('card-open').addEventListener('click', openPost);
  card.addEventListener('click', e => {
    if (!e.target.closest('button')) openPost();
  });
  document.getElementById('post-back').addEventListener('click', () => showSection('blog'));
})();

/* ═══════════════════════════════════════════════
   COMMENTS — stored server-side via comments.php
═══════════════════════════════════════════════ */
(function initComments() {
  const list = document.getElementById('comments-list');
  if (!list) return; // not on this page

  const form      = document.getElementById('comment-form');
  const nameInput = document.getElementById('comment-name');
  const textInput = document.getElementById('comment-text');
  const honeypot  = document.getElementById('comment-website');
  const charCount = document.getElementById('char-count');
  const countEl   = document.getElementById('comments-count');
  const statusEl  = document.getElementById('comment-status');
  const submitBtn = document.getElementById('comment-submit');

  const NAME_KEY = 'asd-comment-name';
  nameInput.value = localStorage.getItem(NAME_KEY) || '';

  function setStatus(msg, kind) {
    statusEl.textContent = msg;
    statusEl.className = 'comment-status' + (kind ? ' ' + kind : '');
  }

  function fmtTime(seconds) {
    const diff = Math.floor(Date.now() / 1000) - seconds;
    if (diff < 60)     return 'just now';
    if (diff < 3600)   return Math.floor(diff / 60) + ' min ago';
    if (diff < 86400)  return Math.floor(diff / 3600) + ' hr ago';
    if (diff < 604800) return Math.floor(diff / 86400) + ' day' + (diff < 172800 ? '' : 's') + ' ago';
    return new Date(seconds * 1000).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  }

  function commentEl(c) {
    const el   = document.createElement('div');
    el.className = 'comment';
    const head = document.createElement('div');
    head.className = 'comment-head';
    const name = document.createElement('span');
    name.className = 'comment-name';
    name.textContent = c.name; // textContent keeps user input safely escaped
    const time = document.createElement('span');
    time.className = 'comment-time';
    time.textContent = fmtTime(c.time);
    head.append(name, time);
    const body = document.createElement('p');
    body.className = 'comment-body';
    body.textContent = c.text;
    el.append(head, body);
    return el;
  }

  function render(comments) {
    list.innerHTML = '';
    countEl.textContent = comments.length ? '(' + comments.length + ')' : '';
    if (!comments.length) {
      const empty = document.createElement('p');
      empty.className = 'comments-empty';
      empty.textContent = 'No comments yet — be the first!';
      list.appendChild(empty);
      return;
    }
    comments.forEach(c => list.appendChild(commentEl(c)));
  }

  function loadComments() {
    fetch('comments.php')
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(data => render(data.comments || []))
      .catch(() => {
        render([]);
        list.innerHTML = '';
        if (location.protocol === 'file:') {
          setStatus('💬 Comments work on the live site (they need the server).', '');
          form.classList.add('hidden');
        } else {
          setStatus('⚠ Comments couldn\'t load — try refreshing.', 'err');
        }
      });
  }

  textInput.addEventListener('input', () => {
    charCount.textContent = textInput.value.length + ' / 1500';
  });

  form.addEventListener('submit', e => {
    e.preventDefault();
    const text = textInput.value.trim();
    if (!text) return;

    submitBtn.disabled = true;
    submitBtn.textContent = 'Posting…';
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
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) throw new Error(data.error || 'Something went wrong');
        textInput.value = '';
        charCount.textContent = '0 / 1500';
        setStatus('✓ Comment posted — thanks!', 'ok');
        loadComments();
      })
      .catch(err => {
        setStatus('⚠ ' + (err.message || 'Could not post your comment — try again.'), 'err');
      })
      .finally(() => {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Post comment';
      });
  });

  loadComments();
})();
