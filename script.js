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
      e.preventDefault();
      const id = link.dataset.section;
      if (id) {
        showSection(id);
        closeMobileDrawer();
      }
    });
  });

  const hash = window.location.hash.replace('#', '');
  if (hash && document.getElementById(hash)) showSection(hash);
  else showSection('home');
})();

/* ── Mobile hamburger / drawer ── */
const hamburger     = document.getElementById('hamburger');
const mobileDrawer  = document.getElementById('mobile-drawer');
const drawerOverlay = document.getElementById('drawer-overlay');

function closeMobileDrawer() {
  hamburger.classList.remove('open');
  mobileDrawer.classList.remove('open');
  drawerOverlay.classList.remove('visible');
}
hamburger.addEventListener('click', () => {
  const isOpen = mobileDrawer.classList.toggle('open');
  hamburger.classList.toggle('open', isOpen);
  drawerOverlay.classList.toggle('visible', isOpen);
});
drawerOverlay.addEventListener('click', closeMobileDrawer);

/* ── Resume download button feedback ── */
const dlBtn = document.getElementById('download-btn');
if (dlBtn) {
  dlBtn.addEventListener('click', e => {
    if (dlBtn.getAttribute('href') === 'resume.pdf') {
      e.preventDefault();
      const original = dlBtn.innerHTML;
      dlBtn.innerHTML = '✓ PDF coming soon!';
      setTimeout(() => { dlBtn.innerHTML = original; }, 2200);
    }
  });
}

