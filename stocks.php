<?php
/**
 * AndyStockAnalysis — market data proxy.
 *
 * Fetches Yahoo Finance's free public JSON endpoints server-side (avoiding
 * browser CORS), caches responses on disk to respect rate limits, and
 * returns trimmed JSON to the front end. Same cURL pattern as chat.php.
 *
 *   GET ?action=quotes&symbols=AAPL,MSFT     -> batch mini-quotes + sparklines
 *   GET ?action=chart&symbol=AAPL&range=1y&interval=1d  -> OHLCV history
 *   GET ?action=fundamentals&symbol=AAPL     -> valuation/financials/profile
 *   GET ?action=news&symbol=AAPL             -> recent headlines
 *
 * Data is delayed (~15 min) and these endpoints are unofficial; the data
 * layer in stocks.js is abstracted so a keyed provider can be swapped in.
 */

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$parent  = dirname(__DIR__);
$dataDir  = is_writable($parent) ? $parent . '/asd-site-data' : __DIR__ . '/site-data';
$cacheDir = $dataDir . '/stock-cache';
if (!is_dir($cacheDir)) {
    @mkdir($cacheDir, 0755, true);
}

function respond($code, $payload)
{
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    exit;
}

/** Validate a ticker: letters, digits, dot, dash, caret (^GSPC), equals (FX). */
function clean_symbol($s)
{
    $s = strtoupper(trim((string) $s));
    return preg_match('/^[A-Z0-9.\-\^=]{1,15}$/', $s) ? $s : null;
}

function cache_path($cacheDir, $key)
{
    return $cacheDir . '/' . preg_replace('/[^A-Za-z0-9_.\-]/', '_', $key) . '.json';
}
function cache_get($file, $ttl)
{
    if (is_file($file) && (time() - filemtime($file)) < $ttl) {
        $d = file_get_contents($file);
        return $d !== false && $d !== '' ? $d : null;
    }
    return null;
}
function cache_put($file, $data)
{
    @file_put_contents($file, $data, LOCK_EX);
}

/** Single GET with browser-like headers. Returns [httpCode, body]. */
function http_get($url, $cookieFile = null)
{
    $ch = curl_init($url);
    $opts = [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 15,
        CURLOPT_CONNECTTIMEOUT => 8,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_HTTPHEADER     => [
            'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
            'Accept: application/json,text/plain,*/*',
        ],
    ];
    if ($cookieFile) {
        $opts[CURLOPT_COOKIEFILE] = $cookieFile;
        $opts[CURLOPT_COOKIEJAR]  = $cookieFile;
    }
    curl_setopt_array($ch, $opts);
    $body = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    return [$code, $body];
}

/** Parallel GET for the batch-quotes endpoint. $urls keyed by symbol. */
function http_get_multi($urls)
{
    $mh = curl_multi_init();
    $handles = [];
    foreach ($urls as $key => $url) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => 15,
            CURLOPT_CONNECTTIMEOUT => 8,
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_HTTPHEADER     => [
                'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
                'Accept: application/json,text/plain,*/*',
            ],
        ]);
        curl_multi_add_handle($mh, $ch);
        $handles[$key] = $ch;
    }
    $running = null;
    do {
        curl_multi_exec($mh, $running);
        curl_multi_select($mh, 0.5);
    } while ($running > 0);

    $out = [];
    foreach ($handles as $key => $ch) {
        $out[$key] = curl_multi_getcontent($ch);
        curl_multi_remove_handle($mh, $ch);
        curl_close($ch);
    }
    curl_multi_close($mh);
    return $out;
}

/**
 * Yahoo requires a crumb + cookie for quoteSummary (fundamentals). Fetch and
 * cache the crumb for ~6 hours. Returns [crumb|null, cookieFile].
 */
