<?php
/**
 * SITE LOCK — front controller.
 *
 * .htaccess routes EVERY request here. Nothing on the site (pages, assets,
 * resume.pdf, the PHP endpoints) is served until the visitor proves they know
 * the site password; then this file serves the originally requested path.
 *
 * Why not HTTP Basic auth: AuthUserFile needs the host's absolute path, which
 * we don't have. This needs no server paths — just one text file.
 *
 * THE PASSWORD lives in the first of these that exists, first non-empty line
 * that isn't a "#" comment:
 *   1. environment variable  ASD_SITE_PASSWORD
 *   2. ../asd-site-data/site-password.txt   <- use this one (survives deploys)
 *   3. ./site-password.txt                  <- fallback, wiped by clean deploys
 * The line may be a plain password or a password_hash() string ($2y$…).
 * With no password configured the site stays locked to everyone, by design.
 */

define('LOCK_COOKIE', 'asd_lock');
define('LOCK_TTL', 30 * 24 * 60 * 60);   // stay signed in for 30 days
define('LOCK_MAX_TRIES', 10);            // per IP
define('LOCK_TRY_WINDOW', 600);          // …per 10 minutes

// ── The stored secret ────────────────────────────────────────────────────
function lock_secret()
{
    static $cached = false;
    if ($cached !== false) {
        return $cached;
    }
    $cached = null;

    $env = getenv('ASD_SITE_PASSWORD');
    if (is_string($env) && trim($env) !== '') {
        return $cached = trim($env);
    }

    $files = [
        dirname(__DIR__) . '/asd-site-data/site-password.txt',
        __DIR__ . '/site-password.txt',
    ];
    foreach ($files as $file) {
        if (!is_file($file) || !is_readable($file)) {
            continue;
        }
        foreach (preg_split('/\R/', (string) file_get_contents($file)) as $line) {
            $line = trim($line);
            if ($line !== '' && $line[0] !== '#') {
                return $cached = $line;
            }
        }
    }
    return $cached;
}

function lock_password_ok($given)
{
    $stored = lock_secret();
    if ($stored === null || $given === '') {
        return false;
    }
    if (preg_match('/^\$(2[aby]|argon2)/', $stored)) {
        return password_verify($given, $stored);
    }
    return hash_equals($stored, $given);
}

// ── Signed cookie (no PHP session — the app's own endpoints own that) ────
function lock_key()
{
    return hash('sha256', 'asd-site-lock|v1|' . (string) lock_secret());
}

function lock_issue_cookie()
{
    $expires = time() + LOCK_TTL;
    $token   = $expires . '.' . hash_hmac('sha256', (string) $expires, lock_key());
    setcookie(LOCK_COOKIE, $token, [
        'expires'  => $expires,
        'path'     => '/',
        'httponly' => true,
        'samesite' => 'Lax',
        'secure'   => lock_is_https(),
    ]);
}

function lock_clear_cookie()
{
    setcookie(LOCK_COOKIE, '', [
        'expires' => time() - 3600, 'path' => '/', 'httponly' => true,
        'samesite' => 'Lax', 'secure' => lock_is_https(),
    ]);
}

function lock_is_https()
{
    if (!empty($_SERVER['HTTPS']) && strtolower((string) $_SERVER['HTTPS']) !== 'off') {
        return true;
    }
    return strtolower((string) ($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '')) === 'https';
}

function lock_unlocked()
{
    if (lock_secret() === null) {
        return false;                       // nothing configured -> nobody gets in
    }
    $parts = explode('.', (string) ($_COOKIE[LOCK_COOKIE] ?? ''), 2);
    if (count($parts) !== 2) {
        return false;
    }
    $expires = (int) $parts[0];
    if ($expires < time()) {
        return false;
    }
    return hash_equals(hash_hmac('sha256', (string) $expires, lock_key()), $parts[1]);
}

// ── Throttle guesses, per IP ─────────────────────────────────────────────
function lock_tries_file()
{
    $ip = (string) ($_SERVER['REMOTE_ADDR'] ?? 'cli');
    return rtrim(sys_get_temp_dir(), '/\\') . '/asd-lock-' . substr(sha1($ip), 0, 16) . '.txt';
}

