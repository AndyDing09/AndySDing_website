# Warrior Desk v2 — Agent Charter

This file governs every Claude Code session that touches this project. Read it before changing anything.

## Mission

A momentum day-trading scanner and **paper-execution** agent implementing the Warrior Trading
methodology. It scans in real time, surfaces stocks meeting the momentum criteria, emits signals
only at ≥ 2:1 reward-to-risk, sizes positions off the stop distance, executes on the **Alpaca
paper API only**, and journals every signal so the strategy's real expectancy is measurable.

This is a disciplined trading assistant, not a money printer. The edge is: (1) only A-grade
setups, (2) risk rules a human would break under emotion, (3) honest stats that catch a losing
pattern in the data before it gets expensive.

## Hard constraints (never relax these)

1. **Paper trading only.** All order routes point at `https://paper-api.alpaca.markets`.
   `src/config.py` rejects any other trading base URL at startup. There is no live-money toggle,
   and none may be added. `tests/test_config.py::test_live_url_refused` enforces this.
2. **Every threshold lives in `config.yaml`** and is validated by pydantic. No magic numbers in code.
3. **The 2:1 gate is unconditional** (`src/risk/rr_gate.py`). A signal failing it is logged
   `skipped:insufficient_rr` and never becomes an order. No override flag exists.
4. **Long-only.** The extension point for shorts is a commented stub in `src/strategies/base.py`;
   do not implement it.
5. **US equities on Nasdaq/NYSE/AMEX only.** No OTC, pink sheets, crypto, or options.
6. **Never trade through a data gap.** Stale symbols are suppressed; stream gaps reconnect with
   backoff and are journaled as incidents.

## Skill checkpoints (mandatory operating loop)

The four data skills are INSTALLED in this repository at `.claude/skills/`
(`explore-data`, `analyze`, `statistical-analysis`, `validate-data` — the spec's
`/data:*` names map to these). Invoke the skill at each checkpoint; the built-in
job is the automation that runs unattended (EOD/weekly schedulers) and the
fallback when a session can't invoke skills. Both write timestamped artifacts to
`reports/` — same contract, same location.

| Checkpoint | Skill (installed) | Built-in job (automation/fallback) |
|---|---|---|
| Onboarding any new data source | `/explore-data <table>` | `python -m src.checkpoints.explore_source <table>` |
| After the 9:15 watchlist freeze | `/validate-data` on the frozen watchlist | `python -m src.checkpoints.validate_watchlist` |
| End of day | `/analyze` on the day's journal | `python -m src.checkpoints.analyze_eod` |
| Weekly (Friday close) and before ANY threshold change | `/statistical-analysis` (knowledge skill; apply via `/analyze`) | `python -m src.checkpoints.stats_weekly` |
| Before showing any performance report to a human | `/validate-data` on the report | `python -m src.checkpoints.validate_report` |

When following the skills, honor their core rules here: report mean AND median
together; Wilson/CI before trusting a win rate; investigate outliers, never
auto-delete; correlation ≠ causation; complete-period comparisons only; and the
validate-data pre-delivery checklist before anything reaches the operator.

**Parameter-tuning rule:** never tune a parameter because the last three trades lost. A threshold
change requires the weekly statistical report as justification, **cited in the commit message**
(path to the `reports/stats_weekly_*.json` artifact). Metrics with n < 30 are labeled
"insufficient sample — do not conclude" and cannot justify a change.

## Live JSON contract (dashboard)

The reporting layer mirrors state to `reports/live/` for any web front-end to poll
(the current consumer is the ⚡ Warrior tab on andysding.com; the contract is front-end-agnostic):

- `reports/live/watchlist.json` — the frozen/rolling watchlist rows (schema: `src/reporting/live_export.py`)
- `reports/live/positions.json` — open positions with unrealized R
- `reports/live/signals.json` — last 50 signals with status (`filled` / `skipped:<reason>` / `rejected:<gate>`)
- `reports/live/expectancy.json` — rolling 20-trade expectancy + circuit-breaker state

Keep these schemas stable; version with an integer `schema` field.

## Guardrails (verbatim — do not edit)

- This system trades simulated money for education and strategy validation. It is not financial
  advice and produces no buy/sell recommendations for real accounts.
- Published research consistently finds most day traders lose money; a minority are consistently
  profitable. The expectancy monitor exists so this system tells the truth about which side of
  that line the strategy is on.
- Paper results overstate live results: real fills on low-float stocks suffer slippage, partial
  fills, and borrow/halt risk the simulator softens even with the slippage model. Treat paper
  profitability as a necessary, never sufficient, condition.
- No real-money migration is in scope. If asked, decline and point to this section.

## Working agreements

- Python 3.11+, asyncio for streams, DuckDB for storage, pydantic models for config and signals,
  type hints everywhere.
- Each build phase ends with its tests passing before the next begins (`python -m pytest`).
- Data integrity is a feature with tests, not an assumption (see `src/data/scrub.py`,
  `stale.py`, `floats.py`, `corp_actions.py`, `clock.py`).
