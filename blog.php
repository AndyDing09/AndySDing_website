<?php
/**
 * Blog post API.
 *  GET                                    -> the published post (public)
 *  POST {"action":"verify","code":...}    -> checks the dev code
 *  POST {"action":"publish","code","title","content"} -> publishes the post
 *
 * The post lives in asd-site-data/blog-post.json, OUTSIDE public_html,
 * so it survives clean-slate deploys and is never in the git repo.
 *
 * The dev code defaults to the built-in one but can be overridden by
 * putting a new code in asd-site-data/dev-code.txt (recommended, since
 * the repo is public). Failed attempts are rate limited per IP.
 */

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$parent = dirname(__DIR__);
$dir = is_writable($parent) ? $parent . '/asd-site-data' : __DIR__ . '/site-data';
if (!is_dir($dir)) {
    @mkdir($dir, 0755, true);
}
$postFile = $dir . '/blog-post.json';
$authFile = $dir . '/blog-auth.json';
$codeFile = $dir . '/dev-code.txt';

/* sha256 of the default dev code (overridable via dev-code.txt) */
$DEFAULT_CODE_HASH = hash('sha256', 'asd-dev|0902');

function respond($code, $payload)
{
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    exit;
}

$method = isset($_SERVER['REQUEST_METHOD']) ? $_SERVER['REQUEST_METHOD'] : 'GET';

/* ── Public read ── */
if ($method === 'GET') {
    if (is_file($postFile)) {
        $post = json_decode((string) file_get_contents($postFile), true);
        if (is_array($post) && isset($post['title'], $post['content'])) {
            respond(200, [
                'title'   => $post['title'],
                'content' => $post['content'],
                'updated' => isset($post['updated']) ? $post['updated'] : null,
            ]);
        }
    }
    respond(200, ['title' => null, 'content' => null, 'updated' => null]);
}

if ($method !== 'POST') {
    respond(405, ['error' => 'Method not allowed']);
}

$input = json_decode((string) file_get_contents('php://input'), true);
if (!is_array($input)) {
    respond(400, ['error' => 'Invalid request']);
}
$action = isset($input['action']) ? $input['action'] : '';
if ($action !== 'verify' && $action !== 'publish') {
    respond(400, ['error' => 'Unknown action']);
}

/* ── Brute-force protection: 5 failed codes / 15 min per IP ── */
$now = time();
$ipHash = substr(sha1((isset($_SERVER['REMOTE_ADDR']) ? $_SERVER['REMOTE_ADDR'] : '') . 'asd-dev'), 0, 12);

function loadJson($file)
{
    if (!is_file($file)) {
        return [];
    }
    $d = json_decode((string) file_get_contents($file), true);
    return is_array($d) ? $d : [];
}

$auth = loadJson($authFile);
$fails = isset($auth[$ipHash]) ? $auth[$ipHash] : [];
$fails = array_values(array_filter($fails, function ($t) use ($now) {
    return $now - $t < 900;
}));
if (count($fails) >= 5) {
    respond(429, ['error' => 'Too many wrong codes — locked out for 15 minutes.']);
}

/* ── Check the code ── */
$code = trim((string) (isset($input['code']) ? $input['code'] : ''));
$expectedHash = $DEFAULT_CODE_HASH;
if (is_file($codeFile)) {
    $custom = trim((string) file_get_contents($codeFile));
    if ($custom !== '') {
        $expectedHash = hash('sha256', 'asd-dev|' . $custom);
    }
}
$valid = hash_equals($expectedHash, hash('sha256', 'asd-dev|' . $code));

if (!$valid) {
    $fails[] = $now;
    $auth[$ipHash] = $fails;
    if (count($auth) > 200) {
        $auth = array_slice($auth, -100, null, true);
    }
    @file_put_contents($authFile, json_encode($auth), LOCK_EX);
    respond(403, ['error' => 'Wrong code']);
}

/* Valid code — clear this IP's failures */
if (isset($auth[$ipHash])) {
    unset($auth[$ipHash]);
    @file_put_contents($authFile, json_encode($auth), LOCK_EX);
}

if ($action === 'verify') {
    respond(200, ['ok' => true]);
}

/* ── Publish ── */
$title = trim((string) (isset($input['title']) ? $input['title'] : ''));
$content = (string) (isset($input['content']) ? $input['content'] : '');

if ($title === '') {
    respond(400, ['error' => 'The post needs a title']);
}
if (mb_strlen($title) > 200) {
    $title = mb_substr($title, 0, 200);
}
if (trim(strip_tags($content)) === '') {
    respond(400, ['error' => 'The post needs some content']);
}
if (strlen($content) > 200000) {
    respond(400, ['error' => 'Post is too large']);
}

/* Sanitize the HTML: allow formatting tags only, strip scripts/handlers */
$content = preg_replace('#<\s*(script|style|iframe|object|embed|form|input|textarea|button|link|meta)[^>]*>.*?<\s*/\s*\1\s*>#is', '', $content);
$content = preg_replace('#<\s*(script|style|iframe|object|embed|form|input|textarea|button|link|meta)[^>]*/?\s*>#i', '', $content);
$content = preg_replace('/\son\w+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)/i', '', $content);
$content = preg_replace('/(href|src)\s*=\s*("|\')\s*javascript:[^"\']*\2/i', '$1=$2#$2', $content);

$post = [
    'title'   => $title,
    'content' => $content,
    'updated' => $now,
];

$fp = @fopen($postFile, 'c+');
if (!$fp) {
    respond(500, ['error' => 'Could not save the post']);
}
flock($fp, LOCK_EX);
ftruncate($fp, 0);
rewind($fp);
fwrite($fp, json_encode($post, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
fflush($fp);
flock($fp, LOCK_UN);
fclose($fp);

respond(200, ['ok' => true, 'post' => $post]);