function lock_throttled()
{
    $file = lock_tries_file();
    if (!is_file($file)) {
        return false;
    }
    $rows = array_filter(array_map('intval', explode("\n", (string) @file_get_contents($file))));
    $cut  = time() - LOCK_TRY_WINDOW;
    return count(array_filter($rows, function ($t) use ($cut) { return $t > $cut; })) >= LOCK_MAX_TRIES;
}

function lock_note_failure()
{
    $file = lock_tries_file();
    $rows = is_file($file) ? array_filter(array_map('intval', explode("\n", (string) @file_get_contents($file)))) : [];
    $cut  = time() - LOCK_TRY_WINDOW;
    $rows = array_filter($rows, function ($t) use ($cut) { return $t > $cut; });
    $rows[] = time();
    @file_put_contents($file, implode("\n", $rows), LOCK_EX);
}

function lock_forget_failures()
{
    @unlink(lock_tries_file());
}

// ── Where was the visitor actually going? ────────────────────────────────
function lock_requested_path()
{
    $path = parse_url((string) ($_SERVER['REQUEST_URI'] ?? '/'), PHP_URL_PATH);
    $path = urldecode((string) ($path === null ? '/' : $path));
    if ($path === '' || $path[0] !== '/') {
        $path = '/' . $path;
    }
    // Requests aimed straight at the gate are just "the site".
    if (preg_match('#^/gate\.php$#i', $path)) {
        $path = '/';
    }
    return $path;
}

/** Safe same-site redirect target: path only, query preserved, no host. */
function lock_return_to()
{
    $path  = lock_requested_path();
    $query = (string) ($_SERVER['QUERY_STRING'] ?? '');
    $query = trim(preg_replace('/(^|&)__lock=[^&]*/', '', $query), '&');
    if (strpos($path, "\n") !== false || strpos($path, "\r") !== false || substr($path, 0, 2) === '//') {
        return '/';
    }
    return $path . ($query !== '' ? '?' . $query : '');
}

// ── Serving a file once unlocked ─────────────────────────────────────────
function lock_content_type($file)
{
    static $types = [
        'html' => 'text/html; charset=utf-8',
        'htm'  => 'text/html; charset=utf-8',
        'css'  => 'text/css; charset=utf-8',
        'js'   => 'text/javascript; charset=utf-8',
        'mjs'  => 'text/javascript; charset=utf-8',
        'json' => 'application/json; charset=utf-8',
        'map'  => 'application/json; charset=utf-8',
        'webmanifest' => 'application/manifest+json',
        'txt'  => 'text/plain; charset=utf-8',
        'csv'  => 'text/csv; charset=utf-8',
        'md'   => 'text/plain; charset=utf-8',
        'xml'  => 'application/xml; charset=utf-8',
        'svg'  => 'image/svg+xml',
        'png'  => 'image/png',
        'jpg'  => 'image/jpeg',
        'jpeg' => 'image/jpeg',
        'gif'  => 'image/gif',
        'webp' => 'image/webp',
        'avif' => 'image/avif',
        'ico'  => 'image/x-icon',
        'pdf'  => 'application/pdf',
        'woff' => 'font/woff',
        'woff2'=> 'font/woff2',
        'ttf'  => 'font/ttf',
        'otf'  => 'font/otf',
        'mp4'  => 'video/mp4',
        'webm' => 'video/webm',
        'mp3'  => 'audio/mpeg',
        'zip'  => 'application/zip',
    ];
    $ext = strtolower((string) pathinfo($file, PATHINFO_EXTENSION));
    return $types[$ext] ?? 'application/octet-stream';
}

function lock_privacy_headers()
{
    header('X-Robots-Tag: noindex, nofollow, noarchive, noimageindex');
    header('Referrer-Policy: no-referrer');
    header('X-Content-Type-Options: nosniff');
}

/** Files the gate must never hand out, however they are requested. */
function lock_is_forbidden($realPath, $root)
{
    $name = basename($realPath);
    if ($name === '' || $name[0] === '.') {
        return true;                                   // .htaccess, .git*, dotfiles
    }
    if (strcasecmp($name, 'site-password.txt') === 0 || strcasecmp($name, 'gate.php') === 0) {
        return true;
    }
    $rel = str_replace('\\', '/', substr($realPath, strlen($root) + 1));
    foreach (explode('/', $rel) as $segment) {
        if ($segment !== '' && $segment[0] === '.') {
            return true;                               // anything under a dot-directory
        }
    }
    return false;
}

