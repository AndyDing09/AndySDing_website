# Morning briefing — cron setup (Hostinger)

The briefing now builds **server-side** and is cached, so the Stocks tab loads it
instantly instead of computing in the browser. A morning cron refreshes it before
the market opens each trading day.

## How it works
- `briefing.php?action=today` → returns the stored briefing JSON. If the cache is
  missing or older than ~18h it rebuilds on the spot (slower, ~15s).
- `briefing.php?action=build&token=XXX` → **forces a rebuild** and overwrites the
  cache. This is what the cron calls. It is **token-protected** so only your cron
  can trigger a rebuild.
- The result is stored at `asd-site-data/briefing-today.json` (outside public_html).

## One-time setup

### 1. Create the cron token (server-side secret)
In hPanel → **File Manager**, go to the `asd-site-data` folder (the same place as
`app-secret.txt`, **not** inside `public_html`). Create a file named
`cron-token.txt` containing one long random string, e.g.

```
m9Q2x7Lr4Tz0Vb8Kc3Pn6Yw1Hd5Sg
```

Make up your own — any 24+ random characters. This is the only thing that lets the
cron rebuild, so keep it private (never commit it, never paste it anywhere public).

### 2. Add the cron job
hPanel → **Advanced → Cron Jobs → Create**. Use **wget** (or curl) to hit the
build URL. Replace `YOURTOKEN` with what you put in `cron-token.txt`:

```
wget -q -O /dev/null "https://andysding.com/briefing.php?action=build&token=YOURTOKEN"
```

**Schedule** — markets open 9:30 AM ET, so build a bit before. Pick the time in
**your server's timezone** (Hostinger is often UTC; 9:00 AM ET ≈ 13:00 or 14:00
UTC depending on daylight saving). A simple, safe choice is **every weekday at
8:50 AM and again at 9:25 AM ET**. As cron fields (minute hour day month weekday),
for 13:50 and 14:25 UTC on weekdays:

```
50 13 * * 1-5   wget -q -O /dev/null "https://andysding.com/briefing.php?action=build&token=YOURTOKEN"
25 14 * * 1-5   wget -q -O /dev/null "https://andysding.com/briefing.php?action=build&token=YOURTOKEN"
```

If hPanel gives you dropdowns instead of raw cron syntax, set: minute `50`, hour
`13`, day `*`, month `*`, weekday `Mon–Fri`, and paste the wget command. Add the
second row the same way.

> Tip: if you don't know your server's timezone, run a one-line cron once that
> writes `date` to a file, or just pick a time and check when `briefing-today.json`
> updates in File Manager. You can always retune the hour.

### 3. Done
The page already calls `action=today`, so visitors always get the latest cached
briefing instantly. Even with **no cron**, it still works — it just rebuilds itself
on the first visit after going stale.

## Verifying
- Visit `https://andysding.com/briefing.php?action=today` → you should see JSON
  with `market`, `watch`, and `ideas`.
- After the cron runs, `asd-site-data/briefing-today.json`'s modified time should
  match the cron time.
- A wrong/missing token returns `{"error":"Bad or missing cron token"}` (403) —
  that's the protection working.

## What's in the briefing
- **Market overview** — SPY/QQQ/DIA/VIX with a plain-English regime read.
- **Stocks to watch today** — the universe ranked by a documented trigger
  (oversold-bounce, breakout-watch, trend-pullback, overbought-caution, trend),
  each with two-sided bull/bear notes, support/resistance, **illustrative**
  entry/stop/target levels, and that stock's **daily news**.
- **All research ideas** — the full two-sided list.

Everything stays educational: entry/stop/target are *examples of what a trader
might watch*, **not** recommendations or predictions.
