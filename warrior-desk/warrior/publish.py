"""Publish a JSON snapshot to the website (the 'viewer' integration).

The Python agent stays the single source of truth: it runs the gauntlet and writes
the journal, then pushes a compact snapshot — watchlist, recent proposals (with the
full 12-step trace), open positions, today's journal summary, cumulative stats, the
graduation gate, and recent alerts — to your site's ``warrior.php`` relay. The
website tab just renders it. The website can also queue on-demand ticker requests,
which the agent picks up here.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import Config
from .disclaimer import DISCLAIMER_SHORT
from .logging_setup import get_logger
from .models import Position, TradeProposal
from .stats import compute_stats, graduation_status, read_closed_trades

log = get_logger("publish")


def proposal_to_dict(p: TradeProposal) -> dict:
    cat = None
    if p.metrics.get("catalyst_headline") or p.metrics.get("catalyst"):
        cat = {"classification": p.metrics.get("catalyst"),
               "headline": p.metrics.get("catalyst_headline"),
               "source": p.metrics.get("catalyst_source")}
    return {
        "symbol": p.symbol, "side": p.side.value, "grade": p.grade.value,
        "pattern": p.pattern.value, "window": p.session_window.value,
        "approval": p.approval, "approved": bool(p.decision and p.decision.approved),
        "triggered": p.triggered,
        "reasons": list(p.decision.reasons) if p.decision else [],
        "entry": p.entry, "stop": p.stop, "target": p.target,
        "stop_distance": p.stop_distance, "reward_risk": p.reward_risk,
        "shares": p.shares, "risk_dollars": p.risk_dollars,
        "position_notional": p.position_notional, "position_pct": p.position_pct,
        "thesis": p.thesis, "catalyst": cat,
        "metrics": {k: v for k, v in p.metrics.items() if not k.startswith("catalyst_")},
        "steps": [{"number": s.number, "name": s.name, "status": s.status.value,
                   "detail": s.detail} for s in p.steps],
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _position_dict(pos: Position) -> dict:
    return {"symbol": pos.symbol, "qty": pos.qty, "avg_entry": pos.avg_entry,
            "stop": pos.stop, "target": pos.target, "scaled": pos.scaled,
            "realized_pnl": pos.realized_pnl}


def build_snapshot(cfg: Config, *, mode: str, account_equity: float, session: dict,
                   watchlist: list, proposals: list[TradeProposal],
                   open_positions: list[Position], journal=None,
                   alerts: Optional[list[str]] = None) -> dict:
    stats_d = grad_d = None
    journal_today = None
    if journal is not None:
        try:
            closed = read_closed_trades(str(Path(cfg.journal_dir) / "closed_trades.csv"))
            s = compute_stats(closed)
            stats_d = {
                "n": s.n, "wins": s.wins, "losses": s.losses, "win_rate": s.win_rate,
                "avg_win": s.avg_win, "avg_loss": s.avg_loss, "profit_factor": s.profit_factor,
                "expectancy": s.expectancy, "expectancy_r": s.expectancy_r,
                "total_pnl": s.total_pnl, "max_drawdown": s.max_drawdown,
                "max_drawdown_pct": s.max_drawdown_pct,
            }
            g = graduation_status(cfg, s)
            grad_d = {"eligible": g.eligible,
                      "criteria": [{"name": n, "met": m, "detail": d} for n, m, d in g.criteria]}
            journal_today = journal.today_structured()
        except Exception as exc:
            log.warning("snapshot stats build failed: %s", exc)

    return {
        "schema": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "account_equity": round(account_equity, 2),
        "disclaimer": DISCLAIMER_SHORT,
        "session": session,
        "watchlist": [{"symbol": c.symbol, "price": round(c.price, 4),
                       "gap_pct": round(c.gap_pct, 4), "rvol": round(c.rvol or 0, 2),
                       "score": round(c.score or 0, 2)} for c in watchlist],
        "proposals": [proposal_to_dict(p) for p in proposals],
        "open_positions": [_position_dict(p) for p in open_positions],
        "journal_today": journal_today,
        "stats": stats_d,
        "graduation": grad_d,
        "alerts": list(alerts or [])[-12:],
    }


def publish_snapshot(cfg: Config, snapshot: dict, timeout: float = 12.0) -> tuple[bool, str]:
    url = cfg.secrets.publish_url
    if not url:
        return False, "WARRIOR_PUBLISH_URL not set (snapshot not published)"
    body = json.dumps(snapshot).encode()
    req = urllib.request.Request(
        url + ("?action=publish" if "action=" not in url else ""),
        data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "X-Warrior-Token": cfg.secrets.publish_token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (200 <= resp.status < 300), f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:200] if e.fp else ''}"
    except Exception as exc:
        return False, f"publish failed: {exc}"


def fetch_requests(cfg: Config, timeout: float = 10.0) -> list[str]:
    """Pull (and clear) any on-demand ticker requests queued from the website."""
    url = cfg.secrets.publish_url
    if not url:
        return []
    base = url.split("?")[0]
    req = urllib.request.Request(base + "?action=requests", method="GET",
                                 headers={"X-Warrior-Token": cfg.secrets.publish_token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode() or "{}")
        syms = data.get("symbols", [])
        return [str(s).upper() for s in syms if s][:10]
    except Exception as exc:
        log.debug("fetch_requests failed: %s", exc)
        return []
