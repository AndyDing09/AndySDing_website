<?php
/**
 * Accounts — invite-only signup, login, logout, session check.
 *   GET  ?action=me                                  -> {user|null, configured}
 *   POST {action:'signup', username, password, invite}
 *   POST {action:'login',  username, password}
 *   POST {action:'logout'}
 * Passwords are hashed (password_hash). Signup needs a valid invite code from
 * asd-site-data/invite-codes.txt. Each user only ever sees their own data.
 */
require __DIR__ . '/lib_platform.php';

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

if ($method === 'GET') {
    $action = $_GET['action'] ?? '';
    if ($action === 'me') {
        plat_session();
        $uid = plat_current_user_id();
        if (!$uid) {
            plat_json(200, ['user' => null, 'configured' => plat_configured()]);
        }
        $st = plat_pdo()->prepare('SELECT id, username FROM users WHERE id = ?');
        $st->execute([$uid]);
        $u = $st->fetch();
        plat_json(200, ['user' => $u ?: null, 'configured' => true]);
    }
    plat_json(400, ['error' => 'Unknown action']);
}

if ($method !== 'POST') {
    plat_json(405, ['error' => 'Method not allowed']);
}

$in = json_decode((string) file_get_contents('php://input'), true);
if (!is_array($in)) {
    plat_json(400, ['error' => 'Invalid request']);
}
$action = $in['action'] ?? '';

if ($action === 'logout') {
    plat_session();
    $_SESSION = [];
    session_destroy();
    plat_json(200, ['ok' => true]);
}

if (!plat_rate_limit('auth', 12, 600)) {
    plat_json(429, ['error' => 'Too many attempts — wait a few minutes.']);
}

$username = strtolower(trim((string) ($in['username'] ?? '')));
$password = (string) ($in['password'] ?? '');

if (!preg_match('/^[a-z0-9_.-]{3,32}$/', $username)) {
    plat_json(400, ['error' => 'Username must be 3–32 chars (letters, numbers, _.-).']);
}
if (strlen($password) < 8) {
    plat_json(400, ['error' => 'Password must be at least 8 characters.']);
}

$pdo = plat_pdo();

if ($action === 'signup') {
    // Validate invite code
    $invite = trim((string) ($in['invite'] ?? ''));
    $codesFile = ASD_DATA_DIR . '/invite-codes.txt';
    $codes = is_file($codesFile) ? array_filter(array_map('trim', explode("\n", (string) file_get_contents($codesFile)))) : [];
    if (!in_array($invite, $codes, true)) {
        plat_json(403, ['error' => 'Invalid invite code.']);
    }
    $st = $pdo->prepare('SELECT id FROM users WHERE username = ?');
    $st->execute([$username]);
    if ($st->fetch()) {
        plat_json(409, ['error' => 'That username is taken.']);
    }
    $ins = $pdo->prepare('INSERT INTO users (username, pass_hash, created_at) VALUES (?,?,?)');
    $ins->execute([$username, password_hash($password, PASSWORD_DEFAULT), time()]);
    $uid = (int) $pdo->lastInsertId();
    plat_session();
    session_regenerate_id(true);
    $_SESSION['uid'] = $uid;
    plat_json(200, ['user' => ['id' => $uid, 'username' => $username]]);
}

if ($action === 'login') {
    $st = $pdo->prepare('SELECT id, username, pass_hash FROM users WHERE username = ?');
    $st->execute([$username]);
    $u = $st->fetch();
    if (!$u || !password_verify($password, $u['pass_hash'])) {
        plat_json(401, ['error' => 'Wrong username or password.']);
    }
    plat_session();
    session_regenerate_id(true);
    $_SESSION['uid'] = (int) $u['id'];
    plat_json(200, ['user' => ['id' => (int) $u['id'], 'username' => $u['username']]]);
}

plat_json(400, ['error' => 'Unknown action']);
