"""Windows-encoding discipline.

Python's default text encoding on Windows is cp1252, which cannot represent the
unicode this project writes (✓, →, 🎉 in reports and journals). The EOD report
crashed on the operator's machine for exactly this. Every text read/write must
therefore pass encoding= explicitly; this test fails the build if a bare call
sneaks back in.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("src", "scripts", "replay")
CALL = re.compile(r"\.(?:write_text|read_text|open)\(")
EXEMPT = ("urlopen", "webbrowser.open", "_opener.open", "duckdb.connect")


def _calls_without_encoding(text: str) -> list[str]:
    bad = []
    for m in CALL.finditer(text):
        start = m.start()
        line_start = text.rfind("\n", 0, start) + 1
        line = text[line_start:text.find("\n", start)]
        if any(e in line for e in EXEMPT):
            continue
        # capture the full call by balancing parentheses from the opening one
        i = m.end() - 1
        depth = 0
        for j in range(i, min(len(text), i + 600)):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    call = text[i:j + 1]
                    break
        else:
            call = text[i:i + 600]
        # binary-mode open() is exempt ('rb'/'wb'); text mode must set encoding
        if re.search(r"""['"][rwa]b['"]""", call):
            continue
        if "encoding=" not in call:
            bad.append(line.strip())
    return bad


def test_all_text_io_declares_utf8():
    offenders: dict[str, list[str]] = {}
    for d in SCAN_DIRS:
        for py in (ROOT / d).rglob("*.py"):
            bad = _calls_without_encoding(py.read_text(encoding="utf-8"))
            if bad:
                offenders[str(py.relative_to(ROOT))] = bad
    assert not offenders, (
        "text IO without explicit encoding= (breaks on Windows/cp1252):\n"
        + "\n".join(f"  {f}: {lines}" for f, lines in offenders.items()))
