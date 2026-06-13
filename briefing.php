<?php
/**
 * Morning Desk Briefing — server-side, schedulable, cached.
 *   GET ?action=today           -> the stored briefing (builds if missing/stale)
 *   GET ?action=build&token=XXX -> force-rebuild (for the morning cron)
 *
 * Produces: market overview + regime, "stocks to watch today" (ranked by a
 * documented trigger) each with two-sided notes, daily news, and ILLUSTRATIVE
 * entry/stop/target levels, plus the full two-sided idea list. Stored as JSON
 * in asd-site-data/briefing-today.json so the cron can refresh it each morning
 * and the page loads instantly. Educational only — not advice, not predictions.
 *
 * Cron token lives in asd-site-data/cron-token.txt (so only your cron can build).
 */
require __DIR__ . '/lib_platform.php';
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$UNIVERSE = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'TSLA'];
$INDICES = [['SPY', 'S&P 500'], ['QQQ', 'Nasdaq 100'], ['DIA', 'Dow 30'], ['^VIX', 'VIX']];
$cacheFile = ASD_DATA_DIR . '/briefing-today.json';

/* ── small indicator helpers (self-contained to avoid clashes) ── */
function b_sma($v, $p) {
    $o = []; $s = 0;
    for ($i = 0; $i < count($v); $i++) { $s += $v[$i]; if ($i >= $p) { $s -= $v[$i - $p]; } $o[$i] = $i >= $p - 1 ? $s / $p : null; }
    return $o;
}
function b_rsi($c, $p = 14) {
    $o = array_fill(0, count($c), null);
    if (count($c) <= $p) { return $o; }
    $g = 0; $l = 0;
    for ($i = 1; $i <= $p; $i++) { $d = $c[$i] - $c[$i - 1]; $d >= 0 ? $g += $d : $l -= $d; }
    $ag = $g / $p; $al = $l / $p; $o[$p] = $al == 0 ? 100 : 100 - 100 / (1 + $ag / $al);
    for ($i = $p + 1; $i < count($c); $i++) { $d = $c[$i] - $c[$i - 1]; $ag = ($ag * ($p - 1) + max($d, 0)) / $p; $al = ($al * ($p - 1) + max(-$d, 0)) / $p; $o[$i] = $al == 0 ? 100 : 100 - 100 / (1 + $ag / $al); }
    return $o;
}
function b_atr($h, $l, $c, $p = 14) {
    $tr = [$h[0] - $l[0]];
    for ($i = 1; $i < count($c); $i++) { $tr[] = max($h[$i] - $l[$i], abs($h[$i] - $c[$i - 1]), abs($l[$i] - $c[$i - 1])); }
    $k = 2 / ($p + 1); $e = $tr[0]; for ($i = 1; $i < count($tr); $i++) { $e = $tr[$i] * $k + $e * (1 - $k); }
    return $e;
}
function b_daily($sym) {
    $url = 'https://query1.finance.yahoo.com/v8/finance/chart/' . rawurlencode($sym) . '?range=1y&interval=1d';
    list($code, $d) = plat_http_get_json($url);
    $res = isset($d['chart']['result'][0]) ? $d['chart']['result'][0] : null;
    if ($code !== 200 || !$res || !isset($res['timestamp'])) { return null; }
    $q = $res['indicators']['quote'][0];
    $o = ['t' => [], 'o' => [], 'h' => [], 'l' => [], 'c' => [], 'name' => isset($res['meta']['shortName']) ? $res['meta']['shortName'] : $sym];
    for ($i = 0; $i < count($res['timestamp']); $i++) {
        if (!isset($q['close'][$i]) || $q['close'][$i] === null) { continue; }
        $o['t'][] = (int) $res['timestamp'][$i]; $o['c'][] = (float) $q['close'][$i];
        $o['h'][] = (float) ($q['high'][$i] ?? $q['close'][$i]); $o['l'][] = (float) ($q['low'][$i] ?? $q['close'][$i]);
        $o['o'][] = (float) ($q['open'][$i] ?? $q['close'][$i]);
    }
    return count($o['c']) > 60 ? $o : null;
}
function b_news($sym, $n = 3) {
    $url = 'https://query1.finance.yahoo.com/v1/finance/search?q=' . rawurlencode($sym) . '&newsCount=' . $n . '&quotesCount=0';
    list($code, $d) = plat_http_get_json($url);
    $out = [];
    if ($code === 200 && isset($d['news']) && is_array($d['news'])) {
        foreach (array_slice($d['news'], 0, $n) as $it) {
            $out[] = ['title' => $it['title'] ?? '', 'publisher' => $it['publisher'] ?? '', 'link' => $it['link'] ?? '', 'time' => $it['providerPublishTime'] ?? null];
        }
    }
    return $out;
}
function rnd($v, $d = 2) { return $v === null ? null : round($v, $d); }

