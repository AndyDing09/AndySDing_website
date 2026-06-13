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
@set_time_limit(120); // the full build makes ~15 sequential upstream calls
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

define('BRIEF_SCHEMA', 3); // bump when the JSON shape changes so caches self-refresh
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
/** Crude keyword read of a headline: +1 likely-positive, -1 likely-negative, 0 neutral. */
function b_headline_dir($title) {
    $t = ' ' . strtolower((string) $title) . ' ';
    $pos = ['beat', 'beats', 'tops', 'surge', 'soar', 'jump', 'rally', 'rallies', 'upgrade', 'raises', 'raised', 'record', 'all-time high', 'strong', 'growth', 'outperform', 'buy rating', 'wins', 'awarded', 'approval', 'approved', 'partnership', 'expansion', 'profit', 'gains', 'rises', 'boom', 'bullish', 'breakthrough', 'buyback', 'dividend', 'beat estimates', 'better-than', 'better than', 'tops estimates'];
    $neg = ['miss', 'misses', 'missed', 'plunge', 'drop', 'falls', 'slump', 'sinks', 'downgrade', 'cuts', 'cut', 'lawsuit', 'sued', 'probe', 'investigation', 'recall', 'warns', 'warning', 'weak', 'decline', 'loss', 'losses', 'layoff', 'bankruptcy', 'fraud', 'slowdown', 'bearish', 'underperform', 'sell rating', 'halts', 'delay', 'delayed', 'concerns', 'fears', 'slips', 'tumble', 'crash', 'worse-than', 'worse than', 'misses estimates', 'subpoena', 'antitrust'];
    $s = 0;
    foreach ($pos as $w) { if (strpos($t, ' ' . $w) !== false || strpos($t, $w . ' ') !== false || strpos($t, $w) !== false) { $s++; } }
    foreach ($neg as $w) { if (strpos($t, $w) !== false) { $s--; } }
    return $s > 0 ? 1 : ($s < 0 ? -1 : 0);
}
function b_news($sym, $n = 3) {
    $url = 'https://query1.finance.yahoo.com/v1/finance/search?q=' . rawurlencode($sym) . '&newsCount=' . $n . '&quotesCount=0';
    list($code, $d) = plat_http_get_json($url);
    $out = [];
    if ($code === 200 && isset($d['news']) && is_array($d['news'])) {
        foreach (array_slice($d['news'], 0, $n) as $it) {
            $title = $it['title'] ?? '';
            $out[] = ['title' => $title, 'publisher' => $it['publisher'] ?? '', 'link' => $it['link'] ?? '', 'time' => $it['providerPublishTime'] ?? null, 'dir' => b_headline_dir($title)];
        }
    }
    return $out;
}
/** Aggregate the headlines into a short, two-sided "how this news might move the stock" read. */
function b_news_read($news) {
    if (!$news) { return ['lean' => 0, 'text' => 'No fresh headlines — price will likely follow the broader tape and the next catalyst rather than stock-specific news.']; }
    $s = 0; foreach ($news as $n) { $s += $n['dir']; }
    if ($s > 0) { return ['lean' => 1, 'text' => 'Headlines skew positive (upgrades / beats / strong demand). News like this tends to pull a stock up — but markets often price good news in quickly, so a pop can fade if it was already expected.']; }
    if ($s < 0) { return ['lean' => -1, 'text' => 'Headlines skew negative (downgrades / misses / legal or demand worries). News like this tends to pressure a stock down — though if the bad news was already feared, the drop may be limited or even reverse.']; }
    return ['lean' => 0, 'text' => 'Headlines look mixed or neutral — no clear directional tilt. Moves here are more likely to come from the overall market than from these stories.'];
}
function rnd($v, $d = 2) { return $v === null ? null : round($v, $d); }

