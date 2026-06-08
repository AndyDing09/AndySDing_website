/* ═══════════════════════════════════════════════
   ANDY S. DING — PERSONAL WEBSITE SCRIPTS
═══════════════════════════════════════════════ */

/* ── Animated particle/nebula background ── */
(function initCanvas() {
  const canvas = document.getElementById('bg-canvas');
  const ctx = canvas.getContext('2d');
  let W, H, particles, mouse = { x: -999, y: -999 };

  function resize() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  function mkParticle() {
    return {
      x: Math.random() * W,
      y: Math.random() * H,
      r: Math.random() * 1.6 + 0.3,
      vx: (Math.random() - 0.5) * 0.25,
      vy: (Math.random() - 0.5) * 0.25,
      alpha: Math.random() * 0.55 + 0.1,
      hue: Math.random() < 0.6 ? 240 : (Math.random() < 0.5 ? 265 : 180)
    };
  }

  function init() {
    resize();
    particles = Array.from({ length: 110 }, mkParticle);
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);

    /* Soft gradient blobs */
    const grad1 = ctx.createRadialGradient(W * 0.15, H * 0.25, 0, W * 0.15, H * 0.25, W * 0.38);
    grad1.addColorStop(0, 'rgba(99,102,241,0.07)');
    grad1.addColorStop(1, 'transparent');
    ctx.fillStyle = grad1;
    ctx.fillRect(0, 0, W, H);

    const grad2 = ctx.createRadialGradient(W * 0.82, H * 0.7, 0, W * 0.82, H * 0.7, W * 0.3);
    grad2.addColorStop(0, 'rgba(167,139,250,0.06)');
    grad2.addColorStop(1, 'transparent');
    ctx.fillStyle = grad2;
    ctx.fillRect(0, 0, W, H);

    /* Particles */
    particles.forEach(p => {
      /* Mouse repulsion */
      const dx = p.x - mouse.x, dy = p.y - mouse.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 120) {
        p.vx += (dx / dist) * 0.04;
        p.vy += (dy / dist) * 0.04;
      }
      /* Speed cap */
      const speed = Math.sqrt(p.vx * p.vx + p.vy * p.vy);
      if (speed > 0.8) { p.vx *= 0.8 / speed; p.vy *= 0.8 / speed; }

      p.x += p.vx;
      p.y += p.vy;
      if (p.x < 0) p.x = W;
      if (p.x > W) p.x = 0;
      if (p.y < 0) p.y = H;
      if (p.y > H) p.y = 0;

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `hsla(${p.hue}, 75%, 75%, ${p.alpha})`;
      ctx.fill();
    });

    /* Connection lines */
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const d  = Math.sqrt(dx * dx + dy * dy);
        if (d < 90) {
          ctx.beginPath();
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.strokeStyle = `rgba(99,102,241,${0.12 * (1 - d / 90)})`;
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }
      }
    }

    requestAnimationFrame(draw);
  }

  window.addEventListener('resize', () => { resize(); });
  window.addEventListener('mousemove', e => { mouse.x = e.clientX; mouse.y = e.clientY; });

  init();
  draw();
})();

/* ── Typed effect on hero ── */
(function initTyped() {
  const el = document.getElementById('typed');
  if (!el) return;
  const words = [
    'Robotics & Autonomous Systems.',
    'Environmental Engineering.',
    'Microplastic Research.',
    'Ocean Science & Technology.',
    'Entrepreneurship & Impact.'
  ];
  let wi = 0, ci = 0, deleting = false, wait = 0;

  function tick() {
    const word = words[wi];
    if (!deleting) {
      el.textContent = word.slice(0, ++ci);
      if (ci === word.length) { deleting = true; wait = 48; }
    } else {
      if (--wait > 0) { setTimeout(tick, 20); return; }
      el.textContent = word.slice(0, --ci);
      if (ci === 0) { deleting = false; wi = (wi + 1) % words.length; }
    }
    setTimeout(tick, deleting ? 38 : 75);
  }
  setTimeout(tick, 800);
})();

/* ── Section navigation ── */
(function initNav() {
  const sections = document.querySelectorAll('.section');
  const navLinks  = document.querySelectorAll('.nav-link, .drawer-link, .btn[data-section]');
  const navbar    = document.getElementById('navbar');

  function showSection(id) {
    sections.forEach(s => s.classList.remove('active'));
    const target = document.getElementById(id);
    if (target) {
      target.classList.add('active');
      window.scrollTo({ top: 0, behavior: 'instant' });
    }

    /* Update active nav state */
    document.querySelectorAll('.nav-link, .drawer-link').forEach(l => {
      l.classList.toggle('active', l.dataset.section === id);
    });

    /* Re-trigger skill bar animation when resume opens */
    if (id === 'resume') {
      document.querySelectorAll('.skill-bar-fill').forEach(bar => {
        bar.style.animation = 'none';
        requestAnimationFrame(() => {
          bar.style.animation = '';
        });
      });
    }
  }

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

  /* Scroll-based navbar shadow */
  window.addEventListener('scroll', () => {
    navbar.classList.toggle('scrolled', window.scrollY > 20);
  });

  /* Initial section from URL hash */
  const hash = window.location.hash.replace('#', '');
  if (hash && document.getElementById(hash)) showSection(hash);
  else showSection('home');
})();

/* ── Mobile hamburger / drawer ── */
const hamburger    = document.getElementById('hamburger');
const mobileDrawer = document.getElementById('mobile-drawer');
const drawerOverlay= document.getElementById('drawer-overlay');

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

/* ── Research tab switcher ── */
document.querySelectorAll('.res-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.res-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    const id = tab.dataset.tab;
    document.querySelectorAll('.research-content').forEach(c => {
      c.classList.toggle('hidden', !c.id.endsWith(id));
    });
  });
});

/* ── Scroll-reveal for cards ── */
(function initReveal() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.style.opacity = '1';
        entry.target.style.transform = 'translateY(0)';
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.08 });

  function observeCards() {
    document.querySelectorAll(
      '.blog-card, .research-card, .pub-item, .bento-card, .resume-block'
    ).forEach(el => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(24px)';
      el.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
      observer.observe(el);
    });
  }

  /* Re-observe when sections become active */
  const sectionObserver = new MutationObserver(observeCards);
  document.querySelectorAll('.section').forEach(s => {
    sectionObserver.observe(s, { attributes: true, attributeFilter: ['class'] });
  });

  observeCards();
})();


/* ── Subtle tilt on bento cards (desktop) ── */
document.querySelectorAll('.bento-card').forEach(card => {
  card.addEventListener('mousemove', e => {
    const rect = card.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width  - 0.5;
    const y = (e.clientY - rect.top)  / rect.height - 0.5;
    card.style.transform = `translateY(-4px) scale(1.01) rotateX(${-y * 6}deg) rotateY(${x * 6}deg)`;
  });
  card.addEventListener('mouseleave', () => {
    card.style.transform = '';
  });
});
