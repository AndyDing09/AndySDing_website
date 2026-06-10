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
hamburger.addEventListener('click', () => {
  const isOpen = mobileDrawer.classList.toggle('open');
  hamburger.classList.toggle('open', isOpen);
  drawerOverlay.classList.toggle('visible', isOpen);
});
drawerOverlay.addEventListener('click', closeMobileDrawer);

/* ═══════════════════════════════════════════════
   BLOG — single post with built-in WYSIWYG editor
   Content is saved in this browser via localStorage.
   Comments are loaded/submitted via comments.php.
═══════════════════════════════════════════════ */
(function initBlog() {
  var KEY = 'asd-blog-post-v1';

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
    created: Date.now(),
    updated: null
  };

  /* ── Elements ── */
  var cardDate     = document.getElementById('card-date');
  var cardTitle    = document.getElementById('card-title');
  var cardExcerpt  = document.getElementById('card-excerpt');
  var cardReadtime = document.getElementById('card-readtime');
  var cardOpen     = document.getElementById('card-open');

  var postSection  = document.getElementById('post');
  var postBack     = document.getElementById('post-back');
  var editToggle   = document.getElementById('edit-toggle');
  var saveStatus   = document.getElementById('save-status');
  var toolbar      = document.getElementById('editor-toolbar');
  var postTitle    = document.getElementById('post-title');
  var postDate     = document.getElementById('post-date');
  var postStats    = document.getElementById('post-stats');
  var postBody     = document.getElementById('post-body');
  var editorFooter = document.getElementById('editor-footer');
  var wordCount    = document.getElementById('word-count');
  var backupBtn    = document.getElementById('backup-btn');
  var restoreInput = document.getElementById('restore-input');
  var resetBtn     = document.getElementById('reset-btn');
  var linkBtn      = document.getElementById('link-btn');

  var post = loadPost();
  var editing = false;
  var saveTimer = null;

  /* ── Storage ── */
  function loadPost() {
    try {
      var raw = localStorage.getItem(KEY);
      if (raw) {
        var p = JSON.parse(raw);
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
      flashStatus('Saved \u2713', true);
    } catch (e) {
      flashStatus('\u26a0 Could not save (storage full?)', false);
    }
    renderCard();
    renderMeta();
  }

  function scheduleSave() {
    saveStatus.textContent = 'Saving\u2026';
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
    var div = document.createElement('div');
    div.innerHTML = html;
    return (div.textContent || '').trim();
  }
  function words(html) {
    var t = textOf(html);
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
    var t = textOf(post.content);
    cardExcerpt.textContent = t.length > 200 ? t.slice(0, 200).trimEnd() + '\u2026' : (t || 'Nothing written yet \u2014 open the post and start writing!');
    cardDate.textContent = post.updated ? 'Updated ' + fmtDate(post.updated) : fmtDate(post.created);
    cardReadtime.textContent = '\U0001f4f0 ' + readTime(post.content) + ' min read';
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
    editToggle.innerHTML = on ? '\u2713 Done' : '\u270f\ufe0f Edit';
    editToggle.classList.toggle('btn-primary', on);
    editToggle.classList.toggle('btn-ghost', !on);
    if (on) {
      flashStatus('Editing \u2014 changes save automatically', false);
      postBody.focus();
    } else {
      clearTimeout(saveTimer);
      persist();
    }
  }

  /* ── Wire up ── */
  cardOpen.addEventListener('click', function() { renderPost(); showSection('post'); });
  document.getElementById('blog-card').addEventListener('click', function(e) {
    if (e.target.closest('button')) return;
    renderPost();
    showSection('post');
  });

  postBack.addEventListener('click', function() {
    if (editing) setEditing(false);
    showSection('blog');
  });

  editToggle.addEventListener('click', function() { setEditing(!editing); });

  postTitle.addEventListener('input', scheduleSave);
  postBody.addEventListener('input', function() {
    scheduleSave();
    wordCount.textContent = words(postBody.innerHTML) + ' words';
  });

  /* Keep the title to a single line; Enter jumps into the body */
  postTitle.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      postBody.focus();
    }
  });

  /* Ctrl+S = save now */
  document.addEventListener('keydown', function(e) {
    if (editing && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      clearTimeout(saveTimer);
      persist();
    }
  });

  /* Toolbar commands */
  var i, btn, cmd, block;
  var btns = toolbar.querySelectorAll('.tb-btn');
  for (i = 0; i < btns.length; i++) {
    btn = btns[i];
    btn.addEventListener('mousedown', function(e) { e.preventDefault(); });
    btn.addEventListener('click', function(b) {
      return function() {
        cmd = b.dataset.cmd;
        block = b.dataset.block;
        if (cmd) document.execCommand(cmd, false, null);
        else if (block) document.execCommand('formatBlock', false, '<' + block + '>');
      };
    }(btn));
  }

  linkBtn.addEventListener('click', function() {
    var url = prompt('Link address (e.g. https://example.com):');
    if (url) document.execCommand('createLink', false, url);
  });

  /* Backup */
  backupBtn.addEventListener('click', function() {
    var blob = new Blob([JSON.stringify(post, null, 2)], { type: 'application/json' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'my-blog-post.json';
    a.click();
    URL.revokeObjectURL(a.href);
    flashStatus('Backup downloaded \u2713', true);
  });

  /* Restore from backup file */
  restoreInput.addEventListener('change', function() {
    var file = restoreInput.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function() {
      try {
        var p = JSON.parse(reader.result);
        if (!p || typeof p.title !== 'string' || typeof p.content !== 'string') throw new Error('bad file');
        post = p;
        renderPost();
        persist();
        flashStatus('Restored from backup \u2713', true);
      } catch (e) {
        flashStatus('\u26a0 That file doesn\'t look like a blog backup', false);
      }
      restoreInput.value = '';
    };
    reader.readAsText(file);
  });

  /* Start over */
  resetBtn.addEventListener('click', function() {
    if (!confirm('Erase this post and start with a blank page?\n(Tip: download a Backup first if you might want it back.)')) return;
    post = { title: '', content: '', created: Date.now(), updated: null };
    postTitle.textContent = '';
    postBody.innerHTML = '';
    persist();
    flashStatus('Fresh page ready \u2713', true);
    postTitle.focus();
  });

  /* ── First paint ── */
  renderCard();
  renderPost();
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