function lock_serve_404($root)
{
    $page = $root . '/404.html';
    http_response_code(404);
    lock_privacy_headers();
    header('Cache-Control: private, no-store');
    header('Content-Type: text/html; charset=utf-8');
    if (is_file($page)) {
        readfile($page);
    } else {
        echo '<!doctype html><meta charset="utf-8"><title>Not found</title><p>Not found.</p>';
    }
    exit;
}

function lock_serve($path)
{
    $root = rtrim(str_replace('\\', '/', __DIR__), '/');
    $rel  = ltrim($path, '/');
    if ($rel === '' || substr($rel, -1) === '/') {
        $rel .= 'index.html';
    }
    if (strpos($rel, "\0") !== false) {
        lock_serve_404($root);
    }

    $real = realpath($root . '/' . $rel);
    if ($real === false) {
        lock_serve_404($root);
    }
    $real = str_replace('\\', '/', $real);
    if (is_dir($real)) {
        $real = realpath($real . '/index.html');
        if ($real === false) {
            lock_serve_404($root);
        }
        $real = str_replace('\\', '/', $real);
    }
    // Must stay inside the document root — no ../ escapes, no symlink escapes.
    if (strncmp($real . '/', $root . '/', strlen($root) + 1) !== 0 || $real === $root) {
        lock_serve_404($root);
    }
    if (!is_file($real) || lock_is_forbidden($real, $root)) {
        lock_serve_404($root);
    }

    lock_privacy_headers();

    // PHP endpoints run in place; they set their own status/content type.
    if (strcasecmp((string) pathinfo($real, PATHINFO_EXTENSION), 'php') === 0) {
        include $real;
        exit;
    }

    $mtime = (int) filemtime($real);
    $size  = (int) filesize($real);
    $etag  = '"' . dechex($mtime) . '-' . dechex($size) . '"';

    header('Content-Type: ' . lock_content_type($real));
    header('Cache-Control: private, max-age=0, must-revalidate');
    header('ETag: ' . $etag);
    header('Last-Modified: ' . gmdate('D, d M Y H:i:s', $mtime) . ' GMT');

    $noneMatch = trim((string) ($_SERVER['HTTP_IF_NONE_MATCH'] ?? ''));
    $since     = strtotime((string) ($_SERVER['HTTP_IF_MODIFIED_SINCE'] ?? '')) ?: 0;
    if (($noneMatch !== '' && $noneMatch === $etag) || ($since !== 0 && $since >= $mtime)) {
        http_response_code(304);
        exit;
    }

    header('Content-Length: ' . $size);
    if (strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET')) !== 'HEAD') {
        while (ob_get_level() > 0) {
            ob_end_clean();
        }
        readfile($real);
    }
    exit;
}