function yahoo_crumb($cacheDir)
{
    $cookieFile = $cacheDir . '/yahoo-cookies.txt';
    $crumbFile  = $cacheDir . '/yahoo-crumb.txt';
    if (is_file($crumbFile) && (time() - filemtime($crumbFile)) < 21600) {
        $c = trim((string) file_get_contents($crumbFile));
        if ($c !== '') {
            return [$c, $cookieFile];
        }
    }
    // 1. Hit a Yahoo page to receive the consent cookie.
    http_get('https://fc.yahoo.com', $cookieFile);
    // 2. Exchange the cookie for a crumb.
    list($code, $crumb) = http_get('https://query1.finance.yahoo.com/v1/test/getcrumb', $cookieFile);
    $crumb = trim((string) $crumb);
    if ($code === 200 && $crumb !== '' && strlen($crumb) < 40 && strpos($crumb, '<') === false) {
        cache_put($crumbFile, $crumb);
        return [$crumb, $cookieFile];
    }
    return [null, $cookieFile];
}

$action = isset($_GET['action']) ? $_GET['action'] : '';

/* ─────────────────────────────────────────────
   REALTIME — near-real-time quotes via Finnhub
   (key hidden in asd-site-data/finnhub-key.txt; ~1-2s fresh, not delayed).
   Falls back silently to delayed Yahoo quotes when no key is present.
───────────────────────────────────────────── */
if ($action === 'rtstatus') {
    $kf = $dataDir . '/finnhub-key.txt';
    $on = is_file($kf) && trim((string) file_get_contents($kf)) !== '';
    respond(200, ['enabled' => $on, 'source' => $on ? 'finnhub' : 'yahoo']);
}
if ($action === 'realtime') {
    $kf = $dataDir . '/finnhub-key.txt';
    $key = is_file($kf) ? trim((string) file_get_contents($kf)) : '';
    if ($key === '') {
        respond(200, ['enabled' => false]);
    }
    $raw = isset($_GET['symbols']) ? explode(',', $_GET['symbols']) : [];
    $symbols = [];
    foreach ($raw as $s) {
        $c = clean_symbol($s);
        if ($c && !in_array($c, $symbols, true)) {
            $symbols[] = $c;
        }
    }
    if (empty($symbols) || count($symbols) > 30) {
        respond(400, ['error' => 'Provide 1–30 symbols']);
    }
    $out = [];
    $toFetch = [];
    foreach ($symbols as $sym) {
        $cached = cache_get(cache_path($cacheDir, "rt_$sym"), 1); // 1-second cache
        if ($cached !== null) {
            $out[$sym] = json_decode($cached, true);
        } else {
            $toFetch[$sym] = 'https://finnhub.io/api/v1/quote?symbol=' . rawurlencode($sym)
                . '&token=' . rawurlencode($key);
        }
    }
    if (!empty($toFetch)) {
        $bodies = http_get_multi($toFetch);
        foreach ($bodies as $sym => $body) {
            $d = json_decode((string) $body, true);
            $q = ['ok' => false, 'symbol' => $sym];
            if (is_array($d) && isset($d['c']) && $d['c'] > 0) {
                $q = [
                    'ok'        => true,
                    'symbol'    => $sym,
                    'price'     => $d['c'],
                    'change'    => isset($d['d']) ? $d['d'] : null,
                    'changePct' => isset($d['dp']) ? $d['dp'] : null,
                    'prevClose' => isset($d['pc']) ? $d['pc'] : null,
                    't'         => isset($d['t']) ? $d['t'] : null,
                ];
            }
            cache_put(cache_path($cacheDir, "rt_$sym"), json_encode($q));
            $out[$sym] = $q;
        }
    }
    respond(200, ['enabled' => true, 'source' => 'finnhub', 'quotes' => $out]);
}

