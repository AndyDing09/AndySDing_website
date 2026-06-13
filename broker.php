<?php
/**
 * Private per-user broker connection (Alpaca; paper default, live opt-in).
 *   GET  ?action=status            -> {connected, mode, masked} for THIS user
 *   GET  ?action=account           -> Alpaca account (server-side; keys never sent)
 *   POST {action:'connect', mode, key, secret}  -> validate w/ Alpaca, store ENCRYPTED
 *   POST {action:'disconnect', mode}
 *
 * Keys are encrypted at rest (AES-256-GCM), decrypted only here, server-side,
 * scoped to the authenticated user, and NEVER returned to the browser or logged.
 * Only Alpaca is supported (official API). Firstrade has no API — not connectable.
 */
require __DIR__ . '/lib_platform.php';

$uid = plat_require_user();
$pdo = plat_pdo();
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

function load_keys($pdo, $uid, $mode)
{
    $st = $pdo->prepare('SELECT key_enc, secret_enc FROM broker_keys WHERE user_id = ? AND mode = ?');
    $st->execute([$uid, $mode]);
    $row = $st->fetch();
    if (!$row) {
        return null;
    }
    $key = plat_decrypt($row['key_enc']);
    $secret = plat_decrypt($row['secret_enc']);
    return ($key && $secret) ? ['key' => $key, 'secret' => $secret] : null;
}

if ($method === 'GET') {
    $action = $_GET['action'] ?? '';

    if ($action === 'status') {
        $st = $pdo->prepare('SELECT mode, key_enc FROM broker_keys WHERE user_id = ?');
        $st->execute([$uid]);
        $modes = [];
        foreach ($st->fetchAll() as $r) {
            $k = plat_decrypt($r['key_enc']);
            $modes[$r['mode']] = $k ? ('••••' . substr($k, -4)) : '••••'; // masked id only
        }
        plat_json(200, ['connected' => !empty($modes), 'modes' => $modes]);
    }

    if ($action === 'account') {
        $mode = ($_GET['mode'] ?? 'paper') === 'live' ? 'live' : 'paper';
        $k = load_keys($pdo, $uid, $mode);
        if (!$k) {
            plat_json(400, ['error' => 'No ' . $mode . ' account connected']);
        }
        list($code, $body) = plat_alpaca($mode, $k['key'], $k['secret'], '/v2/account');
        if ($code !== 200 || !is_array($body)) {
            plat_json(502, ['error' => 'Could not reach Alpaca (check your keys / mode).']);
        }
        // Return only safe account fields — never the keys
        plat_json(200, ['account' => [
            'mode'         => $mode,
            'status'       => $body['status'] ?? null,
            'currency'     => $body['currency'] ?? 'USD',
            'cash'         => $body['cash'] ?? null,
            'equity'       => $body['equity'] ?? null,
            'buying_power'  => $body['buying_power'] ?? null,
            'portfolio_value' => $body['portfolio_value'] ?? null,
            'pattern_day_trader' => $body['pattern_day_trader'] ?? null,
        ]]);
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

if ($action === 'disconnect') {
    $mode = ($in['mode'] ?? 'paper') === 'live' ? 'live' : 'paper';
    $st = $pdo->prepare('DELETE FROM broker_keys WHERE user_id = ? AND mode = ?');
    $st->execute([$uid, $mode]);
    plat_json(200, ['ok' => true]);
}

if ($action === 'connect') {
    if (!plat_rate_limit('connect', 10, 600)) {
        plat_json(429, ['error' => 'Too many attempts — wait a few minutes.']);
    }
    $mode = ($in['mode'] ?? 'paper') === 'live' ? 'live' : 'paper';
    $key = trim((string) ($in['key'] ?? ''));
    $secret = trim((string) ($in['secret'] ?? ''));
    if ($key === '' || $secret === '') {
        plat_json(400, ['error' => 'Enter both your API key and secret.']);
    }
    // Validate against Alpaca BEFORE storing — don't persist bad/typo'd keys.
    list($code, $body) = plat_alpaca($mode, $key, $secret, '/v2/account');
    if ($code === 401 || $code === 403) {
        plat_json(400, ['error' => 'Alpaca rejected those keys for the ' . $mode . ' endpoint. Double-check the key/secret and that you picked the right mode.']);
    }
    if ($code !== 200 || !is_array($body)) {
        plat_json(502, ['error' => 'Could not verify with Alpaca right now — try again shortly.']);
    }
    $st = $pdo->prepare('REPLACE INTO broker_keys (user_id, mode, key_enc, secret_enc, updated_at) VALUES (?,?,?,?,?)');
    $st->execute([$uid, $mode, plat_encrypt($key), plat_encrypt($secret), time()]);
    plat_json(200, ['ok' => true, 'mode' => $mode, 'masked' => '••••' . substr($key, -4),
        'account_status' => $body['status'] ?? null]);
}

plat_json(400, ['error' => 'Unknown action']);
