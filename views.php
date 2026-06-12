<?php
/**
 * Blog view counter.
 *  GET  -> {"views": n}
 *  POST {"action":"view"} -> increments once, returns {"views": n}
 *
 * The client only POSTs once per visitor per day (localStorage guard),
 * and the server also rate-limits by IP hash to keep counts honest.
 * Stored next to the comments, outside public_html when possible.
 */

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$parent = dirname(__DIR__);
$dir = is_writable($parent) ? $parent . '/asd-site-data' : __DIR__ . '/site-data';
if (!is_dir($dir)) {
    @mkdir($dir, 0755, true);
}
$file = $dir . '/blog-views.json';

function respond($code, $payload)
{
    http_response_code($code);
    echo json_encode($payload);
    exit;
}

$method = isset($_SERVER['REQUEST_METHOD']) ? $_SERVER['REQUEST_METHOD'] : 'GET';

if ($method === 'GET') {
    $views = 0;
    if (is_file($file)) {
        $data = json_decode((string) file_get_contents($file), true);
        if (is_array($data) && isset($data['post-1'])) {
            $views = max(0, (int) $data['post-1']);
        }
    }
    respond(200, ['views' => $views]);
}

if ($method !== 'POST') {
    respond(405, ['error' => 'Method not allowed']);
}

$input  = json_decode((string) file_get_contents('php://input'), true);
$action = is_array($input) && isset($input['action']) ? $input['action'] : '';
if ($action !== 'view') {
    respond(400, ['error' => 'Invalid action']);
}

$ipHash = substr(sha1(($_SERVER['REMOTE_ADDR'] ?? '') . 'asd-views'), 0, 12);
$today  = date('Y-m-d');

$fp = @fopen($file, 'c+');
if (!$fp) {
    respond(500, ['error' => 'Could not store view']);
}
flock($fp, LOCK_EX);
$raw  = stream_get_contents($fp);
$data = json_decode($raw !== false && $raw !== '' ? $raw : '{}', true);
if (!is_array($data)) {
    $data = [];
}

$views   = isset($data['post-1']) ? max(0, (int) $data['post-1']) : 0;
$seen    = isset($data['seen']) && is_array($data['seen']) ? $data['seen'] : [];

/* One counted view per visitor per day */
$seenKey = $ipHash . ':' . $today;
if (!isset($seen[$seenKey])) {
    $views++;
    $seen[$seenKey] = 1;
    /* prune entries from previous days so the file stays small */
    foreach (array_keys($seen) as $k) {
        if (substr($k, -10) !== $today) {
            unset($seen[$k]);
        }
    }
    $data['post-1'] = $views;
    $data['seen']   = $seen;

    ftruncate($fp, 0);
    rewind($fp);
    fwrite($fp, json_encode($data));
    fflush($fp);
}

flock($fp, LOCK_UN);
fclose($fp);

respond(200, ['views' => $views]);