/** Build a plain-English, do-this-then-that game plan from the computed levels. Educational, not advice. */
function b_plan($price, $sup, $res, $sma50, $sma20, $atr, $entry) {
    $f = function ($v) { return '$' . number_format((float) $v, 2); };
    $steps = [];
    if (!$entry) {
        $steps[] = 'No clean setup today. The disciplined move is usually to wait — most money is lost forcing trades that aren\'t there.';
        $steps[] = 'Put it on your watchlist. What would change things: a reclaim of the 50-day (' . $f($sma50) . ') or a clear bounce off support (' . $f($sup) . ').';
        $steps[] = 'Only when that happens, look at an entry near support with a stop just below it.';
        $steps[] = 'Never average down into a falling stock just because it\'s "cheaper" — that\'s how small losses become big ones.';
        return $steps;
    }
    $type = $entry['type']; $stop = $entry['stop']; $target = $entry['target']; $ref = $price;
    if ($type === 'Dip-buy watch') { $steps[] = 'WAIT for the drop to steady near support (' . $f($sup) . ') — a green day or a higher low — instead of catching a falling knife.'; $ref = $price; }
    elseif ($type === 'Breakout watch') { $steps[] = 'WAIT for a daily CLOSE above ' . $f($res) . ' (ideally on heavy volume). No close above it = no trade yet.'; $ref = $res; }
    elseif ($type === 'Trend-pullback watch') { $steps[] = 'WAIT for the pullback to reach the 50-day (' . $f($sma50) . ') and actually bounce (a green candle, or it holds the level).'; $ref = $sma50; }
    elseif ($type === 'Caution (no entry)') {
        $steps[] = 'DON\'T chase here — it\'s overbought/extended. Sit on your hands; chasing green candles is the #1 beginner mistake.';
        $steps[] = 'Set a price alert for a cooldown toward ' . $f($sma20 ?: $sma50) . ' (the 20/50-day). Revisit the idea only then.';
        $steps[] = 'If you ALREADY own it: consider trimming some into the strength and/or trailing a stop up to lock in gains.';
        return $steps;
    }
    else { $steps[] = 'Trend is up — only act on PULLBACKS toward the 50-day (' . $f($sma50) . '). Don\'t buy right after a big up day.'; $ref = $sma50; }

    if ($stop !== null) {
        $risk = abs($ref - $stop);
        $steps[] = 'SIZE IT FIRST (this is the most important step): your stop sits at ' . $f($stop) . ', so you\'d risk about ' . $f($risk) . ' per share. Risk only ~1% of your account on the trade → shares ≈ (1% of your account) ÷ ' . $f($risk) . '.';
    }
    if ($type === 'Breakout watch') { $steps[] = 'ENTER only after it confirms — buy on the close above ' . $f($res) . ', or wait for a small pullback back to that level. A buy-stop order can automate this.'; }
    else { $steps[] = 'ENTER with a LIMIT order around ' . $entry['zone'] . ' (a limit, not market, so you don\'t overpay on a spike).'; }
    if ($stop !== null) { $steps[] = 'PROTECT it immediately: place a stop-loss at ' . $f($stop) . '. That\'s your "I was wrong" line — honor it; don\'t widen it to hope.'; }
    if ($target !== null) { $steps[] = 'TAKE PROFITS at the first target near ' . $f($target) . ' (around resistance ' . $f($res) . '). A common move: sell ~half there, then trail a stop on the rest.'; }
    $steps[] = 'MANAGE: check once a day, not every tick. As it works in your favor, ratchet your stop UP toward break-even — never move it down.';
    return $steps;
}

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
        if ($sma50 !== null) { $m = ($price > $sma50 ? 'Above' : 'Below') . ' the 50-day average.'; if ($price > $sma50) { $bull[] = $m; } else { $bear[] = $m; } }
        if ($sma200 !== null) { $m = ($price > $sma200 ? 'Above' : 'Below') . ' the 200-day (longer-term ' . ($price > $sma200 ? 'uptrend' : 'downtrend') . ').'; if ($price > $sma200) { $bull[] = $m; } else { $bear[] = $m; } }
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
            'plan' => b_plan($price, $sup20, $res20, $sma50, $sma20, $atr, $entry),
            'news' => [], // filled below for watch picks only (to limit calls)
        ];
    }

    // ── rank "stocks to watch today" (top by trigger score), attach news ──
    usort($cards, function ($a, $b) { return $b['score'] - $a['score']; });
    $watch = array_slice(array_filter($cards, function ($c) { return $c['score'] > 0; }), 0, 5);
    foreach ($watch as &$w) { $w['news'] = b_news($w['symbol'], 3); $w['news_read'] = b_news_read($w['news']); }
    unset($w);

    return [
        'schema' => BRIEF_SCHEMA,
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

// action=today: serve stored; rebuild if missing, stale (>18h), or an old schema
if (is_file($cacheFile) && (time() - filemtime($cacheFile)) < 64800) {
    $cached = file_get_contents($cacheFile);
    $j = json_decode($cached, true);
    if (is_array($j) && (int) ($j['schema'] ?? 0) >= BRIEF_SCHEMA) {
        echo $cached;
        exit;
    }
}
$b = build_briefing($UNIVERSE, $INDICES);
@file_put_contents($cacheFile, json_encode($b, JSON_UNESCAPED_UNICODE), LOCK_EX);
echo json_encode($b, JSON_UNESCAPED_UNICODE);
