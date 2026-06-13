<?php
/**
 * Paper-trading desk (per-user, Alpaca). Human-in-the-loop: orders are only
 * placed on an explicit POST action:'submit' with confirm:true — the UI shows a
 * review step first, and nothing is ever auto-submitted.
 *
 *   GET  ?action=positions[&mode=paper]
 *   GET  ?action=orders[&mode=paper]
 *   GET  ?action=journal
 *   POST {action:'preview', mode, symbol, side, qty, type, limit_price?, stop_price?}
 *   POST {action:'submit',  ...same..., confirm:true}        (places the order)
 *   POST {action:'journal_add', symbol, side, qty, rationale, desk_pick}
 *
 * Keys are decrypted only here, server-side, scoped to the authenticated user.
 */
require __DIR__ . '/lib_platform.php';

$uid = plat_require_user();
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

function mode_of($v) { return ($v === 'live') ? 'live' : 'paper'; }
function clean_sym($s) { $s = strtoupper(trim((string) $s)); return preg_match('/^[A-Z0-9.\-]{1,12}$/', $s) ? $s : null; }

function keys_or_die($uid, $mode)
{
    $k = plat_load_keys($uid, $mode);
    if (!$k) {
        plat_json(400, ['error' => 'No ' . $mode . ' account connected.']);
    }
    return $k;
}

