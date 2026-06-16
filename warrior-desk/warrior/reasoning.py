"""The trader's brain — plain-English thesis writer (Section 6).

It turns the *already-computed* facts into a mentor-style explanation for the
journal. Two implementations:

  - TemplateReasoner: deterministic, dependency-free, always available.
  - ClaudeReasoner: uses the Anthropic API (claude-sonnet-4-6) for richer prose.

Both are strictly downstream of the risk engine. They receive only real numbers,
may not invent data, and CANNOT alter any gate — the gauntlet restores the
authoritative decision after calling them.
"""

from __future__ import annotations

from typing import Optional

from .logging_setup import get_logger
from .models import Grade, StepStatus, TradeProposal

log = get_logger("reasoning")


def _facts_block(p: TradeProposal) -> str:
    m = p.metrics
    def g(k, default="n/a"):
        v = m.get(k, default)
        return default if v is None else v
    lines = [
        f"symbol={p.symbol} mode={p.mode} window={p.session_window.value} grade={p.grade.value}",
        f"pattern={g('pattern')} retrace={g('retrace_pct')} vwap_held={g('vwap_held')}",
        f"price={g('price')} rvol={g('rvol')}{' (approx)' if m.get('rvol_approx') else ''} "
        f"float={g('float')} float_verified={g('float_verified')}",
        f"vwap={g('vwap')} 9ema={g('ema9')} 20ema={g('ema20')} macd={g('macd_state')} "
        f"rsi={g('rsi')} atr={g('atr')}",
        f"catalyst={g('catalyst')} hod={g('hod')} prior_close={g('prior_close')}",
        f"entry={p.entry} stop={p.stop} stop_dist={p.stop_distance} target={p.target} "
        f"R:R={p.reward_risk} shares={p.shares} risk=${p.risk_dollars} "
        f"notional=${p.position_notional} pct={p.position_pct}",
    ]
    return "\n".join(lines)


class TemplateReasoner:
    """A solid, deterministic desk-note. No network, always works."""

    def write_thesis(self, p: TradeProposal) -> str:
        m = p.metrics
        approved = bool(p.decision and p.decision.approved)
        verb = "TAKING" if approved else "SKIPPING"
        parts: list[str] = []

        pattern = m.get("pattern", "n/a")
        cat = m.get("catalyst")
        cat_txt = f"a {cat} catalyst" if cat else "no news (technical-only)"
        rvol = m.get("rvol")
        rvol_txt = f"{rvol:.1f}x RVOL" if isinstance(rvol, (int, float)) else "unknown RVOL"

        if approved:
            parts.append(
                f"Why I'm {verb} {p.symbol}: a {pattern.replace('_', ' ')} in the "
                f"{p.session_window.value} window with {rvol_txt} and {cat_txt}. "
                f"Entry {p.entry:.2f} on the breakout, stop {p.stop:.2f} at the pullback low "
                f"(${p.stop_distance:.2f}/share), first target {p.target:.2f} for "
                f"{p.reward_risk:.1f}:1 — clears the 2:1 floor. Sized to {p.shares} shares "
                f"(${p.risk_dollars:.0f} at risk, {p.position_pct:.1%} of the account). "
                f"Graded {p.grade.value}."
            )
            if m.get("grade_notes"):
                parts.append(f"Grade rationale: {m['grade_notes']}.")
            if p.grade == Grade.B:
                parts.append("Sized down because it's a B — a soft spot keeps it off full size.")
        else:
            reason = "; ".join(p.decision.reasons) if p.decision else "did not qualify"
            parts.append(
                f"Why I'm {verb} {p.symbol}: it failed the gauntlet — {reason}. "
                f"The discipline is the edge; a tempting chart that doesn't clear the rules "
                f"is exactly the trade that bleeds an account. Walking away."
            )

        # A short note on the read.
        macd = m.get("macd_state"); rsi = m.get("rsi_state")
        if macd or rsi:
            parts.append(f"Read: MACD {macd}; RSI {rsi}; "
                         f"{'above' if m.get('vwap_held') else 'watch'} VWAP.")
        if m.get("float_verified") is False:
            parts.append("Note: float is UNVERIFIED — treated cautiously, not as fact.")
        return " ".join(parts)


class ClaudeReasoner:
    """Anthropic-backed thesis. Lazy-imports the SDK; degrades to the template."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self.api_key = api_key
        self.model = model
        self._client = None
        self._fallback = TemplateReasoner()

    def _client_or_none(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic  # lazy
        except ImportError:
            log.info("anthropic SDK not installed; using the template reasoner.")
            return None
        try:
            self._client = anthropic.Anthropic(api_key=self.api_key)
        except Exception as exc:
            log.warning("could not init Anthropic client: %s", exc)
            return None
        return self._client

    def write_thesis(self, p: TradeProposal) -> str:
        client = self._client_or_none()
        if client is None or not self.api_key:
            return self._fallback.write_thesis(p)

        steps = "\n".join(
            f"  {s.number}. {s.name}: {s.status.value} — {s.detail}" for s in p.steps
        )
        decision = "APPROVED" if (p.decision and p.decision.approved) else "REJECTED"
        reasons = "; ".join(p.decision.reasons) if (p.decision and not p.decision.approved) else "n/a"
        system = (
            "You are a disciplined momentum day-trading mentor writing a journal note. "
            "Explain the read like a desk trader teaching a student. Use ONLY the numbers "
            "provided — never invent data. You are NOT deciding anything: the decision is "
            "already made by a deterministic risk engine and you cannot change it. 120 words max, "
            "plain English, honest about uncertainty. End acknowledging this is educational, not advice."
        )
        user = (
            f"Decision (fixed): {decision}. Reasons if rejected: {reasons}.\n\n"
            f"Computed facts:\n{_facts_block(p)}\n\n12-step trace:\n{steps}\n\n"
            f"Write the 'why I took / skipped this trade' note."
        )
        try:
            resp = client.messages.create(
                model=self.model, max_tokens=400,
                system=system, messages=[{"role": "user", "content": user}],
            )
            text = "".join(getattr(b, "text", "") for b in resp.content).strip()
            return text or self._fallback.write_thesis(p)
        except Exception as exc:
            log.warning("Anthropic call failed (%s); using template.", exc)
            return self._fallback.write_thesis(p)


def make_reasoner(cfg, secrets) -> Optional[object]:
    """Pick a reasoner: Claude if enabled and a key exists, else the template."""
    if not cfg.use_llm_reasoning:
        return TemplateReasoner()
    if secrets.has_anthropic:
        return ClaudeReasoner(secrets.anthropic_api_key, cfg.llm_model)
    return TemplateReasoner()
