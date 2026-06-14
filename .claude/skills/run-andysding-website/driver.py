#!/usr/bin/env python3
"""Run & drive the andysding.com site locally.

The site is static HTML/CSS/JS (no build step). Its dynamic features call PHP
endpoints (chat.php, stocks.php, briefing.php, ...) that need a PHP runtime;
the front-end degrades gracefully without them, so the static server is enough
to verify layout/design, and the live endpoints are smoke-checked over HTTP.

Usage:
  python driver.py shot [page ...]      screenshot pages (default: index.html
                                        kymarion.html dev.html) with headless
                                        Chrome; prints PNG paths
  python driver.py serve [--port N]     serve the repo and block (manual view)
  python driver.py api [BASE_URL]       smoke the read-only GET endpoints
                                        (default base: https://andysding.com)

Env:
  CHROME=<path>   override the Chrome/Edge binary used for screenshots
  SHOTS=<dir>     override the screenshot output directory
"""
import http.server, socketserver, threading, functools, subprocess
import sys, os, tempfile, urllib.request

# .../<repo>/.claude/skills/run-andysding-website/driver.py  -> repo is 4 up
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

CHROME_CANDIDATES = [
    os.environ.get("CHROME"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser",
]


def find_chrome():
    import shutil
    for c in CHROME_CANDIDATES:
        if not c:
            continue
        if os.path.isfile(c):
            return c
        w = shutil.which(c)
        if w:
            return w
    sys.exit("No Chrome/Edge found. Set CHROME=<path-to-chrome.exe>.")


def start_server(port=0):
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a, **k: None  # quiet
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=REPO)
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def cmd_shot(pages):
    pages = pages or ["index.html", "kymarion.html", "dev.html"]
    chrome = find_chrome()
    httpd, port = start_server()
    out_dir = os.environ.get("SHOTS") or os.path.join(tempfile.gettempdir(), "andysding-shots")
    os.makedirs(out_dir, exist_ok=True)
    udd = tempfile.mkdtemp(prefix="andysding-chrome-")
    rc = 0
    for page in pages:
        url = "http://127.0.0.1:%d/%s" % (port, page)
        out = os.path.join(out_dir, page.replace("/", "_").replace(".html", "") + ".png")
        subprocess.run([
            chrome, "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--user-data-dir=" + udd,
            "--hide-scrollbars", "--force-device-scale-factor=1",
            "--window-size=1440,2600", "--virtual-time-budget=4000",
            "--screenshot=" + out, url,
        ], timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ok = os.path.exists(out) and os.path.getsize(out) > 0
        print(("OK   " if ok else "FAIL ") + out)
        rc = rc or (0 if ok else 1)
    httpd.shutdown()
    sys.exit(rc)


def cmd_serve(argv):
    port = 0
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    httpd, port = start_server(port)
    print("Serving %s at http://127.0.0.1:%d/  (Ctrl-C to stop)" % (REPO, port))
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        httpd.shutdown()


def cmd_api(argv):
    base = (argv[0] if argv else "https://andysding.com").rstrip("/")
    checks = [
        ("rtstatus", "stocks.php?action=rtstatus"),
        ("quote AAPL", "stocks.php?action=quotes&symbols=AAPL"),
        ("chart AAPL 1d", "stocks.php?action=chart&symbol=AAPL&range=1d&interval=5m"),
        ("briefing today", "briefing.php?action=today"),
        ("chat status", "chat.php"),
    ]
    rc = 0
    for name, path in checks:
        try:
            req = urllib.request.Request(base + "/" + path, headers={"User-Agent": "andysding-driver"})
            with urllib.request.urlopen(req, timeout=75) as r:
                body = r.read(220).decode("utf-8", "replace").replace("\n", " ")
                print("[%s] %-14s %s" % (r.status, name, body[:150]))
        except Exception as e:
            print("[ERR] %-14s %s" % (name, e)); rc = 1
    sys.exit(rc)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "shot":
        cmd_shot(rest)
    elif cmd == "serve":
        cmd_serve(rest)
    elif cmd == "api":
        cmd_api(rest)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
