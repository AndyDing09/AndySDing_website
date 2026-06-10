<?php
/**
 * Blog comments API.
 *  GET  -> {"comments":[{name,text,time}, ...]} (oldest first)
 *  POST {"name","text","website"} -> stores a comment ("website" is a honeypot)
 *
 * Comments are stored OUTSIDE public_html when possible so the
 * clean-slate FTP deploy never wipes them.
 */

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$parent = dirname(__DIR__);
$dir = is_writable($parent) ? $parent . '/asd-site-data' : __DIR__ . '/site-data';
if (!is_dir($dir)) {
    @mkdir($dir, 0755, true);
}
$file = $dir . '/blog-comments.json';

function respond($code, $payload)
{
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    exit;
}

function publicFields($c)
{
    return [
        'name' => isset($c['name']) ? $c['name'] : 'Anonymous',
        'text' => isset($c['text']) ? $c['text'] : '',
        'time' => isset($c['time']) ? $c['time'] : 0,
    ];
}

/**
 * Profanity check. Normalizes common letter swaps (f*ck, sh1t, f.u.c.k)
 * before matching, so simple disguises don't slip through.
 */
function containsProfanity($text)
{
    $t = mb_strtolower($text);
    $t = strtr($t, [
        '0' => 'o', '1' => 'i', '!' => 'i', '3' => 'e', '4' => 'a',
        '@' => 'a', '5' => 's', '$' => 's', '7' => 't', '+' => 't',
        '*' => '', '.' => '', '-' => '', '_' => '',
    ]);

    /* Whole-word matches (words that also appear inside innocent words,
       e.g. "ass" in "class", are only blocked as standalone words) */
    $wordList = [
        'fuck', 'shit', 'bitch', 'bastard', 'asshole', 'ass', 'dick',
        'cock', 'pussy', 'cunt', 'whore', 'slut', 'douche', 'piss',
        'prick', 'wanker', 'bollocks', 'damn', 'goddamn',
        'nigger', 'nigga', 'faggot', 'fag', 'retard', 'kike', 'spic', 'chink',
    ];
    $spaced = preg_replace('/[^a-z]+/', ' ', $t);
    foreach ($wordList as $w) {
        if (preg_match('/\b' . $w . '\b/', $spaced)) {
            return true;
        }
    }

    /* Substring matches on the fully squeezed string, for unambiguous
       terms — catches "bullsh it", "f u c k", embedded slurs, etc. */
    $squeezed = preg_replace('/[^a-z]+/', '', $t);
    $substringList = [
        'fuck', 'shit', 'bitch', 'whore', 'slut', 'cunt',
        'nigger', 'nigga', 'faggot',
    ];
    foreach ($substringList as $w) {
        if (strpos($squeezed, $w) !== false) {
            return true;
        }
    }

    return false;
}

$method = isset($_SERVER['REQUEST_METHOD']) ? $_SERVER['REQUEST_METHOD'] : 'GET';

if ($method === 'GET') {
    $comments = [];
    if (is_file($file)) {
        $decoded = json_decode((string) file_get_contents($file), true);
        if (is_array($decoded)) {
            $comments = array_map('publicFields', $decoded);
        }
    }
    respond(200, ['comments' => array_values($comments)]);
}

if ($method !== 'POST') {
    respond(405, ['error' => 'Method not allowed']);
}

$input = json_decode((string) file_get_contents('php://input'), true);
if (!is_array($input)) {
    respond(400, ['error' => 'Invalid request']);
}

/* Honeypot: bots fill the hidden "website" field — pretend success, store nothing */
if (!empty($input['website'])) {
    respond(200, ['ok' => true]);
}

$name = trim(preg_replace('/[\x00-\x1F\x7F]/u', ' ', (string) ($input['name'] ?? '')));
$text = trim(preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/u', ' ', (string) ($input['text'] ?? '')));

if (mb_strlen($name) > 60) {
    $name = mb_substr($name, 0, 60);
}
if ($text === '') {
    respond(400, ['error' => 'Comment cannot be empty']);
}
if (mb_strlen($text) > 1500) {
    respond(400, ['error' => 'Comment is too long (1500 characters max)']);
}
if (containsProfanity($text) || containsProfanity($name)) {
    respond(400, ['error' => 'Let\'s keep it friendly — please remove the strong language and try again.']);
}

$ipHash = substr(sha1(($_SERVER['REMOTE_ADDR'] ?? '') . 'asd-comments'), 0, 12);

$fp = @fopen($file, 'c+');
if (!$fp) {
    respond(500, ['error' => 'Could not store comment']);
}
flock($fp, LOCK_EX);
$raw = stream_get_contents($fp);
$comments = json_decode($raw !== false && $raw !== '' ? $raw : '[]', true);
if (!is_array($comments)) {
    $comments = [];
}

/* Light rate limit: one comment per 30 seconds per visitor */
$now = time();
foreach (array_slice(array_reverse($comments), 0, 5) as $c) {
    if (($c['ip'] ?? '') === $ipHash && $now - ($c['time'] ?? 0) < 30) {
        flock($fp, LOCK_UN);
        fclose($fp);
        respond(429, ['error' => 'You\'re commenting too fast — wait a few seconds.']);
    }
}

$comment = [
    'name' => $name !== '' ? $name : 'Anonymous',
    'text' => $text,
    'time' => $now,
    'ip'   => $ipHash,
];
$comments[] = $comment;
if (count($comments) > 1000) {
    $comments = array_slice($comments, -1000);
}

ftruncate($fp, 0);
rewind($fp);
fwrite($fp, json_encode($comments, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
fflush($fp);
flock($fp, LOCK_UN);
fclose($fp);

respond(200, ['ok' => true, 'comment' => publicFields($comment)]);
