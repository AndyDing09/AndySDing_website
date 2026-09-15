# Site lock

andysding.com is private. Every request — pages, CSS/JS, `photo.jpg`,
`resume.pdf`, `docs/`, and all the PHP endpoints — goes through `gate.php`
first and is served only after the visitor enters the site password.

No absolute server paths are involved, which is what stalled the earlier
HTTP-Basic attempt (`AuthUserFile` needs the host's real filesystem path).

## Turn it on: one file, one line

In hPanel → File Manager, open the **`asd-site-data`** folder that sits next to
`public_html`, and create:

```
asd-site-data/site-password.txt
```

with a single line — the password you want to use:

```
whatever-password-you-pick
```

That's it. The lock is live the moment the file exists.

Why there: `asd-site-data/` is outside `public_html`, so the web server can
never serve the file, the clean-slate FTP deploy never wipes it, and it stays
out of this repo.

**Until that file exists the site is closed to everyone, including you** — the
lock screen says so and returns 503. That is deliberate: no password file means
no way in, rather than an accidentally open site.

### Options

- A `password_hash()` string (`$2y$...`) works in place of the plain password;
  `gate.php` detects the `$2y$` prefix and verifies against it.
- `ASD_SITE_PASSWORD` in the environment beats the file, if you ever set one.
- Fallback location `public_html/site-password.txt` also works, but a deploy
  wipes it (`dangerous-clean-slate: true`), so don't rely on it.

## Day to day

- Signing in sets one signed, HttpOnly cookie (`asd_lock`), good for 30 days.
  The cookie is keyed off the password, so **changing the password signs
  everyone out**.
- Sign out with `https://www.andysding.com/?__lock=out`.
- Ten wrong guesses from one IP in ten minutes → 429 for a few minutes.
- Every response carries `X-Robots-Tag: noindex, nofollow`, and `robots.txt`
  (the one file still served publicly) is now `Disallow: /`.
- Deep links still work: `/classic.html?x=1` prompts for the password, then
  lands on `/classic.html?x=1`.

## Turning the lock off

Delete these four lines from `.htaccess`:

```
RewriteEngine On
RewriteBase /
RewriteCond %{REQUEST_URI} !^/gate\.php$
RewriteRule ^ /gate.php [L,QSA]
```

Nothing else in the site depends on the lock; `gate.php` becomes dead code you
can delete too. Put `robots.txt` back to `Allow: /` if you want the site
indexed again.
