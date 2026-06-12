<?php
/**
 * Blog comments API (v2 — threaded + votes).
 *
 *  GET  /comments.php
 *       -> {"comments":[{id,parentId,name,text,time,votes}, ...]}  (flat list, oldest first)
 *
 *  POST /comments.php  {"name","text","parentId","website"}
 *       -> stores a top-level or reply comment; "website" is a honeypot
 *
 *  POST /comments.php  {"action":"vote","id":"<id>","dir":1|-1}
 *       -> adjusts vote count for that comment; one vote per visitor per comment
 *
 *  DELETE /comments.php  {"secret":"<ADMIN_SECRET>"}
 *       -> wipes all comments (admin only)
 *
 * Comments are stored OUTSIDE public_html when possible.
 */

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

define('ADMIN_SECRET', getenv('ASD_ADMIN_SECRET') ?: 'change-me-before-use');

$parent = dirname(__DIR__);
$dir    = is_writable($parent) ? $parent . '/asd-site-data' : __DIR__ . '/site-data';
if (!is_dir($dir)) {
    @mkdir($dir, 0755, true);
}
$file      = $dir . '/blog-comments.json';
$votesFile = $dir . '/blog-comment-votes.json';

function respond($code, $payload)
{
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    exit;
}

function publicFields($c)
{
    return [
        'id'       => $c['id']       ?? '',
        'parentId' => $c['parentId'] ?? null,
        'name'     => $c['name']     ?? 'Anonymous',
        'text'     => $c['text']     ?? '',
        'time'     => $c['time']     ?? 0,
        'votes'    => $c['votes']    ?? 0,
    ];
}

function containsProfanity($text)
{
    $t = mb_strtolower($text);
    $t = strtr($t, [
        '0' => 'o', '1' => 'i', '!' => 'i', '3' => 'e', '4' => 'a',
        '@' => 'a', '5' => 's', '$' => 's', '7' => 't', '+' => 't',
        '*' => '', '.' => '', '-' => '', '_' => '',
    ]);
    $wordList = [
        'fuck', 'shit', 'bitch', 'bastard', 'asshole', 'ass', 'dick',
        'cock', 'pussy', 'cunt', 'whore', 'slut', 'douche', 'piss',
        'prick', 'wanker', 'bollocks', 'damn', 'goddamn',
        'nigger', 'nigga', 'faggot', 'fag', 'retard', 'kike', 'spic', 'chink',
    ];
    $spaced = preg_replace('/[^a-z]+/', ' ', $t);
    foreach ($wordList as $w) {
        if (preg_match('/\b' . preg_quote($w, '/') . '\b/', $spaced)) return true;
    }
    $squeezed    = preg_replace('/[^a-z]+/', '', $t);
    $substringList = ['fuck', 'shit', 'bitch', 'whore', 'slut', 'cunt', 'nigger', 'nigga', 'faggot'];
    foreach ($substringList as $w) {
        if (strpos($squeezed, $w) !== false) return true;
    }
    return false;
}

function loadJson($path, $default = [])
{
    if (!is_file($path)) return $default;
    $raw = file_get_contents($path);
    $decoded = json_decode($raw !== false ? $raw : '', true);
    return is_array($decoded) ? $decoded : $default;
}

