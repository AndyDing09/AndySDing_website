<?php
/**
 * TEMPORARY — prints the server paths needed to switch the site lock on.
 * Delete this file once the lock is working. It exposes nothing secret,
 * but it has no reason to stay on a live site.
 */
header('Content-Type: text/plain; charset=utf-8');
header('Cache-Control: no-store');

$public = __DIR__;
$data   = dirname(__DIR__) . '/asd-site-data';

echo "Copy everything below and send it back.\n";
echo str_repeat('-', 58) . "\n\n";

echo "Web server : " . ($_SERVER['SERVER_SOFTWARE'] ?? 'unknown') . "\n";
echo "PHP        : " . PHP_VERSION . "\n\n";

echo "public_html      : $public\n";
echo "asd-site-data    : $data\n";
echo "  exists         : " . (is_dir($data)  ? 'yes' : 'NO') . "\n";
echo "  writable       : " . (is_writable($data) ? 'yes' : 'no') . "\n\n";

echo "AuthUserFile line to use:\n";
echo "AuthUserFile $data/.htpasswd\n\n";

echo ".htpasswd present: " . (is_file($data . '/.htpasswd') ? 'yes' : 'NO — still needs creating') . "\n";

$leftovers = ['blog-comments.json', 'blog-comment-votes.json'];
echo "\nLeftover comment data:\n";
foreach ($leftovers as $f) {
    $p = $data . '/' . $f;
    echo "  $f: " . (is_file($p) ? 'still there (' . filesize($p) . " bytes) — delete it\n" : "gone\n");
}