/* ═══════════════════════════════════════════════
   BLOG — single post with built-in editor
   Saved in this browser via localStorage.
═══════════════════════════════════════════════ */
(function initBlog() {
  const KEY = 'asd-blog-post-v1';

  const DEFAULT_POST = {
    title: 'Welcome to my blog',
    content:
      '<p>This is my little corner of the internet for writing about the environment, school, and whatever I’m curious about right now.</p>' +
      '<h2>How this page works (note to self)</h2>' +
      '<p>Hit the <strong>✏️ Edit</strong> button at the top right to start writing. While editing you can:</p>' +
      '<ul>' +
      '<li>Use the toolbar (or <strong>Ctrl+B</strong> / <strong>Ctrl+I</strong> / <strong>Ctrl+U</strong>) to format text</li>' +
      '<li>Add headings, lists, quotes, and links</li>' +
      '<li>Stop worrying about saving — it autosaves as you type</li>' +
      '<li>Click <strong>⬇ Backup</strong> now and then to download a copy of your post</li>' +
      '</ul>' +
      '<blockquote>Replace all of this with your first real post whenever you’re ready!</blockquote>',
    created: Date.now(),
    updated: null
  };

  /* ── Elements ── */
  const cardDate     = document.getElementById('card-date');
  const cardTitle    = document.getElementById('card-title');
  const cardExcerpt  = document.getElementById('card-excerpt');
  const cardReadtime = document.getElementById('card-readtime');
  const cardOpen     = document.getElementById('card-open');

  const postSection  = document.getElementById('post');
  const postBack     = document.getElementById('post-back');
  const editToggle   = document.getElementById('edit-toggle');
  const saveStatus   = document.getElementById('save-status');
  const toolbar      = document.getElementById('editor-toolbar');
  const postTitle    = document.getElementById('post-title');
  const postDate     = document.getElementById('post-date');
  const postStats    = document.getElementById('post-stats');
  const postBody     = document.getElementById('post-body');
  const editorFooter = document.getElementById('editor-footer');
  const wordCount    = document.getElementById('word-count');
  const backupBtn    = document.getElementById('backup-btn');
  const restoreInput = document.getElementById('restore-input');
  const resetBtn     = document.getElementById('reset-btn');
  const linkBtn      = document.getElementById('link-btn');

  let post = loadPost();
  let editing = false;
  let saveTimer = null;

  /* ── Storage ── */
  function loadPost() {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) {
        const p = JSON.parse(raw);
        if (p && typeof p.title === 'string' && typeof p.content === 'string') return p;
      }
    } catch (e) { /* corrupted data — fall back to default */ }
    return JSON.parse(JSON.stringify(DEFAULT_POST));
  }

  function persist() {
    post.title = postTitle.textContent.trim();
    post.content = postBody.innerHTML;
    post.updated = Date.now();
    try {
      localStorage.setItem(KEY, JSON.stringify(post));
      flashStatus('Saved ✓', true);
    } catch (e) {
      flashStatus('⚠ Could not save (storage full?)', false);
    }
    renderCard();
    renderMeta();
  }

  function scheduleSave() {
    saveStatus.textContent = 'Saving…';
    saveStatus.classList.remove('saved');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(persist, 600);
  }

  function flashStatus(msg, ok) {
    saveStatus.textContent = msg;
    saveStatus.classList.toggle('saved', !!ok);
  }

  /* ── Helpers ── */
  function textOf(html) {
    const div = document.createElement('div');
    div.innerHTML = html;
    return (div.textContent || '').trim();
  }
  function words(html) {
    const t = textOf(html);
    return t ? t.split(/\s+/).length : 0;
  }
  function readTime(html) {
    return Math.max(1, Math.round(words(html) / 200));
  }
  function fmtDate(ts) {
    return new Date(ts).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
  }

  /* ── Render ── */
  function renderCard() {
    cardTitle.textContent = post.title || 'Untitled post';
    const t = textOf(post.content);
    cardExcerpt.textContent = t.length > 200 ? t.slice(0, 200).trimEnd() + '…' : (t || 'Nothing written yet — open the post and start writing!');
    cardDate.textContent = post.updated ? 'Updated ' + fmtDate(post.updated) : fmtDate(post.created);
    cardReadtime.textContent = '🕐 ' + readTime(post.content) + ' min read';
  }

  function renderMeta() {
    postDate.textContent = post.updated ? 'Updated ' + fmtDate(post.updated) : fmtDate(post.created);
    postStats.textContent = readTime(post.content) + ' min read';
    wordCount.textContent = words(post.content) + ' words';
  }

  function renderPost() {
    postTitle.textContent = post.title;
    postBody.innerHTML = post.content;
    renderMeta();
  }

  /* ── Edit mode ── */
  function setEditing(on) {
    editing = on;
    postSection.classList.toggle('editing', on);
    toolbar.classList.toggle('hidden', !on);
    editorFooter.classList.toggle('hidden', !on);
    postTitle.contentEditable = on;
    postBody.contentEditable = on;
    editToggle.innerHTML = on ? '✓ Done' : '✏️ Edit';
    editToggle.classList.toggle('btn-primary', on);
    editToggle.classList.toggle('btn-ghost', !on);
    if (on) {
      flashStatus('Editing — changes save automatically', false);
      postBody.focus();
    } else {
      clearTimeout(saveTimer);
      persist();
    }
  }

  /* ── Wire up ── */
  cardOpen.addEventListener('click', () => { renderPost(); showSection('post'); });
  document.getElementById('blog-card').addEventListener('click', e => {
    if (e.target.closest('button')) return;
    renderPost();
    showSection('post');
  });

  postBack.addEventListener('click', () => {
    if (editing) setEditing(false);
    showSection('blog');
  });

  editToggle.addEventListener('click', () => setEditing(!editing));

  postTitle.addEventListener('input', scheduleSave);
  postBody.addEventListener('input', () => {
    scheduleSave();
    wordCount.textContent = words(postBody.innerHTML) + ' words';
  });

  /* Keep the title to a single line; Enter jumps into the body */
  postTitle.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      e.preventDefault();
      postBody.focus();
    }
  });

  /* Ctrl+S = save now (it autosaves anyway, but habits are habits) */
  document.addEventListener('keydown', e => {
    if (editing && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      clearTimeout(saveTimer);
      persist();
    }
  });

  /* Toolbar commands */
  toolbar.querySelectorAll('.tb-btn').forEach(btn => {
    /* Keep focus/selection in the editor when clicking toolbar buttons */
    btn.addEventListener('mousedown', e => e.preventDefault());
    btn.addEventListener('click', () => {
      const cmd = btn.dataset.cmd;
      const block = btn.dataset.block;
      if (cmd) document.execCommand(cmd, false, null);
      else if (block) document.execCommand('formatBlock', false, '<' + block + '>');
    });
  });

  linkBtn.addEventListener('click', () => {
    const url = prompt('Link address (e.g. https://example.com):');
    if (url) document.execCommand('createLink', false, url);
  });

  /* Backup — download the post as a small file */
  backupBtn.addEventListener('click', () => {
    const blob = new Blob([JSON.stringify(post, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'my-blog-post.json';
    a.click();
    URL.revokeObjectURL(a.href);
    flashStatus('Backup downloaded ✓', true);
  });

  /* Restore from a backup file */
  restoreInput.addEventListener('change', () => {
    const file = restoreInput.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const p = JSON.parse(reader.result);
        if (!p || typeof p.title !== 'string' || typeof p.content !== 'string') throw new Error('bad file');
        post = p;
        renderPost();
        persist();
        flashStatus('Restored from backup ✓', true);
      } catch (e) {
        flashStatus('⚠ That file doesn’t look like a blog backup', false);
      }
      restoreInput.value = '';
    };
    reader.readAsText(file);
  });

  /* Start over */
  resetBtn.addEventListener('click', () => {
    if (!confirm('Erase this post and start with a blank page?\n(Tip: download a Backup first if you might want it back.)')) return;
    post = { title: '', content: '', created: Date.now(), updated: null };
    postTitle.textContent = '';
    postBody.innerHTML = '';
    persist();
    flashStatus('Fresh page ready ✓', true);
    postTitle.focus();
  });

  /* ── First paint ── */
  renderCard();
  renderPost();
})();