function saveJson($path, $data)
{
    file_put_contents($path, json_encode($data, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$ipHash = substr(sha1(($_SERVER['REMOTE_ADDR'] ?? '') . 'asd-comments-v2'), 0, 12);

/* ── GET: return flat list of all comments ── */
if ($method === 'GET') {
    $comments = loadJson($file, []);
    respond(200, ['comments' => array_values(array_map('publicFields', $comments))]);
}

/* ── DELETE: admin wipe ── */
if ($method === 'DELETE') {
    $input  = json_decode((string) file_get_contents('php://input'), true);
    $secret = is_array($input) ? ($input['secret'] ?? '') : '';
    if ($secret !== ADMIN_SECRET) {
        respond(403, ['error' => 'Forbidden']);
    }
    saveJson($file, []);
    saveJson($votesFile, []);
    respond(200, ['ok' => true, 'cleared' => true]);
}

if ($method !== 'POST') {
    respond(405, ['error' => 'Method not allowed']);
}

$input = json_decode((string) file_get_contents('php://input'), true);
if (!is_array($input)) {
    respond(400, ['error' => 'Invalid request']);
}

/* ── POST vote ── */
if (($input['action'] ?? '') === 'vote') {
    $commentId = trim((string) ($input['id'] ?? ''));
    $dir       = (int) ($input['dir'] ?? 0);

    if ($commentId === '' || ($dir !== 1 && $dir !== -1)) {
        respond(400, ['error' => 'Invalid vote']);
    }

    $fp = @fopen($file, 'c+');
    if (!$fp) respond(500, ['error' => 'Storage error']);
    flock($fp, LOCK_EX);
    $raw      = stream_get_contents($fp);
    $comments = json_decode($raw !== false && $raw !== '' ? $raw : '[]', true);
    if (!is_array($comments)) $comments = [];

    $votesData = loadJson($votesFile, []);
    $voterKey  = $ipHash . ':' . $commentId;

    if (isset($votesData[$voterKey])) {
        $prev = (int) $votesData[$voterKey];
        if ($prev === $dir) {
            /* Same direction — undo the vote */
            foreach ($comments as &$c) {
                if (($c['id'] ?? '') === $commentId) {
                    $c['votes'] = (int)($c['votes'] ?? 0) - $dir;
                    break;
                }
            }
            unset($votesData[$voterKey]);
        } else {
            /* Flip direction */
            foreach ($comments as &$c) {
                if (($c['id'] ?? '') === $commentId) {
                    $c['votes'] = (int)($c['votes'] ?? 0) - $prev + $dir;
                    break;
                }
            }
            $votesData[$voterKey] = $dir;
        }
    } else {
        foreach ($comments as &$c) {
            if (($c['id'] ?? '') === $commentId) {
                $c['votes'] = (int)($c['votes'] ?? 0) + $dir;
                break;
            }
        }
        $votesData[$voterKey] = $dir;
    }
    unset($c);

    ftruncate($fp, 0); rewind($fp);
    fwrite($fp, json_encode($comments, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
    fflush($fp); flock($fp, LOCK_UN); fclose($fp);
    saveJson($votesFile, $votesData);

    /* Return the updated vote count for this comment */
    $newVotes = 0;
    foreach ($comments as $c) {
        if (($c['id'] ?? '') === $commentId) { $newVotes = (int)($c['votes'] ?? 0); break; }
    }
    $voted = isset($votesData[$voterKey]) ? (int)$votesData[$voterKey] : 0;
    respond(200, ['ok' => true, 'votes' => $newVotes, 'voted' => $voted]);
}

/* ── POST new comment / reply ── */
if (!empty($input['website'])) {
    respond(200, ['ok' => true]); // honeypot
}

$name     = trim(preg_replace('/[\x00-\x1F\x7F]/u', ' ', (string) ($input['name'] ?? '')));
$text     = trim(preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/u', ' ', (string) ($input['text'] ?? '')));
$parentId = trim((string) ($input['parentId'] ?? ''));

if (mb_strlen($name) > 60)  $name = mb_substr($name, 0, 60);
if ($text === '')            respond(400, ['error' => 'Comment cannot be empty']);
if (mb_strlen($text) > 1500) respond(400, ['error' => 'Comment is too long (1500 characters max)']);
if (containsProfanity($text) || containsProfanity($name)) {
    respond(400, ['error' => "Let's keep it friendly — please remove the strong language and try again."]);
}

$fp = @fopen($file, 'c+');
if (!$fp) respond(500, ['error' => 'Could not store comment']);
flock($fp, LOCK_EX);
$raw      = stream_get_contents($fp);
$comments = json_decode($raw !== false && $raw !== '' ? $raw : '[]', true);
if (!is_array($comments)) $comments = [];

/* Rate limit: one comment per 30 s per visitor */
$now = time();
foreach (array_slice(array_reverse($comments), 0, 5) as $c) {
    if (($c['ip'] ?? '') === $ipHash && $now - ($c['time'] ?? 0) < 30) {
        flock($fp, LOCK_UN); fclose($fp);
        respond(429, ['error' => "You're commenting too fast — wait a few seconds."]);
    }
}

/* Validate parentId if provided */
if ($parentId !== '') {
    $found = false;
    foreach ($comments as $c) { if (($c['id'] ?? '') === $parentId) { $found = true; break; } }
    if (!$found) respond(400, ['error' => 'Parent comment not found']);
}

$comment = [
    'id'       => bin2hex(random_bytes(6)),
    'parentId' => $parentId !== '' ? $parentId : null,
    'name'     => $name !== '' ? $name : 'Anonymous',
    'text'     => $text,
    'time'     => $now,
    'votes'    => 0,
    'ip'       => $ipHash,
];
$comments[] = $comment;
if (count($comments) > 1000) $comments = array_slice($comments, -1000);

ftruncate($fp, 0); rewind($fp);
fwrite($fp, json_encode($comments, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
fflush($fp); flock($fp, LOCK_UN); fclose($fp);

respond(200, ['ok' => true, 'comment' => publicFields($comment)]);