/* ─────────────────────────────────────────────
   QUOTES — batch mini-quote + sparkline
───────────────────────────────────────────── */
if ($action === 'quotes') {
    $raw = isset($_GET['symbols']) ? explode(',', $_GET['symbols']) : [];
    $symbols = [];
    foreach ($raw as $s) {
        $c = clean_symbol($s);
        if ($c && !in_array($c, $symbols, true)) {
            $symbols[] = $c;
        }
    }
    if (empty($symbols) || count($symbols) > 30) {
        respond(400, ['error' => 'Provide 1–30 symbols']);
    }

    $quotes = [];
    $toFetch = [];
    foreach ($symbols as $sym) {
        $cached = cache_get(cache_path($cacheDir, "quote_$sym"), 60);
        if ($cached !== null) {
            $quotes[$sym] = json_decode($cached, true);
        } else {
            $toFetch[$sym] = 'https://query1.finance.yahoo.com/v8/finance/chart/'
                . rawurlencode($sym) . '?range=1d&interval=5m&includePrePost=false';
        }
    }

    if (!empty($toFetch)) {
        $bodies = http_get_multi($toFetch);
        foreach ($bodies as $sym => $body) {
            $q = ['symbol' => $sym, 'ok' => false];
            $data = json_decode((string) $body, true);
            $res = isset($data['chart']['result'][0]) ? $data['chart']['result'][0] : null;
            if ($res && isset($res['meta'])) {
                $m = $res['meta'];
                $price = isset($m['regularMarketPrice']) ? $m['regularMarketPrice'] : null;
                $prev  = isset($m['chartPreviousClose']) ? $m['chartPreviousClose']
                       : (isset($m['previousClose']) ? $m['previousClose'] : null);
                $spark = [];
                if (isset($res['indicators']['quote'][0]['close'])) {
                    foreach ($res['indicators']['quote'][0]['close'] as $c) {
                        if ($c !== null) {
                            $spark[] = round($c, 4);
                        }
                    }
                }
                if (count($spark) > 60) { // thin to ~60 points
                    $step = ceil(count($spark) / 60);
                    $thin = [];
                    for ($i = 0; $i < count($spark); $i += $step) {
                        $thin[] = $spark[$i];
                    }
                    $spark = $thin;
                }
                $q = [
                    'symbol'      => $sym,
                    'ok'          => $price !== null,
                    'name'        => isset($m['longName']) ? $m['longName'] : (isset($m['shortName']) ? $m['shortName'] : $sym),
                    'price'       => $price,
                    'prevClose'   => $prev,
                    'change'      => ($price !== null && $prev) ? round($price - $prev, 4) : null,
                    'changePct'   => ($price !== null && $prev) ? round((($price - $prev) / $prev) * 100, 2) : null,
                    'currency'    => isset($m['currency']) ? $m['currency'] : 'USD',
                    'marketState' => isset($m['marketState']) ? $m['marketState'] : null,
                    'spark'       => $spark,
                ];
            }
            cache_put(cache_path($cacheDir, "quote_$sym"), json_encode($q));
            $quotes[$sym] = $q;
        }
    }

    respond(200, ['quotes' => $quotes, 'delayed' => true]);
}

