# Warrior Desk — a disciplined, paper-first momentum day-trading agent

> **Educational tool. NOT investment advice.** Most day traders lose money. Past
> or simulated performance does not predict future results. Paper mode risks
> nothing; live mode risks real capital and is the Operator's sole responsibility.
> This agent enforces risk rules but cannot guarantee profit or prevent loss.

Warrior Desk role-plays a patient, rule-bound momentum desk trader following the
Ross Cameron / Warrior Trading small-cap strategy. It runs a strict **12-step
pre-trade gauntlet** before every order, enforces **hard deterministic risk
rules it cannot override**, and writes a plain-English **learning journal** that
explains the *why* behind every decision — including the trades it chose **not**
to take.

The point isn't a money printer (there's no such thing). It's disciplined
execution plus honest record-keeping so the Operator learns the craft.

---

## Safety model (read this first)

- **Paper by default.** Execution goes to Alpaca's paper API. No real money moves.
- **Live is a deliberate, multi-lock action** — never a default. To run live, ALL
  of these must hold or the app refuses to start:
  1. `trading_mode: live` in `config.yaml`
  2. env `WARRIOR_ALLOW_LIVE=I_UNDERSTAND_THE_RISK`
  3. an interactive typed confirmation at launch
  4. a signed & dated `live_account_acknowledgement.md`
- **Human-in-the-loop approval gate.** Every order prints the full proposal and
  waits for explicit `y` approval. In live this is mandatory and cannot be
  disabled; in paper it can be auto-approved for unattended sims (still logged).
- **The risk engine is the authority.** Plain Python decides; the LLM only writes
  prose. The model can never widen a stop, skip the 2:1 check, exceed size caps,
  or trade through a halt. If code and model disagree, **the code wins**.
- **Kill switch.** `warrior kill` flattens everything, cancels orders, and halts
  the session.
- **Graduation gate.** The agent refuses to discuss/enable live until a paper
  track record clears the bar (default ≥50 closed trades, positive expectancy,
  profit factor ≥1, drawdown under the limit).

---

## Install

```bash
cd warrior-desk
python3 -m pip install -e .            # core (PyYAML only)
# optional extras, installed lazily as needed:
python3 -m pip install -e ".[alpaca]"  # live data + execution (alpaca-py optional; a
                                       # dependency-free REST client is built in)
python3 -m pip install -e ".[llm]"     # Anthropic-written theses (claude-sonnet-4-6)
python3 -m pip install -e ".[gdoc]"    # Google Doc journal sync
```

The safety-critical core (risk engine, indicators, gauntlet, local journal) runs
on the standard library + PyYAML, so the tests run anywhere.

## Quickstart (no keys needed)

```bash
warrior propose --demo WARR     # full 12-step proposal on a built-in setup; no order
warrior backtest --demo         # replay a session through the same gauntlet (sim)
warrior run --demo --once       # one scan/evaluate/enter pass on demo data
warrior stats                   # cumulative performance + graduation-gate progress
```

## Configure

```bash
cp config.example.yaml config.yaml
cp .env.example .env             # add ALPACA_API_KEY / ALPACA_SECRET_KEY (paper)
```

Thresholds in `config.yaml` can be made **stricter** but some protective floors
are enforced in code regardless (the 2:1 reward:risk minimum, the 2-consecutive-
loss halt). See `config.example.yaml` for every setting.

## CLI

| command | what it does |
|---|---|
| `warrior run` | start the agent loop in the configured mode |
| `warrior status` | account, open positions, day P&L, gate state |
| `warrior watchlist` | ranked candidates + criteria scores |
| `warrior propose SYM` | run the 12-step gauntlet on one symbol; **place no order** |
| `warrior journal today` | today's journal summary |
| `warrior stats` | cumulative performance + graduation-gate progress |
| `warrior kill` | **flatten all + cancel orders + halt the session** |
| `warrior backtest --bars f.csv --symbol X` | replay historical bars (sim, no orders) |

`propose` and `backtest` are the main learning tools — full reasoning, zero
execution risk. Add `--demo` to any command to use the offline demo data.

## Going live (don't rush this)

1. Build a real paper track record. Run `warrior stats` until the graduation gate
   is green.
2. Set `trading_mode: live` in `config.yaml`.
3. `export WARRIOR_ALLOW_LIVE=I_UNDERSTAND_THE_RISK`.
4. `cp live_account_acknowledgement.example.md live_account_acknowledgement.md`,
   fill it in, and set `SIGNED: YES` with a real date and signature.
5. `warrior run` — type the launch confirmation when prompted.

If any lock is missing the agent hard-exits. There is no flag that auto-enables
live. The approval gate stays mandatory in live.

## Honest data gaps

Alpaca does **not** provide share float, and its scanner coverage for true
low-float gappers is limited. So:

- **Float** is a pluggable `FloatSource` (`UnknownFloatSource` by default,
  `StaticFloatSource` from an Operator CSV, or wire your own paid feed). When
  float is unknown the setup is marked *unverified* and **downgraded** (it can
  never grade A) — the agent never fabricates a number.
- **RVOL** needs a baseline the free feed may not give; it's approximated from
  daily average volume and **flagged as approximate** when so.
- The watchlist is approximated from movers + RVOL. Plug a real scanner via the
  `DataProvider` interface when you have one.

## Google Doc journal (optional)

The journal is always written locally (`journal/journal.md`, `journal/trades.csv`,
`journal/closed_trades.csv`). To also sync to a Google Doc:

1. Create a Google Cloud project; enable the **Google Docs API**.
2. Use a **service account** (share the target Doc with its email) or an **OAuth
   client** (download `credentials.json`; a `token.json` is written on first run).
3. Set `GOOGLE_CREDENTIALS_PATH`, `GOOGLE_TOKEN_PATH`, and `WARRIOR_GOOGLE_DOC_ID`
   in `.env`, and `pip install -e ".[gdoc]"`.

Without it the journal degrades to local-only and tells you how to enable it.

## Architecture

```
warrior/
  config.py        locks.py        risk.py         sizing.py       state.py
  sessions.py      indicators.py   patterns.py     selection.py    grading.py
  catalysts.py     gauntlet.py     reasoning.py    render.py       execution.py
  position_manager.py   broker.py  engine.py       kill.py         stats.py
  backtest.py      cli.py          demo.py         disclaimer.py
  data/   (DataProvider, Alpaca REST/provider, synthetic, float source)
  journal/(local CSV/MD, Google Doc sync, formatting, glossary)
```

Flow: **scan → gauntlet (12 steps) → deterministic risk engine → approval gate →
bracket order → position manager → journal**. The LLM only writes the thesis and
sits strictly downstream of the risk decision.

## Testing

```bash
python3 -m pytest        # ~120 tests; pure-Python core, no network needed
```

Covered: the live-lock impossibility, every hard risk gate, the LLM-can't-override
guarantee, sizing math, indicators vs hand-computed values, the gauntlet on clean
vs junk setups, the exit logic, restart safety, gaps/halts/outages, and the
backtest.

---

*Not financial advice. Educational only. Trade paper. The discipline is the edge.*
