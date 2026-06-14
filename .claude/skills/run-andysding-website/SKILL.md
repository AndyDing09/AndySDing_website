---
name: run-andysding-website
description: Run, serve, preview, or screenshot the andysding.com personal website locally, and smoke-test its live PHP endpoints. Use when asked to run/start/preview/screenshot the site, verify a frontend/design change, or check the stocks/briefing/chat endpoints.
---

# Run andysding.com

Personal website (`andysding.com`): **static HTML/CSS/JS, no build step.** Dynamic
features (chat, the stocks lab, the morning briefing) call PHP endpoints
(`chat.php`, `stocks.php`, `briefing.php`, `auth.php`, ...). The front-end degrades
gracefully when those aren't reachable, so a plain static server is enough to
verify layout/design, and the **live** endpoints are smoke-tested over HTTP.

The driver is [.claude/skills/run-andysding-website/driver.py](driver.py) — it
serves the repo with Python's `http.server` and screenshots pages with headless
Chrome, and can curl the read-only PHP endpoints. **Paths below are relative to
the repo root.**

## Prerequisites
Already present on this machine — Python 3 and Chrome. No npm, no build, no PHP needed for the frontend.
- Python 3 (`python`)
- Chrome (auto-detected at `C:\Program Files\Google\Chrome\Application\chrome.exe`; Edge is a fallback). Override with `CHROME=<path>`.

There is **no install/build step** — it's a static site. (Editing CSS/JS? bump the
`?v=N` query string on that file's `<script>`/`<link>` in `index.html` so the
browser doesn't serve a stale cached copy.)

## Run (agent path) — screenshot the design
```bash
python ".claude/skills/run-andysding-website/driver.py" shot index.html
```
Screenshots all key pages by default (`index.html kymarion.html dev.html`):
```bash
python ".claude/skills/run-andysding-website/driver.py" shot
```
PNGs land in `%TEMP%\andysding-shots\` (printed as `OK <path>` lines, e.g.
`C:\Users\andyd\AppData\Local\Temp\andysding-shots\index.png`). **Open the PNG and
look at it** — that's the verification. Override the output dir with `SHOTS=<dir>`.

**Mobile QA** — pass `--size WxH` (suffixed onto the filename):
```bash
python ".claude/skills/run-andysding-website/driver.py" shot index.html --size 375x812
```
Screenshots run with `--force-prefers-reduced-motion`, so the hero's entry
fade-in is skipped and captures are deterministic (otherwise you catch the hero
mid-animation and the headline looks faded/missing — a capture artifact, not a bug).

The Stocks tab is a tab inside the page; screenshot it by passing the page and
then driving the tab in a browser if needed, but for design checks the default
pages cover the hero, blog post, and dev pages.

## Run (manual viewing)
```bash
python ".claude/skills/run-andysding-website/driver.py" serve --port 8765
# -> http://127.0.0.1:8765/index.html  (Ctrl-C to stop)
```
Same static server the screenshotter uses. Useful for clicking around yourself.

## Smoke-test the live PHP endpoints
PHP isn't installed locally, so the backend is checked against the deployed site
(read-only GETs only — safe, no mutations):
```bash
python ".claude/skills/run-andysding-website/driver.py" api
```
Prints status + a snippet for `rtstatus`, a quote, a chart, the morning briefing,
and chat status. Pass a base URL to target somewhere else:
`... api https://andysding.com`.

## Gotchas
- **PHP doesn't run on the static server.** Requests to `*.php` return the raw PHP
  source (HTTP 200), so the JS's `fetch().json()` calls fail and the UI falls back
  (chat → FAQ-only, prices → "delayed", briefing → "unavailable"). This is
  expected locally and does **not** mean the page is broken — the design renders
  fully. Use `driver.py api` (live site) to exercise the real backend.
- **Screenshots are viewport-sized (1440×2600), not full-page.** Headless Chrome's
  `--screenshot` captures a window, not the whole scroll height. The top
  (hero + first sections) is captured; for lower sections, scroll via `serve` in a
  real browser. `--virtual-time-budget=4000` lets scripts/animations settle first.
- **Deploys are automatic, not from here.** Pushing to branch
  `claude/pensive-sagan-9rTxC` triggers a clean-slate FTPS deploy to Hostinger
  `public_html`. `main` is kept in sync with the same branch. Running this driver
  does not deploy anything.
- **Secrets/data are off-repo.** Server-side config lives in `../asd-site-data/`
  (sibling of the deploy root): `anthropic-key.txt` (AI chat — currently off, so
  `chat status` returns `{"ai":false}`), `finnhub-key.txt` (live prices),
  `app-secret.txt`, `db-config.php`, `cron-token.txt`. None are in this repo and
  the local static server has no access to them.
- **First `api briefing today` call can take ~15s** if the server-side cache is
  stale (it rebuilds on demand); subsequent calls are instant.

## Troubleshooting
- `No Chrome/Edge found` → set `CHROME=/c/Program Files/Google/Chrome/Application/chrome.exe` (or your Edge path).
- Screenshot file is created but looks empty/half-rendered → increase the budget:
  edit `--virtual-time-budget` in `driver.py` (e.g. to `8000`), or view live via `serve`.
- `api` shows `[ERR]` lines → you're offline or the live site is down; the
  `shot`/`serve` paths still work fully offline.
