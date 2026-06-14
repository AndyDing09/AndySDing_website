/**
 * Exploratory E2E suite for andysding.com — generated from a source-verified
 * walkthrough of the site's core flows. Locators are taken from the actual DOM
 * (index.html / script.js / chat.js / stocks*.js), not guessed.
 *
 * Run against production (default) or a local build:
 *   BASE_URL=https://www.andysding.com npx playwright test          # default
 *   BASE_URL=http://127.0.0.1:8765      npx playwright test          # local serve
 *
 * NOTE: these hit the LIVE site. Tests here are read-only / net-zero — no
 * comments are posted and NO paper/live trade is ever submitted (that flow is
 * intentionally excluded; it needs auth + an explicit confirm gate).
 */
import { test, expect } from '@playwright/test';

const BASE = process.env.BASE_URL || 'https://www.andysding.com';

test.describe('1 — Section navigation (hash-routed SPA)', () => {
  test('nav link activates its section and updates the hash', async ({ page }) => {
    await page.goto(BASE + '/');
    await expect(page.locator('#home')).toHaveClass(/active/);

    await page.locator('.nav-link[data-section="research"]').click();
    await expect(page.locator('#research')).toHaveClass(/active/);
    await expect(page.locator('#home')).not.toHaveClass(/active/);
    await expect(page.locator('.nav-link[data-section="research"]')).toHaveClass(/active/);
    await expect(page).toHaveURL(/#research$/);
  });

  test('deep-linking via URL hash opens the right section on load', async ({ page }) => {
    await page.goto(BASE + '/#about');
    await expect(page.locator('#about')).toHaveClass(/active/);
    await expect(page.locator('#about .section-title')).toContainText(/About/i);
  });

  test('logo returns to home', async ({ page }) => {
    await page.goto(BASE + '/#resume');
    await page.locator('.nav-logo').click();
    await expect(page.locator('#home')).toHaveClass(/active/);
  });
});

test.describe('2 — Dark-mode toggle', () => {
  test('toggles theme and persists across reload', async ({ page }) => {
    await page.goto(BASE + '/');
    const html = page.locator('html');
    const before = await html.getAttribute('data-theme');

    await page.locator('#theme-toggle').click();
    const after = await html.getAttribute('data-theme');
    expect(after).not.toBe(before);

    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', after!);
    expect(await page.evaluate(() => localStorage.getItem('asd-theme'))).toBe(after);
  });
});

test.describe('3 — Mobile drawer', () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test('hamburger opens the drawer; a link navigates and closes it', async ({ page }) => {
    await page.goto(BASE + '/');
    await expect(page.locator('#mobile-drawer')).not.toHaveClass(/open/);

    await page.locator('#hamburger').click();
    await expect(page.locator('#mobile-drawer')).toHaveClass(/open/);
    await expect(page.locator('#drawer-overlay')).toHaveClass(/visible/);

    await page.locator('.drawer-link[data-section="interests"]').click();
    await expect(page.locator('#interests')).toHaveClass(/active/);
    await expect(page.locator('#mobile-drawer')).not.toHaveClass(/open/);
  });
});

test.describe('4 — Stocks lab', () => {
  test('sub-tabs switch between Lookup and the Research desk', async ({ page }) => {
    await page.goto(BASE + '/#stocks');
    await expect(page.locator('#sa-pane-lookup')).toBeVisible();

    await page.locator('.sa-subtab[data-pane="desk"]').click();
    await expect(page.locator('#sa-pane-desk')).toBeVisible();
    await expect(page.locator('#sa-pane-lookup')).toBeHidden();
    // morning briefing auto-loads on first open (server-cached, instant)
    await expect(page.locator('.desk-brief')).toBeVisible();
    await expect(page.locator('.db-idea').first()).toBeVisible({ timeout: 20000 });
  });

  test('add a ticker, open its dashboard (chart + analysis + game plan)', async ({ page }) => {
    await page.goto(BASE + '/#stocks');
    await page.locator('#sa-add-input').fill('AAPL');
    await page.locator('#sa-add-form').getByRole('button', { name: /add/i }).click();

    const card = page.locator('.sa-wl-card[data-symbol="AAPL"]');
    await expect(card).toBeVisible({ timeout: 20000 });

    await card.click();
    await expect(page.locator('#sa-dash-view')).toBeVisible();
    await expect(page.locator('#sa-chart canvas').first()).toBeVisible({ timeout: 20000 });
    await expect(page.locator('#sa-signal-panel')).toContainText(/Signal summary/i);
    await expect(page.locator('#sa-plan-panel')).toContainText(/game plan/i);

    await page.locator('#sa-dash-back').click();
    await expect(page.locator('#sa-watchlist-view')).toBeVisible();
  });

  test('near-real-time: LIVE badge shows when the price feed is enabled', async ({ page }) => {
    await page.goto(BASE + '/#stocks');
    await page.locator('#sa-add-input').fill('AAPL');
    await page.locator('#sa-add-form').getByRole('button', { name: /add/i }).click();
    await page.locator('.sa-wl-card[data-symbol="AAPL"]').click();
    const rt = await page.request.get(BASE + '/stocks.php?action=rtstatus');
    const enabled = (await rt.json()).enabled;
    test.skip(!enabled, 'Finnhub key not configured on server');
    await expect(page.locator('#sa-live-badge')).toBeVisible({ timeout: 15000 });
  });
});

test.describe('5 — Blog post + Kym chat assistant', () => {
  test('open a post and toggle like (net-zero, leaves count unchanged)', async ({ page }) => {
    await page.goto(BASE + '/#blog');
    await page.locator('#blog-card').click();
    await expect(page.locator('#post')).toHaveClass(/active/);

    const like = page.locator('#like-btn');
    await like.click();                       // like
    await expect(like).toHaveClass(/liked/);
    await like.click();                       // unlike -> restore original state
    await expect(like).not.toHaveClass(/liked/);
  });

  test('chat widget opens and returns a reply', async ({ page }) => {
    await page.goto(BASE + '/');
    await page.locator('#chat-fab').click();
    await expect(page.locator('#chat-panel')).toBeVisible();

    await page.locator('#chat-input').fill('What is Project Kymarion?');
    await page.locator('#chat-form').getByRole('button', { name: /send/i }).click();

    await expect(page.locator('.chat-msg.user')).toContainText(/Kymarion/i);
    // a bot reply renders whether AI is on (chat.php) or the FAQ fallback is used
    await expect(page.locator('.chat-msg.bot').last()).toBeVisible({ timeout: 30000 });
  });
});
