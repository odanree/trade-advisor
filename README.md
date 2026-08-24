# trade-advisor

An advice-only stock recommendation agent. A multi-agent LLM pipeline (fundamentals,
technicals, and sentiment analysts, fanned out in parallel, followed by a bull-vs-bear
debate and a synthesizer) emits structured `Recommendation`s into an append-only SQLite
ledger. A shadow module mirrors every recommendation into an Alpaca **paper** account and
benchmarks it against a same-dollar SPY counterfactual. Evals measure hit rate, alpha
versus SPY, and confidence calibration over time.

A human reads the recommendation and, if they agree, executes the trade manually in
their own brokerage account. This repo never places a live order.

## What this is NOT

- **Not a live-trading system.** There is no live-broker write path anywhere in this
  codebase, by design — not a missing feature, a deliberate boundary. The only broker
  integration is Alpaca **paper** trading, used exclusively to benchmark recommendations
  against reality without risking capital.
- **Not connected to any real brokerage account.** It never touches Fidelity, Schwab,
  Robinhood, or any other credentials — there is nothing in this repo that could execute
  a real trade even if misconfigured.
- **Not financial advice.** Recommendations are the output of an LLM pipeline reasoning
  over public market data. They are a structured opinion with a tracked record, not a
  guarantee, and are not a substitute for your own judgment or a licensed advisor.

## Architecture

```
                     ┌────────────────────────────┐
                     │      data providers        │
                     │  (fundamentals / price /    │
                     │   news, per-ticker fetch)   │
                     └──────────────┬─────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
             ┌────────────┐ ┌─────────────┐ ┌─────────────┐
             │fundamentals│ │ technicals  │ │  sentiment  │   analyst fan-out
             │  analyst   │ │  analyst    │ │  analyst    │   (parallel LLM calls)
             └──────┬─────┘ └──────┬──────┘ └──────┬──────┘
                    │              │               │
                    └──────────────┼───────────────┘
                                   ▼
                          ┌─────────────────┐
                          │  bull vs. bear   │   steelmanned debate,
                          │     debate       │   grounded in analyst evidence
                          └────────┬─────────┘
                                   ▼
                          ┌─────────────────┐
                          │   synthesizer    │   ONE recommendation:
                          │                  │   direction / size_pct /
                          │                  │   confidence / invalidation /
                          │                  │   horizon_days
                          └────────┬─────────┘
                                   ▼
                          ┌─────────────────┐
                          │  append-only     │   SQLite ledger — the
                          │  ledger (SQLite) │   permanent track record
                          └────────┬─────────┘
                                   ▼
                    ┌──────────────┴──────────────┐
                    ▼                              ▼
           ┌─────────────────┐           ┌──────────────────┐
           │  shadow: mirror  │           │  shadow: SPY      │
           │  into Alpaca     │           │  counterfactual    │
           │  PAPER account   │           │  (same $ amount)   │
           └────────┬─────────┘           └─────────┬──────────┘
                    │                                │
                    └───────────────┬────────────────┘
                                    ▼
                          ┌─────────────────┐
                          │      settle      │   mark positions,
                          │                  │   check invalidation
                          └────────┬─────────┘
                                   ▼
                          ┌─────────────────┐
                          │    scorecard      │   hit rate, alpha vs SPY,
                          │                  │   confidence calibration
                          └─────────────────┘
```

## Quickstart

```bash
cp .env.example .env          # fill in ANTHROPIC_API_KEY and Alpaca PAPER keys
pip install -e .

trade-advisor advise                    # run the pipeline over config/watchlist.yaml
trade-advisor settle                    # mark open shadow positions, check invalidation rules
trade-advisor scorecard                 # hit rate / alpha vs SPY / calibration report
trade-advisor import-positions positions.csv   # seed shadow tracking from an existing CSV
```

## Ledger + calibration philosophy: the track record is the product

The ledger is **append-only**. A recommendation, once written, is never edited or
deleted — corrections happen by writing a new row, not mutating history. This is what
makes the scorecard trustworthy: there is no way to quietly clean up a bad call after
the fact. Every `buy`/`sell`/`trim`/`hold` this system has ever made, with its stated
confidence and invalidation rule, stays on the record.

`confidence` is treated as a literal, checkable claim, not a vibe: a batch of
recommendations tagged 0.8 should be right roughly 80% of the time. The scorecard's
calibration eval exists specifically to catch drift from that — a synthesizer that
clusters every call around 0.75 "to be safe," or one that's systematically overconfident
on `buy` calls and underconfident on `hold`, shows up as a visible miscalibration in the
eval output, not as a vague sense that "the model seems off."

Every recommendation is benchmarked against a same-dollar SPY counterfactual, not
judged on raw return alone — a `buy` that returns 8% while SPY returns 12% over the same
horizon is a loss against the actual opportunity cost, and the scorecard reports it that
way. The goal is not to prove the pipeline is right; it's to build an honest, unedited
record of whether it is, and to make that record legible enough to act on.