/* ─────────────────────────────────────────────
   CHART — OHLCV history
───────────────────────────────────────────── */
if ($action === 'chart') {
    $sym = clean_symbol(isset($_GET['symbol']) ? $_GET['symbol'] : '');
    if (!$sym) {
        respond(400, ['error' => 'Invalid symbol']);
    }
    $allowedRange    = ['1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', 'max'];
    $allowedInterval = ['1m', '2m', '5m', '15m', '30m', '60m', '1d', '1wk', '1mo'];
    $range    = in_array(($_GET['range'] ?? ''), $allowedRange, true) ? $_GET['range'] : '1y';
    $interval = in_array(($_GET['interval'] ?? ''), $allowedInterval, true) ? $_GET['interval'] : '1d';

    // Intraday data changes fast (cache 2 min); daily+ is fine for 10 min.
    $ttl = in_array($interval, ['1m', '2m', '5m', '15m', '30m', '60m'], true) ? 120 : 600;
    $cacheFile = cache_path($cacheDir, "chart_{$sym}_{$range}_{$interval}");
    $cached = cache_get($cacheFile, $ttl);
    if ($cached !== null) {
        respond(200, json_decode($cached, true));
    }

    $url = 'https://query1.finance.yahoo.com/v8/finance/chart/' . rawurlencode($sym)
        . '?range=' . $range . '&interval=' . $interval;
    list($code, $body) = http_get($url);
    $data = json_decode((string) $body, true);
    $res  = isset($data['chart']['result'][0]) ? $data['chart']['result'][0] : null;
    if ($code !== 200 || !$res || !isset($res['timestamp'])) {
        respond(502, ['error' => 'Could not load chart data for ' . $sym]);
    }

    $ts   = $res['timestamp'];
    $q    = $res['indicators']['quote'][0];
    $adj  = isset($res['indicators']['adjclose'][0]['adjclose']) ? $res['indicators']['adjclose'][0]['adjclose'] : null;
    $candles = [];
    for ($i = 0; $i < count($ts); $i++) {
        if (!isset($q['close'][$i]) || $q['close'][$i] === null) {
            continue;
        }
        $candles[] = [
            't' => (int) $ts[$i],
            'o' => $q['open'][$i]  !== null ? round($q['open'][$i], 4)  : null,
            'h' => $q['high'][$i]  !== null ? round($q['high'][$i], 4)  : null,
            'l' => $q['low'][$i]   !== null ? round($q['low'][$i], 4)   : null,
            'c' => round($q['close'][$i], 4),
            'v' => isset($q['volume'][$i]) && $q['volume'][$i] !== null ? (int) $q['volume'][$i] : 0,
            'a' => ($adj && $adj[$i] !== null) ? round($adj[$i], 4) : null,
        ];
    }
    $m = $res['meta'];
    $out = [
        'symbol'   => $sym,
        'currency' => isset($m['currency']) ? $m['currency'] : 'USD',
        'name'     => isset($m['longName']) ? $m['longName'] : (isset($m['shortName']) ? $m['shortName'] : $sym),
        'range'    => $range,
        'interval' => $interval,
        'candles'  => $candles,
    ];
    cache_put($cacheFile, json_encode($out));
    respond(200, $out);
}

