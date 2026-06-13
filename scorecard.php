<?php
/**
 * Desk scorecard — the desk's rules-based ideas vs. buy-and-hold SPY.
 * A transparent simulation of the desk's screen over the trailing ~year, so it
 * shows a real track record immediately and rolls forward as time passes.
 * HYPOTHETICAL: no fees, slippage, taxes, or emotion. Small samples are noisy.
 *
 *   GET ?action=scorecard  -> {desk, spy, metrics, verdict, rules, universe}
 *
 * The "desk" portfolio: each day, hold an equal-weight basket of universe names
 * that pass the screen (price > 50-day SMA, 50-day > 200-day, RSI < 75);
 * decided on the prior day's data (no look-ahead). Benchmark: SPY buy & hold.
 */
require __DIR__ . '/lib_platform.php';
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$UNIVERSE = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'TSLA'];
$BENCH = 'SPY';
$RF = 0.043;
$cacheDir = ASD_DATA_DIR . '/stock-cache';
if (!is_dir($cacheDir)) { @mkdir($cacheDir, 0755, true); }

$action = $_GET['action'] ?? 'scorecard';
if ($action !== 'scorecard') {
    plat_json(400, ['error' => 'Unknown action']);
}

$cacheFile = $cacheDir . '/scorecard.json';
if (is_file($cacheFile) && (time() - filemtime($cacheFile)) < 21600) { // 6h
    echo file_get_contents($cacheFile);
    exit;
}

/* ── indicator helpers ── */
function sma_arr($v, $p) {
    $out = []; $sum = 0;
    for ($i = 0; $i < count($v); $i++) {
        $sum += $v[$i];
        if ($i >= $p) { $sum -= $v[$i - $p]; }
        $out[$i] = ($i >= $p - 1) ? $sum / $p : null;
    }
    return $out;
}
function rsi_arr($c, $p = 14) {
    $out = array_fill(0, count($c), null);
    if (count($c) <= $p) { return $out; }
    $gain = 0; $loss = 0;
    for ($i = 1; $i <= $p; $i++) { $d = $c[$i] - $c[$i - 1]; if ($d >= 0) { $gain += $d; } else { $loss -= $d; } }
    $ag = $gain / $p; $al = $loss / $p;
    $out[$p] = $al == 0 ? 100 : 100 - 100 / (1 + $ag / $al);
    for ($i = $p + 1; $i < count($c); $i++) {
        $d = $c[$i] - $c[$i - 1]; $g = $d > 0 ? $d : 0; $l = $d < 0 ? -$d : 0;
        $ag = ($ag * ($p - 1) + $g) / $p; $al = ($al * ($p - 1) + $l) / $p;
        $out[$i] = $al == 0 ? 100 : 100 - 100 / (1 + $ag / $al);
    }
    return $out;
}
/** Fetch 2y daily closes from Yahoo -> [date=>close] plus ordered dates. */
function daily_closes($sym) {
    $url = 'https://query1.finance.yahoo.com/v8/finance/chart/' . rawurlencode($sym) . '?range=2y&interval=1d';
    list($code, $d) = plat_http_get_json($url);
    $res = isset($d['chart']['result'][0]) ? $d['chart']['result'][0] : null;
    if ($code !== 200 || !$res || !isset($res['timestamp'])) { return null; }
    $ts = $res['timestamp']; $cl = $res['indicators']['quote'][0]['close'];
    $map = [];
    for ($i = 0; $i < count($ts); $i++) {
        if (isset($cl[$i]) && $cl[$i] !== null) { $map[(int) $ts[$i]] = (float) $cl[$i]; }
    }
    return $map;
}

/* ── load data ── */
$spyMap = daily_closes($BENCH);
if (!$spyMap) { plat_json(502, ['error' => 'Could not load benchmark data right now.']); }
$dates = array_keys($spyMap); sort($dates);

$series = []; // sym => [date=>close]
foreach ($UNIVERSE as $s) {
    $m = daily_closes($s);
    if ($m) { $series[$s] = $m; }
}
if (empty($series)) { plat_json(502, ['error' => 'Could not load universe data right now.']); }

/* precompute indicators per symbol on the shared date axis */
$ind = [];
foreach ($series as $s => $m) {
    $closes = [];
    foreach ($dates as $d) { $closes[] = isset($m[$d]) ? $m[$d] : null; }
    // forward-fill gaps for indicator calc
    $filled = []; $prev = null;
    foreach ($closes as $c) { if ($c === null) { $c = $prev; } $filled[] = $c; $prev = $c; }
    $ind[$s] = [
        'close' => $closes, 'filled' => $filled,
        'sma50' => sma_arr($filled, 50), 'sma200' => sma_arr($filled, 200), 'rsi' => rsi_arr($filled, 14),
    ];
}

/* find first index where sma200 is valid for at least one symbol; sim trailing ~252 days */
$N = count($dates);
$startIdx = 200;
$simStart = max($startIdx + 1, $N - 252);

$deskCurve = []; $spyCurve = [];
$deskIdx = 100.0;
$spyBase = $spyMap[$dates[$simStart - 1]];
$deskRets = [];
$held = []; // sym => entry close (for position records)
$positions = [];

