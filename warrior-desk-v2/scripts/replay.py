#!/usr/bin/env python3
"""Replay a stored session through the identical pipeline (§7.3).

    python scripts/replay.py --date 2026-07-06 --speed 10
    python scripts/replay.py --date 2026-07-06 --speed 0     # as fast as possible

Loads replay/data/<date>/bars_1m.parquet plus the day's frozen watchlist JSON,
runs the same SessionEngine as live, prints the result and the deterministic
signal digest (same input ⇒ same digest, byte for byte).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from replay.harness import load_bars_parquet, run_replay          # noqa: E402
from src.config import load_or_exit                                # noqa: E402
from src.models import Candidate                                   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", required=True, help="YYYY-MM-DD of a captured session")
    ap.add_argument("--speed", type=float, default=0.0, help="0 = max speed, N = Nx pacing")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = load_or_exit(args.config)
    bars = load_bars_parquet(Path(cfg.data.replay_dir) / args.date)

    wl_path = Path(cfg.reports.dir) / f"watchlist_{args.date}.json"
    if not wl_path.exists():
        print(f"missing {wl_path} — the pre-market scan writes it; replay needs the "
              f"same candidates the live session saw.", file=sys.stderr)
        return 2
    rows = json.loads(wl_path.read_text())["rows"]
    candidates = {r["symbol"]: Candidate.model_validate(r) for r in rows}

    res = run_replay(cfg, bars, candidates, speed=args.speed)
    print(f"replayed {res.n_bars} bars → {res.n_signals} signals, "
          f"{res.n_trades} trades, P&L {res.pnl_usd:+.2f} USD (sim, slippage-adjusted)")
    print(f"signal digest: {res.digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
