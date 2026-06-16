"""Human-readable rendering of a TradeProposal.

Shared by ``warrior propose``, the approval gate, and the Markdown journal so the
metric table and 12-step trace look identical everywhere.
"""

from __future__ import annotations

import textwrap

from .models import StepStatus, TradeProposal


def _fmt(v, kind: str = "") -> str:
    if v is None:
        return "n/a"
    if kind == "money":
        return f"${v:,.2f}"
    if kind == "pct":
        return f"{v:.2%}"
    if kind == "shares":
        return f"{int(v):,}"
    if kind == "float":
        return f"{v/1e6:,.1f}M"
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".")
    return str(v)


def metric_rows(p: TradeProposal) -> list[tuple[str, str]]:
    m = p.metrics
    fv = "verified" if m.get("float_verified") else "UNVERIFIED"
    rvol = m.get("rvol")
    rvol_s = (f"{rvol:.1f}x" + (" (approx)" if m.get("rvol_approx") else "")) if rvol else "n/a"
    rows = [
        ("float", f"{_fmt(m.get('float'), 'float')} ({fv})" if m.get("float") else f"unknown ({fv})"),
        ("RVOL", rvol_s),
        ("price", _fmt(m.get("price"))),
        ("spread", _fmt(m.get("spread"))),
        ("% from 9-EMA", _fmt(m.get("pct_from_9ema"), "pct") if m.get("pct_from_9ema") is not None else "n/a"),
        ("% from VWAP", _fmt(m.get("pct_from_vwap"), "pct") if m.get("pct_from_vwap") is not None else "n/a"),
        ("VWAP held?", _fmt(m.get("vwap_held"))),
        ("MACD", _fmt(m.get("macd_state"))),
        ("RSI", _fmt(m.get("rsi_state"))),
        ("ATR", _fmt(m.get("atr"))),
        ("HOD", _fmt(m.get("hod"))),
        ("prior close", _fmt(m.get("prior_close"))),
        ("entry", _fmt(p.entry)),
        ("stop", f"{_fmt(p.stop)}  (dist {_fmt(p.stop_distance)})"),
        ("target", _fmt(p.target)),
        ("reward:risk", f"{p.reward_risk:.2f} : 1"),
        ("shares", _fmt(p.shares, "shares")),
        ("$ at risk", _fmt(p.risk_dollars, "money")),
        ("notional", _fmt(p.position_notional, "money")),
        ("% of account", _fmt(p.position_pct, "pct")),
    ]
    return rows


def render_metric_table(p: TradeProposal) -> str:
    rows = metric_rows(p)
    w = max(len(k) for k, _ in rows)
    return "\n".join(f"  {k.ljust(w)}  {v}" for k, v in rows)


def render_steps(p: TradeProposal) -> str:
    out = []
    for s in p.steps:
        mark = {"PASS": "✓", "FAIL": "✗", "INFO": "·", "SKIP": "–"}.get(s.status.value, "?")
        out.append(f"  {mark} {s.number:>2}. {s.name}: {s.status.value}")
        if s.detail:
            for line in textwrap.wrap(s.detail, 86):
                out.append(f"        {line}")
    return "\n".join(out)


def render_proposal(p: TradeProposal, width: int = 80) -> str:
    bar = "=" * width
    approved = bool(p.decision and p.decision.approved)
    head = f"{p.symbol} | {p.side.value.upper()} | grade {p.grade.value} | {p.pattern.value} | " \
           f"{p.session_window.value} | {p.mode}"
    if approved:
        verdict = "DECISION: ✓ APPROVED (clears every gate)"
    else:
        reasons = "; ".join(p.decision.reasons) if p.decision else "did not qualify"
        verdict = f"DECISION: ✗ REJECTED — {reasons}"

    cat = "none"
    if p.metrics.get("catalyst_headline"):
        cat = f"{p.metrics.get('catalyst')} — \"{p.metrics['catalyst_headline'][:70]}\" " \
              f"({p.metrics.get('catalyst_source', '')})"
    elif p.metrics.get("catalyst"):
        cat = str(p.metrics["catalyst"])

    sections = [
        bar,
        "WARRIOR DESK — TRADE PROPOSAL".center(width),
        bar,
        head,
        verdict,
        "",
        "THESIS:",
        textwrap.fill(p.thesis or "(no thesis generated)", width - 2,
                      initial_indent="  ", subsequent_indent="  "),
        "",
        f"CATALYST: {cat}",
        "",
        "METRICS:",
        render_metric_table(p),
        "",
        "12-STEP GAUNTLET:",
        render_steps(p),
        bar,
    ]
    return "\n".join(sections)
