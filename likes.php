<?php
/**
 * Blog like counter.
 *  GET  -> {"likes": n}
 *  POST {"action":"like"|"unlike"} -> adjusts the count, returns {"likes": n}
 *
 * Stored next to the comments, outside public_html when possible.
 */

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$parent = dirname(__DIR__);
$dir = is_writable($parent) ? $parent . '/asd-site-data' : __DIR__ . '/site-data';
if (!is_dir($dir)) {
    @mkdir($dir, 0755, true);
}
$file = $dir . '/blog-likes.json';

function respond($code, $payload)
{
    http_response_code($code);
    echo json_encode($payload);
    exit;
}

$method = isset($_SERVER['REQUEST_METHOD']) ? $_SERVER['REQUEST_METHOD'] : 'GET';

if ($method === 'GET') {
    $likes = 0;
    if (is_file($file)) {
        $data = json_decode((string) file_get_contents($file), true);
        if (is_array($data) && isset($data['post-1'])) {
            $likes = max(0, (int) $data['post-1']);
        }
    }
    respond(200, ['likes' => $likes]);
}

if ($method !== 'POST') {
    respond(405, ['error' => 'Method not allowed']);
}

$input = json_decode((string) file_get_contents('php://input'), true);
$action = is_array($input) && isset($input['action']) ? $input['action'] : '';
if ($action !== 'like' && $action !== 'unlike') {
    respond(400, ['error' => 'Invalid action']);
}

$fp = @fopen($file, 'c+');
if (!$fp) {
    respond(500, ['error' => 'Could not store like']);
}
flock($fp, LOCK_EX);
$raw = stream_get_contents($fp);
$data = json_decode($raw !== false && $raw !== '' ? $raw : '{}', true);
if (!is_array($data)) {
    $data = [];
}
$likes = isset($data['post-1']) ? max(0, (int) $data['post-1']) : 0;
$likes = $action === 'like' ? $likes + 1 : max(0, $likes - 1);
$data['post-1'] = $likes;

ftruncate($fp, 0);
rewind($fp);
fwrite($fp, json_encode($data));
fflush($fp);
flock($fp, LOCK_UN);
fclose($fp);

respond(200, ['likes' => $likes]);
