<?php
/**
 * Equity Research Desk — streaming AI endpoint for stock-research.html.
 *
 *  GET  -> {"ai": true|false}                       — whether the Claude layer is on
 *  POST {"prompt":"...","model":"..."} -> SSE       — streams the analyst note
 *
 * This is the PHP port of the Vercel `api/analyze.js` from the bundle: it holds
 * the Anthropic API key server-side, adds the analyst system prompt + the
 * web_search tool, calls the Anthropic Messages API with streaming, and forwards
 * simplified Server-Sent Events to the browser so the report renders as it is
 * written. The front-end (stock-research.html) consumes these events:
 *
 *   event: status  data: {"phase":"search"|"results"|"write"}
 *   event: delta   data: {"text":"..."}
 *   event: error   data: {"message":"..."}
 *   event: done    data: {}
 *
 * The key is read from asd-site-data/anthropic-key.txt — the SAME file chat.php
 * uses — which lives OUTSIDE public_html so it is never in the git repo and
 * survives clean-slate deploys. If the file is missing, the endpoint reports
 * ai:false (GET) or returns a clear error (POST).
 *
 * Cost protections (the Anthropic Console spend limit is the real backstop):
 *   • per-IP rate limit (6 runs / 15 min)
 *   • global daily cap (60 runs/day)
 *   • capped web searches + max_tokens, model allow-list.
 */

/* ── locate the server-side data dir + key (mirrors chat.php) ── */
$parent = dirname(__DIR__);
$dir = is_writable($parent) ? $parent . '/asd-site-data' : __DIR__ . '/site-data';
if (!is_dir($dir)) {
    @mkdir($dir, 0755, true);
}
$keyFile = $dir . '/anthropic-key.txt';
$apiKey = is_file($keyFile) ? trim((string) file_get_contents($keyFile)) : '';

/* ── tunables ── */
$MODEL_DEFAULT = 'claude-sonnet-4-6';                       // swap to 'claude-opus-4-8' for max depth (higher cost)
$MODELS_ALLOWED = ['claude-sonnet-4-6', 'claude-opus-4-8']; // block arbitrary models on this public endpoint
$MAX_TOKENS = 8000;
$MAX_SEARCHES = 5;          // caps web-search time so a run fits in the function/PHP time limit
$RL_PER_IP = 6;             // runs per IP …
$RL_WINDOW = 900;           // … per 15 minutes
$RL_DAILY = 60;             // global runs per day

$SYSTEM = <<<'PROMPT'
You are an elite equity research analyst at a top-tier investment fund, acting as the engine behind a stock-analysis agent. Apply these rules on every response:
1. USE THE web_search TOOL to pull current, live data — price, valuation multiples, revenue, margins, free cash flow, debt, analyst estimates, recent news — BEFORE stating any figure. Never invent or recall current numbers from memory; market data changes constantly.
2. Source the key numerical claims and flag any figure you could not verify with [VERIFY].
3. Be specific and direct. Stay genuinely adversarial wherever the framework asks for a bear case, a short-seller's view, or what could make the thesis wrong — do not soften it.
4. Follow the requested structure exactly and keep the section headings.
5. This is analytical scaffolding, not investment advice; you are not a registered investment advisor and the user must independently verify everything. State this once, briefly.
Write the response in clean markdown.
PROMPT;

/* ── GET: report whether the AI layer is available ── */
$method = isset($_SERVER['REQUEST_METHOD']) ? $_SERVER['REQUEST_METHOD'] : 'GET';
if ($method === 'GET') {
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode(['ai' => $apiKey !== '']);
    exit;
}

/* JSON error helper for the pre-stream phase */
function analyze_fail($code, $message)
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode(['error' => $message]);
    exit;
}

if ($method !== 'POST') {
    analyze_fail(405, 'Method not allowed');
}
if ($apiKey === '') {
    analyze_fail(503, 'The research desk is not enabled yet — the site owner needs to add an Anthropic API key.');
}

$input = json_decode((string) file_get_contents('php://input'), true);
$prompt = is_array($input) && isset($input['prompt']) ? (string) $input['prompt'] : '';
$prompt = trim($prompt);
if ($prompt === '') {
    analyze_fail(400, 'Missing prompt');
}
if (strlen($prompt) > 12000) {
    analyze_fail(413, 'That request is too long.');
}
$model = is_array($input) && isset($input['model']) ? (string) $input['model'] : $MODEL_DEFAULT;
if (!in_array($model, $MODELS_ALLOWED, true)) {
    $model = $MODEL_DEFAULT;
}