// ── The lock screen ──────────────────────────────────────────────────────
function lock_screen($status, $heading, $message, $showForm = true)
{
    http_response_code($status);
    lock_privacy_headers();
    header('Content-Type: text/html; charset=utf-8');
    header('Cache-Control: private, no-store');
    $heading = htmlspecialchars($heading, ENT_QUOTES, 'UTF-8');
    $message = htmlspecialchars($message, ENT_QUOTES, 'UTF-8');
    $action  = htmlspecialchars(lock_return_to(), ENT_QUOTES, 'UTF-8');
    $form    = $showForm ? <<<FORM
    <form method="post" action="$action" autocomplete="on">
      <label for="pw">Password</label>
      <input id="pw" name="asd_lock_password" type="password" autocomplete="current-password"
             autofocus required spellcheck="false" aria-describedby="note">
      <button type="submit">Enter</button>
    </form>
FORM
    : '';

    echo <<<HTML
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive">
<meta name="color-scheme" content="dark">
<title>Private — andysding.com</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Space+Grotesk:wght@400;500;600&display=swap">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #04121a; --panel: #081c26; --ink: #e8f1f2; --muted: #8fb0b6;
    --accent: #35e0c8; --warn: #ffb454; --line: rgba(127, 232, 216, 0.16);
  }
  html { background: var(--bg); color-scheme: dark; }
  body {
    min-height: 100dvh; display: grid; place-items: center; padding: 24px;
    background: radial-gradient(1100px 620px at 50% -10%, #0a2331 0%, var(--bg) 62%);
    color: var(--ink); font-family: 'Space Grotesk', system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .card {
    width: 100%; max-width: 420px; background: rgba(8, 28, 38, 0.72);
    border: 1px solid var(--line); border-radius: 10px; padding: 36px 32px 30px;
    box-shadow: 0 24px 64px rgba(0, 0, 0, 0.55); backdrop-filter: blur(6px);
  }
  .mark { display: block; margin: 0 auto 22px; width: 62px; height: 62px; opacity: 0.95; }
  h1 {
    font-family: 'Instrument Serif', Georgia, serif; font-weight: 400;
    font-size: 2rem; line-height: 1.15; letter-spacing: -0.01em; text-align: center;
  }
  p.sub { margin-top: 10px; text-align: center; color: var(--muted); font-size: 0.9rem; line-height: 1.55; }
  form { margin-top: 26px; }
  label { display: block; font-size: 0.72rem; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); }
  input {
    width: 100%; margin-top: 8px; padding: 12px 14px; font: inherit; color: var(--ink);
    background: rgba(4, 18, 26, 0.85); border: 1px solid var(--line); border-radius: 6px;
    outline: none; transition: border-color 0.2s ease, box-shadow 0.2s ease;
  }
  input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(53, 224, 200, 0.16); }
  button {
    width: 100%; margin-top: 16px; padding: 12px 14px; font: 500 1rem 'Space Grotesk', system-ui, sans-serif;
    color: #04121a; background: var(--accent); border: 0; border-radius: 6px; cursor: pointer;
    transition: filter 0.2s ease, transform 0.08s ease;
  }
  button:hover { filter: brightness(1.08); }
  button:active { transform: translateY(1px); }
  .note { margin-top: 20px; font-size: 0.78rem; line-height: 1.6; color: var(--muted); text-align: center; }
  .warn { color: var(--warn); }
  code { font-family: ui-monospace, 'SFMono-Regular', monospace; font-size: 0.95em; }
  @media (prefers-reduced-motion: no-preference) {
    .card { animation: rise 0.5s cubic-bezier(0.2, 0.7, 0.3, 1) both; }
    @keyframes rise { from { opacity: 0; transform: translateY(10px); } }
  }
</style>
</head>
<body>
  <main class="card">
    <svg class="mark" viewBox="0 0 120 120" aria-hidden="true">
      <circle cx="60" cy="60" r="34" fill="none" stroke="#35e0c8" stroke-width="3" opacity=".9"/>
      <circle cx="60" cy="60" r="50" fill="none" stroke="#35e0c8" stroke-width="1.6" opacity=".32"/>
      <path d="M60 37 L73 71 H47 Z" fill="none" stroke="#e8f1f2" stroke-width="3"/>
      <circle cx="60" cy="60" r="5" fill="#35e0c8"/>
    </svg>
    <h1>$heading</h1>
    <p class="sub">$message</p>
$form
    <p class="note" id="note">andysding.com is private. If you should have the password, ask Andy.</p>
  </main>
</body>
</html>
HTML;
    exit;
}

// ── Request handling ─────────────────────────────────────────────────────
$method = strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));

if (lock_secret() === null) {
    lock_screen(
        503,
        'Locked',
        'No site password is configured on the server, so nothing here can be opened. '
        . 'Create asd-site-data/site-password.txt (one line: the password) to unlock.',
        false
    );
}

if (isset($_GET['__lock']) && $_GET['__lock'] === 'out') {
    lock_clear_cookie();
    lock_screen(200, 'Signed out', 'You are locked out of andysding.com until you enter the password again.');
}

if (lock_unlocked()) {
    lock_serve(lock_requested_path());
}

if ($method === 'POST' && isset($_POST['asd_lock_password'])) {
    if (lock_throttled()) {
        lock_screen(429, 'Too many tries', 'Wait about ten minutes, then try again.', false);
    }
    if (lock_password_ok((string) $_POST['asd_lock_password'])) {
        lock_forget_failures();
        lock_issue_cookie();
        lock_privacy_headers();
        header('Cache-Control: private, no-store');
        header('Location: ' . lock_return_to(), true, 303);
        exit;
    }
    lock_note_failure();
    lock_screen(401, 'Wrong password', 'That is not the password for this site. Try again.');
}

lock_screen(401, 'Private site', 'This site is locked. Enter the password to continue.');