/* ─────────────────────────────────────────────
   FUNDAMENTALS — valuation, financials, profile
───────────────────────────────────────────── */
if ($action === 'fundamentals') {
    $sym = clean_symbol(isset($_GET['symbol']) ? $_GET['symbol'] : '');
    if (!$sym) {
        respond(400, ['error' => 'Invalid symbol']);
    }
    $cacheFile = cache_path($cacheDir, "fund_$sym");
    $cached = cache_get($cacheFile, 3600); // fundamentals change slowly
    if ($cached !== null) {
        respond(200, json_decode($cached, true));
    }

    list($crumb, $cookieFile) = yahoo_crumb($cacheDir);
    $modules = 'price,summaryDetail,defaultKeyStatistics,financialData,calendarEvents,assetProfile';
    $url = 'https://query1.finance.yahoo.com/v10/finance/quoteSummary/' . rawurlencode($sym)
        . '?modules=' . $modules;
    if ($crumb) {
        $url .= '&crumb=' . rawurlencode($crumb);
    }
    list($code, $body) = http_get($url, $cookieFile);
    $data = json_decode((string) $body, true);
    $res  = isset($data['quoteSummary']['result'][0]) ? $data['quoteSummary']['result'][0] : null;
    if ($code !== 200 || !$res) {
        respond(502, ['error' => 'Fundamentals unavailable for ' . $sym]);
    }

    // Yahoo wraps numbers as {raw, fmt}. Pull the raw value.
    $raw = function ($node, $key) {
        return (isset($node[$key]['raw'])) ? $node[$key]['raw'] : (isset($node[$key]) && !is_array($node[$key]) ? $node[$key] : null);
    };
    $price = isset($res['price']) ? $res['price'] : [];
    $sd    = isset($res['summaryDetail']) ? $res['summaryDetail'] : [];
    $ks    = isset($res['defaultKeyStatistics']) ? $res['defaultKeyStatistics'] : [];
    $fd    = isset($res['financialData']) ? $res['financialData'] : [];
    $cal   = isset($res['calendarEvents']) ? $res['calendarEvents'] : [];
    $prof  = isset($res['assetProfile']) ? $res['assetProfile'] : [];

    $earnings = null;
    if (isset($cal['earnings']['earningsDate'][0]['raw'])) {
        $earnings = $cal['earnings']['earningsDate'][0]['raw'];
    }

    $out = [
        'symbol'         => $sym,
        'name'           => $raw($price, 'longName') ?: $sym,
        'sector'         => isset($prof['sector']) ? $prof['sector'] : null,
        'industry'       => isset($prof['industry']) ? $prof['industry'] : null,
        'summary'        => isset($prof['longBusinessSummary']) ? $prof['longBusinessSummary'] : null,
        'marketCap'      => $raw($price, 'marketCap') ?: $raw($sd, 'marketCap'),
        'peTrailing'     => $raw($sd, 'trailingPE'),
        'peForward'      => $raw($ks, 'forwardPE') ?: $raw($sd, 'forwardPE'),
        'peg'            => $raw($ks, 'pegRatio'),
        'priceToBook'    => $raw($ks, 'priceToBook'),
        'priceToSales'   => $raw($sd, 'priceToSalesTrailing12Months'),
        'epsTrailing'    => $raw($ks, 'trailingEps'),
        'epsForward'     => $raw($ks, 'forwardEps'),
        'revenueGrowth'  => $raw($fd, 'revenueGrowth'),
        'earningsGrowth' => $raw($fd, 'earningsGrowth'),
        'profitMargin'   => $raw($fd, 'profitMargins') ?: $raw($ks, 'profitMargins'),
        'operatingMargin'=> $raw($fd, 'operatingMargins'),
        'roe'            => $raw($fd, 'returnOnEquity'),
        'roa'            => $raw($fd, 'returnOnAssets'),
        'debtToEquity'   => $raw($fd, 'debtToEquity'),
        'currentRatio'   => $raw($fd, 'currentRatio'),
        'freeCashflow'   => $raw($fd, 'freeCashflow'),
        'totalCash'      => $raw($fd, 'totalCash'),
        'totalDebt'      => $raw($fd, 'totalDebt'),
        'revenue'        => $raw($fd, 'totalRevenue'),
        'dividendYield'  => $raw($sd, 'dividendYield'),
        'beta'           => $raw($sd, 'beta') ?: $raw($ks, 'beta'),
        'week52High'     => $raw($sd, 'fiftyTwoWeekHigh'),
        'week52Low'      => $raw($sd, 'fiftyTwoWeekLow'),
        'targetMean'     => $raw($fd, 'targetMeanPrice'),
        'recommendation' => isset($fd['recommendationKey']) ? $fd['recommendationKey'] : null,
        'nextEarnings'   => $earnings,
        'currency'       => $raw($price, 'currency') ?: 'USD',
    ];
    cache_put($cacheFile, json_encode($out));
    respond(200, $out);
}

/* ─────────────────────────────────────────────
   NEWS — recent headlines
───────────────────────────────────────────── */
if ($action === 'news') {
    $sym = clean_symbol(isset($_GET['symbol']) ? $_GET['symbol'] : '');
    if (!$sym) {
        respond(400, ['error' => 'Invalid symbol']);
    }
    $cacheFile = cache_path($cacheDir, "news_$sym");
    $cached = cache_get($cacheFile, 900);
    if ($cached !== null) {
        respond(200, json_decode($cached, true));
    }
    $url = 'https://query1.finance.yahoo.com/v1/finance/search?q=' . rawurlencode($sym)
        . '&newsCount=10&quotesCount=0&enableFuzzyQuery=false';
    list($code, $body) = http_get($url);
    $data = json_decode((string) $body, true);
    $items = [];
    if ($code === 200 && isset($data['news']) && is_array($data['news'])) {
        foreach ($data['news'] as $n) {
            $items[] = [
                'title'     => isset($n['title']) ? $n['title'] : '',
                'publisher' => isset($n['publisher']) ? $n['publisher'] : '',
                'link'      => isset($n['link']) ? $n['link'] : '',
                'time'      => isset($n['providerPublishTime']) ? (int) $n['providerPublishTime'] : null,
            ];
        }
    }
    $out = ['symbol' => $sym, 'news' => $items];
    cache_put($cacheFile, json_encode($out));
    respond(200, $out);
}

respond(400, ['error' => 'Unknown action']);