/* ── rate limiting: per-IP window + global daily cap (file-based, like chat.php) ── */
$now = time();
$ipHash = substr(sha1((isset($_SERVER['REMOTE_ADDR']) ? $_SERVER['REMOTE_ADDR'] : '') . 'asd-research'), 0, 12);
$rlFile = $dir . '/research-limits.json';
$fp = @fopen($rlFile, 'c+');
if ($fp) {
    flock($fp, LOCK_EX);
    $raw = stream_get_contents($fp);
    $limits = json_decode($raw !== false && $raw !== '' ? $raw : '{}', true);
    if (!is_array($limits)) {
        $limits = [];
    }
    $today = gmdate('Y-m-d');
    if (!isset($limits['day']) || $limits['day'] !== $today) {
        $limits = ['day' => $today, 'total' => 0, 'ips' => []];
    }
    $stamps = isset($limits['ips'][$ipHash]) ? $limits['ips'][$ipHash] : [];
    $stamps = array_values(array_filter($stamps, function ($t) use ($now, $RL_WINDOW) {
        return $now - $t < $RL_WINDOW;
    }));
    if (count($stamps) >= $RL_PER_IP) {
        flock($fp, LOCK_UN);
        fclose($fp);
        analyze_fail(429, "You're running the desk quickly — give it a few minutes before the next report.");
    }
    if ($limits['total'] >= $RL_DAILY) {
        flock($fp, LOCK_UN);
        fclose($fp);
        analyze_fail(429, "The desk has hit its daily run limit — try again tomorrow, or email andyding09@gmail.com.");
    }
    $stamps[] = $now;
    $limits['ips'][$ipHash] = $stamps;
    if (count($limits['ips']) > 500) {
        $limits['ips'] = array_slice($limits['ips'], -250, null, true);
    }
    $limits['total'] += 1;
    ftruncate($fp, 0);
    rewind($fp);
    fwrite($fp, json_encode($limits));
    fflush($fp);
    flock($fp, LOCK_UN);
    fclose($fp);
}

/* ── open an SSE stream to the browser ── */
@set_time_limit(120);
@ini_set('zlib.output_compression', '0');
@ini_set('output_buffering', '0');
@ini_set('implicit_flush', '1');
while (ob_get_level() > 0) {
    @ob_end_flush();
}
ob_implicit_flush(true);
ignore_user_abort(false);

header('Content-Type: text/event-stream; charset=utf-8');
header('Cache-Control: no-cache, no-transform');
header('Connection: keep-alive');
header('X-Accel-Buffering: no'); // disable proxy buffering (nginx) so deltas flush

function sse_send($event, $data)
{
    echo 'event: ' . $event . "\n";
    echo 'data: ' . json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . "\n\n";
    flush();
}

$payload = [
    'model' => $model,
    'max_tokens' => $MAX_TOKENS,
    'stream' => true,
    'system' => $SYSTEM,
    'messages' => [['role' => 'user', 'content' => $prompt]],
    'tools' => [[
        'type' => 'web_search_20250305',
        'name' => 'web_search',
        'max_uses' => $MAX_SEARCHES,
    ]],
];

/* ── parse Anthropic's SSE incrementally and forward simplified events ── */
$buffer = '';
$sawText = false;

$onChunk = function ($ch, $chunk) use (&$buffer, &$sawText) {
    if (connection_aborted()) {
        return 0; // user navigated away — abort the upstream call (stops spending)
    }
    $buffer .= $chunk;
    while (($idx = strpos($buffer, "\n\n")) !== false) {
        $rawEvent = substr($buffer, 0, $idx);
        $buffer = substr($buffer, $idx + 2);
        $dataStr = '';
        foreach (explode("\n", $rawEvent) as $ln) {
            if (strncmp($ln, 'data:', 5) === 0) {
                $dataStr .= trim(substr($ln, 5));
            }
        }
        if ($dataStr === '') {
            continue;
        }
        $evt = json_decode($dataStr, true);
        if (!is_array($evt) || !isset($evt['type'])) {
            continue;
        }
        if ($evt['type'] === 'content_block_start') {
            $t = isset($evt['content_block']['type']) ? $evt['content_block']['type'] : '';
            if ($t === 'server_tool_use') {
                sse_send('status', ['phase' => 'search']);
            } elseif ($t === 'web_search_tool_result') {
                sse_send('status', ['phase' => 'results']);
            } elseif ($t === 'text') {
                sse_send('status', ['phase' => 'write']);
            }
        } elseif ($evt['type'] === 'content_block_delta') {
            if (isset($evt['delta']['type']) && $evt['delta']['type'] === 'text_delta'
                && isset($evt['delta']['text']) && $evt['delta']['text'] !== '') {
                $sawText = true;
                sse_send('delta', ['text' => $evt['delta']['text']]);
            }
        } elseif ($evt['type'] === 'error') {
            $msg = isset($evt['error']['message']) ? $evt['error']['message'] : 'Stream error';
            sse_send('error', ['message' => $msg]);
        }
    }
    return strlen($chunk);
};

$ch = curl_init('https://api.anthropic.com/v1/messages');
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_HTTPHEADER => [
        'x-api-key: ' . $apiKey,
        'anthropic-version: 2023-06-01',
        'content-type: application/json',
    ],
    CURLOPT_POSTFIELDS => json_encode($payload, JSON_UNESCAPED_UNICODE),
    CURLOPT_WRITEFUNCTION => $onChunk,
    CURLOPT_CONNECTTIMEOUT => 10,
    CURLOPT_TIMEOUT => 110,
]);
$ok = curl_exec($ch);
$status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
$curlErr = curl_error($ch);
curl_close($ch);

if ($ok === false && !connection_aborted()) {
    // Transport failed before/while streaming. If Anthropic returned a non-200
    // it usually arrives as a normal body the parser already forwarded; this
    // covers connect/timeout failures with no usable body.
    if ($status && $status !== 200) {
        sse_send('error', ['message' => 'Anthropic API error (' . $status . ').']);
    } else {
        sse_send('error', ['message' => $curlErr !== '' ? $curlErr : 'The research desk is unreachable right now — try again in a moment.']);
    }
} elseif (!$sawText && !connection_aborted()) {
    sse_send('error', ['message' => 'The model returned no text. Try again, or pick a different framework.']);
}

sse_send('done', []);
exit;
