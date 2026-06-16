<?php
/**
 * Warrior Desk relay — the website is a VIEWER; the Python agent is the source.
 *
 *   POST ?action=publish   (header X-Warrior-Token)  -> store the agent's snapshot
 *   GET  ?action=snapshot  (signed-in user)          -> return the latest snapshot + age
 *   POST ?action=request   (signed-in user)          -> queue an on-demand ticker
 *   GET  ?action=requests  (header X-Warrior-Token)  -> agent pulls + clears the queue
 *
 * The agent authenticates writes with a shared token kept OUTSIDE public_html in
 * asd-site-data/warrior-publish-token.txt (same place as the other secrets). The
 * snapshot is read only by a signed-in user, so this private invite-only desk
 * stays private. No order is ever placed here — this only moves JSON around.
 */
require __DIR__ . '/lib_platform.php';

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$action = $_GET['action'] ?? '';

$SNAP = ASD_DATA_DIR . '/warrior-snapshot.json';
$REQS = ASD_DATA_DIR . '/warrior-requests.json';
$TOKEN_FILE = ASD_DATA_DIR . '/warrior-publish-token.txt';
$MAX_SNAPSHOT_BYTES = 600 * 1024;

function warrior_token_ok($tokenFile)
{
    if (!is_file($tokenFile)) {
        plat_json(503, ['error' => 'Publishing not configured (no token file on the server).']);
    }
    $want = trim((string) @file_get_contents($tokenFile));
    $got = trim((string) ($_SERVER['HTTP_X_WARRIOR_TOKEN'] ?? ''));
    if ($want === '' || $got === '' || !hash_equals($want, $got)) {
        plat_json(401, ['error' => 'Bad or missing publish token.']);
    }
}

// ── GET ──
if ($method === 'GET' && $action === 'snapshot') {
    plat_require_user();
    if (!is_file($SNAP)) {
        plat_json(200, ['ok' => true, 'snapshot' => null,
            'hint' => 'No snapshot yet. Run "warrior publish" (or "warrior run") with WARRIOR_PUBLISH_URL set.']);
    }
    $snap = json_decode((string) file_get_contents($SNAP), true);
    $age = max(0, time() - (int) @filemtime($SNAP));
    plat_json(200, ['ok' => true, 'snapshot' => $snap, 'age_seconds' => $age,
        'stale' => $age > 180]);
}

if ($method === 'GET' && $action === 'requests') {
    warrior_token_ok($TOKEN_FILE);
    $syms = is_file($REQS) ? json_decode((string) file_get_contents($REQS), true) : [];
    if (!is_array($syms)) { $syms = []; }
    @unlink($REQS); // consume
    plat_json(200, ['symbols' => array_values($syms)]);
}

// ── POST ──
if ($method === 'POST' && $action === 'publish') {
    warrior_token_ok($TOKEN_FILE);
    if (!plat_rate_limit('warrior_publish', 120, 60)) {
        plat_json(429, ['error' => 'Publishing too fast.']);
    }
    $raw = (string) file_get_contents('php://input');
    if (strlen($raw) > $MAX_SNAPSHOT_BYTES) {
        plat_json(413, ['error' => 'Snapshot too large.']);
    }
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        plat_json(400, ['error' => 'Invalid snapshot JSON.']);
    }
    $data['received_at'] = time();
    $ok = @file_put_contents($SNAP, json_encode($data, JSON_UNESCAPED_UNICODE), LOCK_EX);
    if ($ok === false) {
        plat_json(500, ['error' => 'Could not store snapshot on the server.']);
    }
    plat_json(200, ['ok' => true, 'stored' => strlen($raw)]);
}

if ($method === 'POST' && $action === 'request') {
    plat_require_user();
    if (!plat_rate_limit('warrior_request', 30, 60)) {
        plat_json(429, ['error' => 'Slow down.']);
    }
    $in = json_decode((string) file_get_contents('php://input'), true);
    $sym = strtoupper(trim((string) ($in['symbol'] ?? '')));
    if (!preg_match('/^[A-Z0-9.\-]{1,12}$/', $sym)) {
        plat_json(400, ['error' => 'Enter a valid ticker.']);
    }
    $syms = is_file($REQS) ? json_decode((string) file_get_contents($REQS), true) : [];
    if (!is_array($syms)) { $syms = []; }
    if (!in_array($sym, $syms, true)) { $syms[] = $sym; }
    $syms = array_slice($syms, -10);
    @file_put_contents($REQS, json_encode($syms), LOCK_EX);
    plat_json(200, ['ok' => true, 'queued' => $sym,
        'note' => 'Queued — your running agent will evaluate it on its next pass.']);
}

plat_json(400, ['error' => 'Unknown action']);