function passes($ind, $s, $i) {
    $c = $ind[$s]['filled'][$i]; $s50 = $ind[$s]['sma50'][$i]; $s200 = $ind[$s]['sma200'][$i]; $r = $ind[$s]['rsi'][$i];
    if ($c === null || $s50 === null || $s200 === null || $r === null) { return false; }
    return ($c > $s50 && $s50 > $s200 && $r < 75);
}

for ($i = $simStart; $i < $N; $i++) {
    // decide holdings from PRIOR day (no look-ahead)
    $basket = [];
    foreach ($series as $s => $m) { if (passes($ind, $s, $i - 1)) { $basket[] = $s; } }
    // desk daily return = equal-weight avg of basket daily returns
    $r = 0; $cnt = 0;
    foreach ($basket as $s) {
        $cPrev = $ind[$s]['filled'][$i - 1]; $cNow = $ind[$s]['filled'][$i];
        if ($cPrev && $cNow) { $r += ($cNow / $cPrev - 1); $cnt++; }
    }
    $dayRet = $cnt ? $r / $cnt : 0; // cash when nothing qualifies
    $deskRets[] = $dayRet;
    $deskIdx *= (1 + $dayRet);
    $deskCurve[] = ['t' => $dates[$i], 'v' => round($deskIdx, 3)];
    $spyCurve[] = ['t' => $dates[$i], 'v' => round($spyMap[$dates[$i]] / $spyBase * 100, 3)];

    // position tracking (per symbol holding runs)
    foreach ($series as $s => $m) {
        $in = in_array($s, $basket, true);
        if ($in && !isset($held[$s])) { $held[$s] = $ind[$s]['filled'][$i]; }
        elseif (!$in && isset($held[$s])) {
            $entry = $held[$s]; $exit = $ind[$s]['filled'][$i];
            if ($entry && $exit) { $positions[] = ['symbol' => $s, 'ret' => $exit / $entry - 1]; }
            unset($held[$s]);
        }
    }
}
// close open positions at last price (mark)
foreach ($held as $s => $entry) {
    $exit = $ind[$s]['filled'][$N - 1];
    if ($entry && $exit) { $positions[] = ['symbol' => $s, 'ret' => $exit / $entry - 1, 'open' => true]; }
}

/* ── metrics ── */
$deskCum = $deskIdx / 100 - 1;
$spyCum = $spyMap[$dates[$N - 1]] / $spyBase - 1;
$mean = array_sum($deskRets) / max(1, count($deskRets));
$var = 0; foreach ($deskRets as $x) { $var += pow($x - $mean, 2); }
$sd = sqrt($var / max(1, count($deskRets)));
$sharpe = $sd > 0 ? ($mean * 252 - $RF) / ($sd * sqrt(252)) : null;
// max drawdown of desk curve
$peak = 0; $maxDD = 0;
foreach ($deskCurve as $pt) { if ($pt['v'] > $peak) { $peak = $pt['v']; } $dd = ($pt['v'] - $peak) / $peak; if ($dd < $maxDD) { $maxDD = $dd; } }
$wins = array_filter($positions, function ($p) { return $p['ret'] > 0; });
$losses = array_filter($positions, function ($p) { return $p['ret'] <= 0; });
$avgWin = count($wins) ? array_sum(array_map(function ($p) { return $p['ret']; }, $wins)) / count($wins) : 0;
$avgLoss = count($losses) ? array_sum(array_map(function ($p) { return $p['ret']; }, $losses)) / count($losses) : 0;
$winRate = count($positions) ? count($wins) / count($positions) : 0;

$beat = $deskCum > $spyCum;
$diff = ($deskCum - $spyCum) * 100;
$verdict = 'Over this window the desk\'s rules ' . ($beat ? 'edged ahead of' : 'trailed') . ' a simple SPY buy-and-hold by ' .
    number_format(abs($diff), 1) . ' percentage points. This is a hypothetical, rules-based simulation over about a year — a short, noisy sample with no fees, slippage, taxes, or emotion. It is not evidence the desk can beat the market going forward, and most active strategies underperform a simple index fund over time.';

$out = [
    'as_of' => date('c'),
    'window_days' => count($deskCurve),
    'universe' => $UNIVERSE,
    'rules' => 'Each day, hold an equal-weight basket of universe names where price > 50-day average, 50-day > 200-day, and RSI < 75 (decided on the prior day to avoid look-ahead); otherwise cash. Benchmark: SPY buy & hold.',
    'desk' => ['curve' => $deskCurve, 'cum_pct' => round($deskCum * 100, 2)],
    'spy'  => ['curve' => $spyCurve, 'cum_pct' => round($spyCum * 100, 2)],
    'metrics' => [
        'desk_cum_pct' => round($deskCum * 100, 2), 'spy_cum_pct' => round($spyCum * 100, 2),
        'sharpe' => $sharpe === null ? null : round($sharpe, 2),
        'max_drawdown_pct' => round($maxDD * 100, 2),
        'trades' => count($positions), 'win_rate_pct' => round($winRate * 100, 1),
        'avg_win_pct' => round($avgWin * 100, 2), 'avg_loss_pct' => round($avgLoss * 100, 2),
    ],
    'beat_market' => $beat,
    'verdict' => $verdict,
    'hypothetical' => true,
];
$json = json_encode($out, JSON_UNESCAPED_UNICODE);
@file_put_contents($cacheFile, $json, LOCK_EX);
echo $json;
