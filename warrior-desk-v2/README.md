# Warrior Desk v2

Momentum day-trading scanner + **paper-execution** agent (Warrior methodology).
Educational; not financial advice. Most day traders lose money — this system's
expectancy monitor exists to tell the truth about which side of that line the
strategy is on. **There is no code path to a live-money endpoint** (tested).

Read `CLAUDE.md` first — it is the agent charter (constraints, skill
checkpoints, live JSON contract, guardrails).

## Install

```bash
cd warrior-desk-v2
python3 -m pip install -e ".[dev]"
python3 -m pytest          # 122 tests
```

Secrets (paper keys only) via environment:

```
ALPACA_API_KEY / ALPACA_SECRET_KEY      # Alpaca PAPER keys
FMP_API_KEY / FINNHUB_API_KEY           # optional: float cross-validation vendors
```

## A trading day

```bash
python scripts/run_premarket.py    # 7:00 ET — gapper scan, 9:15 freeze, brief, QA checkpoint
python scripts/run_session.py      # 9:25 ET — stream → strategies → gates → paper brackets
python scripts/run_session.py halt     # kill switch: flatten + cancel + lock entries
python scripts/run_session.py resume   # release the lock
```

End of day (automatic): 15:55 time-stop flatten → EOD HTML report (auto-opens),
`analyze_eod` + `validate_report` checkpoints, Friday `stats_weekly`, and a
parquet export of the session for replay.

## Automate the daily run (Windows)

One-time setup so the agent runs itself every market weekday:

```powershell
cd warrior-desk-v2
copy secrets.local.ps1.example secrets.local.ps1     # then edit in your PAPER keys
powershell -ExecutionPolicy Bypass -File scripts\windows\install_tasks.ps1
```

Installs two Task Scheduler jobs: **Premarket** (weekdays 6:55 AM local/ET) and
**Session** (9:23 AM). Logs go to `logs\task_<mode>_<date>.log`; remove with the
same script plus `-Uninstall`. The PC must be on — or asleep with wake timers
allowed — at those times; the tasks are set to wake the machine and to run on
battery. Set `alerts.ntfy_topic` in `config.yaml` for phone pings on fills,
breakers, and data incidents so you can tell it ran without opening the laptop.

## Replay any captured day

```bash
python scripts/replay.py --date 2026-07-06 --speed 10
```

Identical code paths to live (same `SessionEngine`); deterministic — the printed
signal digest is stable for the same input, so rule changes are testable on
history before they touch live paper.

## Dashboard contract

The session mirrors state to `reports/live/*.json` (watchlist / positions /
signals / expectancy), schema-versioned — poll it from any front end.

## Honest limitations

- On the free IEX feed, rvol and HOD detection are approximations of the full
  tape (the startup banner says so). Upgrading the account to SIP requires only
  `data.feed: sip` in config.
- Paper fills are optimistic even with the slippage model applied. Treat paper
  profitability as necessary, never sufficient.
- Float vendors disagree; disagreement > 25% flags `float_unverified` and uses
  the conservative larger value.
