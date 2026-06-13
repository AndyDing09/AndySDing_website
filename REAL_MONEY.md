# Phase 5 — Real money (guidance only; nothing here is built)

This file is documentation for Andy's awareness. **No real-money trading code is
implemented**, and the platform defaults everyone to Alpaca **paper** accounts.

## Firstrade
- Firstrade has **no official public API.**
- Connecting it would require **unofficial scraping / automating the login**,
  which **violates Firstrade's terms**, risks account suspension, and would mean
  handling real brokerage credentials that move real money.
- **Do not build this.** The connect form intentionally supports Alpaca only and
  tells users Firstrade can't be connected.

## If you ever move to real money
The only safe pattern:
1. Use a broker with an **official API** (e.g. **Alpaca live**) — never scraping.
2. Keep **position sizes small** while learning.
3. Keep the **mandatory manual confirm on every order** that this app already
   enforces (review → confirm; nothing is ever auto-submitted).
4. An AI/automated agent must **never auto-execute real trades.**

## Custody reminder (you, the operator)
- Hosting other people's **live** keys makes you the custodian of credentials
  that move real money — a real security and, potentially, legal responsibility.
- Keys are encrypted at rest (AES-256-GCM) and decrypted only server-side, but
  the encryption key lives on the same server, so this protects against a
  database leak, **not** a full server compromise.
- Recommendation: keep this a **paper-only, private (invite-only)** tool. If you
  open it up or enable live keys for others, get a proper security review first.

## Honest framing (carried throughout the UI)
- Educational analysis and paper-trading practice — **not financial advice**, and
  it cannot predict markets.
- Most active traders underperform a simple index fund.
- Paper results exclude real-world slippage, fills, taxes, and emotion.
