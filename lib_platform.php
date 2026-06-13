<?php
/**
 * Shared platform library — DB, encryption, sessions, helpers.
 * Included by auth.php / broker.php / desk endpoints. Defines functions only;
 * a direct GET produces no output.
 *
 * Server-side config lives OUTSIDE public_html in asd-site-data/ (never in the
 * repo, never sent to the browser):
 *   db-config.php     -> <?php return ['host'=>..,'name'=>..,'user'=>..,'pass'=>..];
 *   app-secret.txt    -> a long random string (the master encryption secret)
 *   invite-codes.txt  -> one invite code per line (controls who can sign up)
 */

if (!defined('ASD_PLATFORM')) {
    define('ASD_PLATFORM', 1);

    define('ASD_DATA_DIR', dirname(__DIR__) . '/asd-site-data');

    function plat_json($code, $payload)
    {
        http_response_code($code);
        header('Content-Type: application/json; charset=utf-8');
        header('Cache-Control: no-store');
        echo json_encode($payload, JSON_UNESCAPED_UNICODE);
        exit;
    }

    /** True only when the server-side DB config exists. */
    function plat_configured()
    {
        return is_file(ASD_DATA_DIR . '/db-config.php')
            && is_file(ASD_DATA_DIR . '/app-secret.txt');
    }

    /** PDO singleton; auto-creates the schema on first use. */
    function plat_pdo()
    {
        static $pdo = null;
        if ($pdo !== null) {
            return $pdo;
        }
        if (!is_file(ASD_DATA_DIR . '/db-config.php')) {
            plat_json(503, ['error' => 'Platform not configured yet', 'setup' => true]);
        }
        $cfg = require ASD_DATA_DIR . '/db-config.php';
        try {
            $pdo = new PDO(
                'mysql:host=' . $cfg['host'] . ';dbname=' . $cfg['name'] . ';charset=utf8mb4',
                $cfg['user'], $cfg['pass'],
                [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC]
            );
        } catch (Exception $e) {
            plat_json(503, ['error' => 'Database unavailable']);
        }
        plat_schema($pdo);
        return $pdo;
    }

    function plat_schema($pdo)
    {
        $pdo->exec("CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(64) UNIQUE NOT NULL,
            pass_hash VARCHAR(255) NOT NULL,
            created_at INT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
        $pdo->exec("CREATE TABLE IF NOT EXISTS broker_keys (
            user_id INT NOT NULL,
            mode VARCHAR(8) NOT NULL,
            key_enc TEXT NOT NULL,
            secret_enc TEXT NOT NULL,
            updated_at INT NOT NULL,
            PRIMARY KEY (user_id, mode),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
        $pdo->exec("CREATE TABLE IF NOT EXISTS journal (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            symbol VARCHAR(15) NOT NULL,
            side VARCHAR(8) NOT NULL,
            qty DECIMAL(18,4) NOT NULL,
            rationale TEXT,
            desk_pick VARCHAR(64),
            created_at INT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
    }

    /** 32-byte key derived from the app secret. */
    function plat_key()
    {
        $secret = trim((string) @file_get_contents(ASD_DATA_DIR . '/app-secret.txt'));
        if ($secret === '') {
            plat_json(503, ['error' => 'Platform not configured yet', 'setup' => true]);
        }
        return hash('sha256', 'asd-platform|' . $secret, true); // 32 raw bytes
    }

    /** AES-256-GCM encrypt -> base64(iv|tag|cipher). */
    function plat_encrypt($plain)
    {
        $iv = random_bytes(12);
        $tag = '';
        $cipher = openssl_encrypt($plain, 'aes-256-gcm', plat_key(), OPENSSL_RAW_DATA, $iv, $tag, '', 16);
        return base64_encode($iv . $tag . $cipher);
    }
    function plat_decrypt($blob)
    {
        $raw = base64_decode((string) $blob, true);
        if ($raw === false || strlen($raw) < 29) {
            return null;
        }
        $iv = substr($raw, 0, 12);
        $tag = substr($raw, 12, 16);
        $cipher = substr($raw, 28);
        $out = openssl_decrypt($cipher, 'aes-256-gcm', plat_key(), OPENSSL_RAW_DATA, $iv, $tag);
        return $out === false ? null : $out;
    }

    /** Session bootstrap (HTTPS-only, httponly, samesite). */
    function plat_session()
    {
        if (session_status() === PHP_SESSION_NONE) {
            session_set_cookie_params([
                'lifetime' => 0, 'path' => '/', 'httponly' => true,
                'samesite' => 'Lax',
                'secure' => (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off'),
            ]);
            session_name('asd_sess');
            session_start();
        }
    }
    function plat_current_user_id()
    {
        plat_session();
        return isset($_SESSION['uid']) ? (int) $_SESSION['uid'] : null;
    }
    function plat_require_user()
    {
        $uid = plat_current_user_id();
        if (!$uid) {
            plat_json(401, ['error' => 'Not signed in']);
        }
        return $uid;
    }

    /** Simple per-IP rate limit (file-based, like the other endpoints). */
    function plat_rate_limit($bucket, $max, $windowSec)
    {
        $dir = ASD_DATA_DIR . '/ratelimit';
        if (!is_dir($dir)) { @mkdir($dir, 0755, true); }
        $ip = substr(sha1(($_SERVER['REMOTE_ADDR'] ?? '') . $bucket), 0, 16);
        $f = $dir . '/' . $bucket . '_' . $ip . '.json';
        $now = time();
        $hits = is_file($f) ? json_decode((string) file_get_contents($f), true) : [];
        if (!is_array($hits)) { $hits = []; }
        $hits = array_values(array_filter($hits, function ($t) use ($now, $windowSec) { return $now - $t < $windowSec; }));
        if (count($hits) >= $max) {
            return false;
        }
        $hits[] = $now;
        @file_put_contents($f, json_encode($hits), LOCK_EX);
        return true;
    }

    /** Alpaca REST base for a mode. */
    function plat_alpaca_base($mode)
    {
        return $mode === 'live'
            ? 'https://api.alpaca.markets'
            : 'https://paper-api.alpaca.markets';
    }

    /** Call Alpaca with a user's decrypted keys. Returns [httpCode, decodedBody]. */
    function plat_alpaca($mode, $key, $secret, $path, $method = 'GET', $body = null)
    {
        $ch = curl_init(plat_alpaca_base($mode) . $path);
        $headers = [
            'APCA-API-KEY-ID: ' . $key,
            'APCA-API-SECRET-KEY: ' . $secret,
            'Accept: application/json',
        ];
        $opts = [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 15,
            CURLOPT_CONNECTTIMEOUT => 8,
            CURLOPT_CUSTOMREQUEST => $method,
        ];
        if ($body !== null) {
            $headers[] = 'Content-Type: application/json';
            $opts[CURLOPT_POSTFIELDS] = json_encode($body);
        }
        $opts[CURLOPT_HTTPHEADER] = $headers;
        curl_setopt_array($ch, $opts);
        $resp = curl_exec($ch);
        $code = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_close($ch);
        return [$code, json_decode((string) $resp, true)];
    }

    /** Decrypt a user's stored keys for a mode. Returns ['key','secret'] or null. */
    function plat_load_keys($uid, $mode)
    {
        $st = plat_pdo()->prepare('SELECT key_enc, secret_enc FROM broker_keys WHERE user_id = ? AND mode = ?');
        $st->execute([$uid, $mode]);
        $row = $st->fetch();
        if (!$row) {
            return null;
        }
        $key = plat_decrypt($row['key_enc']);
        $secret = plat_decrypt($row['secret_enc']);
        return ($key && $secret) ? ['key' => $key, 'secret' => $secret] : null;
    }

    /** Plain server-side GET of a public JSON URL (e.g. Yahoo) for the desk scorecard. */
    function plat_http_get_json($url)
    {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 15, CURLOPT_CONNECTTIMEOUT => 8,
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_HTTPHEADER => ['User-Agent: Mozilla/5.0 (compatible; AndyDesk/1.0)', 'Accept: application/json'],
        ]);
        $body = curl_exec($ch);
        $code = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_close($ch);
        return [$code, json_decode((string) $body, true)];
    }
}