if ($method === 'GET') {
    $action = $_GET['action'] ?? '';
    $mode = mode_of($_GET['mode'] ?? 'paper');

    if ($action === 'positions') {
        $k = keys_or_die($uid, $mode);
        list($code, $body) = plat_alpaca($mode, $k['key'], $k['secret'], '/v2/positions');
        if ($code !== 200 || !is_array($body)) {
            plat_json(502, ['error' => 'Could not load positions.']);
        }
        $out = array_map(function ($p) {
            return [
                'symbol' => $p['symbol'] ?? '', 'qty' => $p['qty'] ?? '0',
                'avg_entry' => $p['avg_entry_price'] ?? null, 'current' => $p['current_price'] ?? null,
                'market_value' => $p['market_value'] ?? null, 'unrealized_pl' => $p['unrealized_pl'] ?? null,
                'unrealized_plpc' => $p['unrealized_plpc'] ?? null, 'side' => $p['side'] ?? 'long',
            ];
        }, $body);
        plat_json(200, ['positions' => $out]);
    }

    if ($action === 'orders') {
        $k = keys_or_die($uid, $mode);
        list($code, $body) = plat_alpaca($mode, $k['key'], $k['secret'], '/v2/orders?status=all&limit=40&direction=desc');
        if ($code !== 200 || !is_array($body)) {
            plat_json(502, ['error' => 'Could not load orders.']);
        }
        $out = array_map(function ($o) {
            return [
                'symbol' => $o['symbol'] ?? '', 'side' => $o['side'] ?? '', 'qty' => $o['qty'] ?? '',
                'type' => $o['type'] ?? '', 'status' => $o['status'] ?? '',
                'filled_avg_price' => $o['filled_avg_price'] ?? null,
                'submitted_at' => $o['submitted_at'] ?? null,
            ];
        }, $body);
        plat_json(200, ['orders' => $out]);
    }

    if ($action === 'journal') {
        $st = plat_pdo()->prepare('SELECT symbol, side, qty, rationale, desk_pick, created_at FROM journal WHERE user_id = ? ORDER BY id DESC LIMIT 100');
        $st->execute([$uid]);
        plat_json(200, ['journal' => $st->fetchAll()]);
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

if ($action === 'journal_add') {
    $sym = clean_sym($in['symbol'] ?? '');
    if (!$sym) { plat_json(400, ['error' => 'Invalid symbol']); }
    $side = ($in['side'] ?? 'buy') === 'sell' ? 'sell' : 'buy';
    $qty = (float) ($in['qty'] ?? 0);
    $rationale = mb_substr(trim((string) ($in['rationale'] ?? '')), 0, 2000);
    $deskPick = mb_substr(trim((string) ($in['desk_pick'] ?? '')), 0, 64);
    $st = plat_pdo()->prepare('INSERT INTO journal (user_id, symbol, side, qty, rationale, desk_pick, created_at) VALUES (?,?,?,?,?,?,?)');
    $st->execute([$uid, $sym, $side, $qty, $rationale, $deskPick, time()]);
    plat_json(200, ['ok' => true]);
}

// ── Order validation shared by preview + submit ──
function build_order($in)
{
    $sym = clean_sym($in['symbol'] ?? '');
    if (!$sym) { plat_json(400, ['error' => 'Enter a valid symbol.']); }
    $side = ($in['side'] ?? '') === 'sell' ? 'sell' : 'buy';
    $qty = (float) ($in['qty'] ?? 0);
    if ($qty <= 0 || $qty > 100000) { plat_json(400, ['error' => 'Enter a quantity between 0 and 100,000.']); }
    $types = ['market', 'limit', 'stop', 'stop_limit'];
    $type = in_array(($in['type'] ?? ''), $types, true) ? $in['type'] : 'market';
    $order = ['symbol' => $sym, 'qty' => (string) $qty, 'side' => $side, 'type' => $type, 'time_in_force' => 'day'];
    if ($type === 'limit' || $type === 'stop_limit') {
        $lp = (float) ($in['limit_price'] ?? 0);
        if ($lp <= 0) { plat_json(400, ['error' => 'Limit orders need a limit price.']); }
        $order['limit_price'] = (string) $lp;
    }
    if ($type === 'stop' || $type === 'stop_limit') {
        $sp = (float) ($in['stop_price'] ?? 0);
        if ($sp <= 0) { plat_json(400, ['error' => 'Stop orders need a stop price.']); }
        $order['stop_price'] = (string) $sp;
    }
    return $order;
}

if ($action === 'preview') {
    $mode = mode_of($in['mode'] ?? 'paper');
    $k = keys_or_die($uid, $mode);
    $order = build_order($in);
    // Pull a recent price for an estimated cost (Alpaca latest trade)
    list($qc, $qb) = plat_alpaca($mode, $k['key'], $k['secret'], '/v2/stocks/' . rawurlencode($order['symbol']) . '/trades/latest');
    $px = null;
    if ($qc === 200 && isset($qb['trade']['p'])) { $px = (float) $qb['trade']['p']; }
    elseif ($order['type'] === 'limit' || $order['type'] === 'stop_limit') { $px = (float) $order['limit_price']; }
    $est = $px ? $px * (float) $order['qty'] : null;
    // buying power
    list($ac, $ab) = plat_alpaca($mode, $k['key'], $k['secret'], '/v2/account');
    $bp = ($ac === 200 && isset($ab['buying_power'])) ? (float) $ab['buying_power'] : null;
    plat_json(200, ['preview' => [
        'mode' => $mode, 'order' => $order, 'ref_price' => $px, 'est_cost' => $est, 'buying_power' => $bp,
        'enough' => ($est === null || $bp === null) ? null : ($order['side'] === 'sell' ? true : $bp >= $est),
    ]]);
}

if ($action === 'submit') {
    // Hard gate: never place without an explicit confirm from the UI's review step.
    if (($in['confirm'] ?? false) !== true) {
        plat_json(400, ['error' => 'Order not confirmed. Review and confirm first.']);
    }
    if (!plat_rate_limit('order', 30, 60)) {
        plat_json(429, ['error' => 'Slow down — too many orders in a minute.']);
    }
    $mode = mode_of($in['mode'] ?? 'paper');
    $k = keys_or_die($uid, $mode);
    $order = build_order($in);
    list($code, $body) = plat_alpaca($mode, $k['key'], $k['secret'], '/v2/orders', 'POST', $order);
    if ($code !== 200 && $code !== 201) {
        $msg = is_array($body) && isset($body['message']) ? $body['message'] : 'Order rejected by Alpaca.';
        plat_json(400, ['error' => $msg]);
    }
    // auto-journal the order (rationale/desk pick optional, added separately)
    if (isset($in['rationale']) || isset($in['desk_pick'])) {
        $st = plat_pdo()->prepare('INSERT INTO journal (user_id, symbol, side, qty, rationale, desk_pick, created_at) VALUES (?,?,?,?,?,?,?)');
        $st->execute([$uid, $order['symbol'], $order['side'], (float) $order['qty'],
            mb_substr((string) ($in['rationale'] ?? ''), 0, 2000), mb_substr((string) ($in['desk_pick'] ?? ''), 0, 64), time()]);
    }
    plat_json(200, ['ok' => true, 'order' => [
        'id' => $body['id'] ?? null, 'symbol' => $body['symbol'] ?? $order['symbol'],
        'status' => $body['status'] ?? 'submitted', 'mode' => $mode,
    ]]);
}

plat_json(400, ['error' => 'Unknown action']);