function build_briefing($UNIVERSE, $INDICES)
{
    $L = function ($a) { return $a ? end($a) : null; };

    // ── market overview ──
    $indices = [];
    $spyTrend = null;
    foreach ($INDICES as $ix) {
        $d = b_daily($ix[0]);
        if (!$d) { $indices[] = ['name' => $ix[1], 'price' => null]; continue; }
        $c = $d['c']; $price = end($c); $prev = count($c) > 1 ? $c[count($c) - 2] : $price;
        $indices[] = ['name' => $ix[1], 'symbol' => $ix[0], 'price' => rnd($price), 'changePct' => $prev ? rnd(($price - $prev) / $prev * 100) : null];
        if ($ix[0] === 'SPY') { $sma50 = $L(b_sma($c, 50)); $spyTrend = ($sma50 !== null && $price > $sma50); }
        if ($ix[0] === '^VIX') { $vix = $price; }
    }
    $vix = isset($vix) ? $vix : null;
    $regime = 'mixed';
    if ($vix !== null && $spyTrend !== null) {
        if ($vix < 16 && $spyTrend) { $regime = 'calm / risk-on — low volatility and the S&P is above its 50-day average'; }
        elseif ($vix > 26) { $regime = 'stressed / risk-off — elevated volatility (VIX ' . round($vix) . ')'; }
        else { $regime = ($spyTrend ? 'constructive' : 'cautious') . ' — VIX ' . round($vix) . ', S&P ' . ($spyTrend ? 'above' : 'below') . ' its 50-day'; }
    }

    // ── analyze the universe ──
    $cards = [];
    foreach ($UNIVERSE as $sym) {
        $d = b_daily($sym);
        if (!$d) { continue; }
        $c = $d['c']; $h = $d['h']; $l = $d['l'];
        $price = end($c);
        $sma20 = $L(b_sma($c, 20)); $sma50 = $L(b_sma($c, 50)); $sma200 = $L(b_sma($c, 200));
        $rsi = $L(b_rsi($c, 14)); $atr = b_atr($h, $l, $c, 14);
        $hi3 = max(array_slice($h, -63)); $lo3 = min(array_slice($l, -63));
        $sup20 = min(array_slice($l, -20)); $res20 = max(array_slice($h, -20));

        $bull = []; $bear = [];
        if ($sma50 !== null) { ($price > $sma50 ? $bull : $bear)[] = ($price > $sma50 ? 'Above' : 'Below') . ' the 50-day average.'; }
        if ($sma200 !== null) { ($price > $sma200 ? $bull : $bear)[] = ($price > $sma200 ? 'Above' : 'Below') . ' the 200-day (longer-term ' . ($price > $sma200 ? 'uptrend' : 'downtrend') . ').'; }
        if ($rsi !== null) { if ($rsi > 70) { $bear[] = 'RSI ' . round($rsi) . ' — overbought.'; } elseif ($rsi < 30) { $bull[] = 'RSI ' . round($rsi) . ' — oversold.'; } else { $bull[] = 'RSI ' . round($rsi) . ' — neutral.'; } }
        $bear[] = 'Typical daily swing ~$' . round($atr, 2) . ' (ATR) — size for it.';

        // ── trigger + illustrative entry/stop/target ──
        $trigger = null; $score = 0; $entry = null;
        $up = ($sma50 !== null && $price > $sma50) && ($sma200 === null || $price > $sma200);
        if ($rsi !== null && $rsi < 38 && ($sma200 === null || $price > $sma200)) {
            $trigger = 'Oversold pullback in an uptrend'; $score = 5;
            $entry = ['type' => 'Dip-buy watch', 'zone' => rnd(max($sup20, $price * 0.985)) . '–' . rnd($price),
                'stop' => rnd($sup20 - 1.0 * $atr), 'target' => rnd($sma50 ?: $res20),
                'note' => 'A trader watching a bounce might look near recent support (~$' . rnd($sup20) . '), with a stop below it.'];
        } elseif ($up && $price <= $hi3 * 1.03 && $price >= $hi3 * 0.97) {
            $trigger = 'Near a breakout'; $score = 4;
            $entry = ['type' => 'Breakout watch', 'zone' => 'on a daily close above ' . rnd($res20),
                'stop' => rnd($res20 - 1.5 * $atr), 'target' => rnd($price + ($price - $sma50 > 0 ? ($hi3 - $lo3) * 0.5 : 2 * $atr)),
                'note' => 'Watching for a close above the recent high (~$' . rnd($res20) . '); failure back below it would negate it.'];
        } elseif ($up && $sma50 !== null && $price <= $sma50 * 1.03) {
            $trigger = 'Pullback toward the 50-day'; $score = 3;
            $entry = ['type' => 'Trend-pullback watch', 'zone' => rnd($sma50) . '–' . rnd($price),
                'stop' => rnd($sma50 - 1.5 * $atr), 'target' => rnd($res20),
                'note' => 'Uptrend names often find buyers near the 50-day (~$' . rnd($sma50) . ').'];
        } elseif ($rsi !== null && $rsi > 75) {
            $trigger = 'Overbought — caution'; $score = 2;
            $entry = ['type' => 'Caution (no entry)', 'zone' => 'wait for a pullback toward ' . rnd($sma20 ?: $sma50),
                'stop' => null, 'target' => null,
                'note' => 'Extended; chasing here carries pullback risk. Some watch for a cooldown to the 20/50-day.'];
        } elseif ($up) {
            $trigger = 'Healthy uptrend'; $score = 1;
            $entry = ['type' => 'Trend watch', 'zone' => 'pullbacks toward ' . rnd($sma50),
                'stop' => rnd(($sma50 ?: $price) - 1.5 * $atr), 'target' => rnd($res20),
                'note' => 'In an uptrend; pullbacks toward the 50-day are where some look for entries.'];
        }

        $cards[] = [
            'symbol' => $sym, 'name' => $d['name'], 'price' => rnd($price),
            'rsi' => rnd($rsi, 0), 'sma50' => rnd($sma50), 'sma200' => rnd($sma200), 'atr' => rnd($atr),
            'support' => rnd($sup20), 'resistance' => rnd($res20),
            'bull' => $bull, 'bear' => $bear,
            'trigger' => $trigger, 'score' => $score, 'entry' => $entry,
            'news' => [], // filled below for watch picks only (to limit calls)
        ];
    }

    // ── rank "stocks to watch today" (top by trigger score), attach news ──
    usort($cards, function ($a, $b) { return $b['score'] - $a['score']; });
    $watch = array_slice(array_filter($cards, function ($c) { return $c['score'] > 0; }), 0, 5);
    foreach ($watch as &$w) { $w['news'] = b_news($w['symbol'], 3); }
    unset($w);

    return [
        'generated_at' => date('c'),
        'market' => ['indices' => $indices, 'regime' => $regime],
        'watch' => array_values($watch),
        'ideas' => $cards,
        'disclaimer' => 'Educational analysis only — not financial advice and not a prediction. Entry/stop levels are illustrative examples of what a trader might watch, not recommendations. Most active traders underperform a simple index fund. Do your own research.',
    ];
}

$action = $_GET['action'] ?? 'today';

if ($action === 'build') {
    $tokenFile = ASD_DATA_DIR . '/cron-token.txt';
    $expected = is_file($tokenFile) ? trim((string) file_get_contents($tokenFile)) : '';
    $given = trim((string) ($_GET['token'] ?? ''));
    if ($expected === '' || !hash_equals($expected, $given)) {
        plat_json(403, ['error' => 'Bad or missing cron token']);
    }
    $b = build_briefing($UNIVERSE, $INDICES);
    @file_put_contents($cacheFile, json_encode($b, JSON_UNESCAPED_UNICODE), LOCK_EX);
    plat_json(200, ['ok' => true, 'generated_at' => $b['generated_at'], 'watch' => count($b['watch'])]);
}

// action=today: serve stored; rebuild if missing or older than 18h
if (is_file($cacheFile) && (time() - filemtime($cacheFile)) < 64800) {
    echo file_get_contents($cacheFile);
    exit;
}
$b = build_briefing($UNIVERSE, $INDICES);
@file_put_contents($cacheFile, json_encode($b, JSON_UNESCAPED_UNICODE), LOCK_EX);
echo json_encode($b, JSON_UNESCAPED_UNICODE);
