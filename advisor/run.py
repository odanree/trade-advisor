"""Daily pipeline entry point: watchlist -> analysts -> debate -> synthesis -> ledger.

Idempotent per ticker per calendar day: a ticker that already has a
recommendation dated today is skipped. A run_key (today's date + a hash of
the sorted ticker list) is still recorded for observability, but it no
longer gates re-execution -- the per-ticker check is what makes re-running
the same day's job (e.g. a retried cron invocation after a partial failure)
fill in only the missing tickers instead of duplicating the ones that
already succeeded.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from advisor.agents import debate, fundamentals, sentiment, synthesizer, technicals
from advisor.data.providers.news import HeadlineProvider
from advisor.data.providers.yfinance import YFinanceProvider
from advisor.ledger import Ledger
from advisor.schema import Recommendation

logger = logging.getLogger(__name__)

console = Console()

_DEFAULT_BENCHMARK = "SPY"

# Hysteresis against whipsaw: a ticker stopped out via invalidation sits out
# for this many calendar days before it's eligible to be re-advised, even
# though invalidation closes its open rec and would otherwise clear the
# one-open-thesis-per-ticker guard immediately. Horizon-expiry closes don't
# start a cooldown -- see _cooldown_tickers.
COOLDOWN_DAYS = 5


def _load_watchlist(path: Path) -> tuple[list[str], str]:
    """Load tickers + benchmark symbol from a watchlist YAML file."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    tickers = [str(t).upper() for t in (data.get("tickers") or [])]
    benchmark = str(data.get("benchmark") or _DEFAULT_BENCHMARK).upper()
    return tickers, benchmark


def _make_run_key(tickers: list[str]) -> str:
    digest = sha256("|".join(sorted(tickers)).encode()).hexdigest()[:12]
    return f"{date.today().isoformat()}:{digest}"


def _open_rec_tickers(ledger: Ledger) -> set[str]:
    """Tickers that currently have a standing (unsettled) recommendation.

    Holds are excluded by ``Ledger.open_recommendations()`` itself -- a hold
    carries no standing thesis, so it never blocks re-analysis.
    """
    return {rec.ticker for rec in ledger.open_recommendations()}


def _cooldown_tickers(ledger: Ledger, day: date) -> set[str]:
    """Tickers still cooling down after an invalidation close, as of `day`.

    GOOGL was stopped out via invalidation on 2026-08-27 and re-advised as a
    fresh buy the very next day -- getting stopped out and immediately
    re-entered is the whipsaw this guards against. A ticker whose most
    recent invalidation close falls within the last COOLDOWN_DAYS calendar
    days (inclusive) is skipped even though it has no open rec. Horizon-
    expiry closes never land here -- Ledger.tickers_invalidated_since()
    filters to close_reason == "invalidation" only, so a thesis that simply
    ran its course is fine to re-evaluate immediately.
    """
    since = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=COOLDOWN_DAYS)
    return ledger.tickers_invalidated_since(since)


def _tickers_to_skip(ledger: Ledger, day: date) -> set[str]:
    """Tickers run_pipeline should not re-analyze on `day`.

    Union of three checks: the same-day idempotency check (already advised
    today), the one-open-thesis-per-ticker invariant (already has an
    unsettled rec, from any day), and the invalidation cooldown (stopped
    out within the last COOLDOWN_DAYS calendar days -- see
    _cooldown_tickers). Pulled out as a pure function -- combining three
    ledger reads into one set -- so it's testable against a tmp ledger
    without needing to run the LLM + provider pipeline.
    """
    return ledger.tickers_with_rec_on(day) | _open_rec_tickers(ledger) | _cooldown_tickers(ledger, day)


def _render_table(recs: list[Recommendation]) -> None:
    table = Table(title="trade-advisor run results")
    table.add_column("Ticker")
    table.add_column("Direction")
    table.add_column("Size %")
    table.add_column("Confidence")
    table.add_column("Invalidation")
    table.add_column("Horizon (d)")
    table.add_column("Thesis")

    for rec in recs:
        thesis_line = rec.thesis.splitlines()[0] if rec.thesis else ""
        if len(thesis_line) > 80:
            thesis_line = thesis_line[:77] + "..."
        table.add_row(
            rec.ticker,
            rec.direction,
            f"{rec.size_pct:.1f}",
            f"{rec.confidence:.2f}",
            f"{rec.invalidation.type} {rec.invalidation.level}",
            str(rec.horizon_days),
            thesis_line,
        )

    console.print(table)


def run_pipeline(
    watchlist_path: Path = Path("config/watchlist.yaml"),
    ledger: Ledger | None = None,
) -> list[Recommendation]:
    """Run the full analyst -> debate -> synthesis pipeline for the watchlist.

    Returns the list of newly created recommendations. Idempotency is
    per-ticker, not per-run: any ticker that already has a recommendation
    dated today is skipped, so a rerun (e.g. after a partial failure) only
    fills in the tickers that didn't succeed last time rather than
    duplicating the ones that did. A single ticker's failure is logged and
    skipped rather than aborting the whole run.

    One-open-thesis-per-ticker invariant: a ticker with an open (unsettled,
    non-hold) recommendation is not re-advised until that recommendation
    settles -- a buy/sell/trim rec stands for its full horizon (often ~45
    days) without needing a fresh daily analysis. Holds carry no standing
    thesis, so hold tickers are still re-analyzed every day.

    Invalidation cooldown: a ticker whose most recent close was an
    invalidation (stopped out) within the last COOLDOWN_DAYS calendar days
    is also skipped, even once its open rec has settled and the invariant
    above would otherwise clear it -- this is hysteresis against whipsaw,
    so a ticker isn't stopped out and immediately re-advised as a fresh buy
    on the next run. Horizon-expiry closes don't trigger cooldown: a thesis
    that simply ran its course is fine to re-evaluate right away.
    """
    ledger = ledger or Ledger()
    tickers, benchmark = _load_watchlist(watchlist_path)

    run_key = _make_run_key(tickers)
    if ledger.run_exists(run_key):
        # A prior invocation for today's watchlist already latched this key
        # (e.g. a partial-failure run that produced at least one rec). Don't
        # early-exit: the per-ticker guard below is what actually prevents
        # duplicates now, so continuing here is what lets a rerun fill in
        # just the tickers that failed last time.
        logger.info("run %s already recorded; continuing, per-ticker guard will skip completed tickers", run_key)

    already_done = ledger.tickers_with_rec_on(date.today())
    open_rec_tickers = _open_rec_tickers(ledger)
    cooldown_tickers = _cooldown_tickers(ledger, date.today())

    market_provider = YFinanceProvider()
    news_provider = HeadlineProvider()

    recs: list[Recommendation] = []
    for i, ticker in enumerate(tickers, start=1):
        if ticker in already_done:
            console.print(f"[{i}/{len(tickers)}] {ticker} -> already done today, skipped")
            continue
        if ticker in open_rec_tickers:
            console.print(f"[{i}/{len(tickers)}] {ticker} -> open rec active, skipped")
            continue
        if ticker in cooldown_tickers:
            console.print(f"[{i}/{len(tickers)}] {ticker} -> cooling down after invalidation, skipped")
            continue
        try:
            reports = [
                fundamentals.analyze(ticker, market_provider, news_provider),
                technicals.analyze(ticker, market_provider, news_provider),
                sentiment.analyze(ticker, market_provider, news_provider),
            ]
            debate_result = debate.run_debate(ticker, reports)
            rec = synthesizer.synthesize(ticker, reports, debate_result)

            rec.entry_price = market_provider.get_quote(ticker)
            rec.benchmark_entry_price = market_provider.get_quote(benchmark)

            ledger.append_recommendation(rec)
            recs.append(rec)
            console.print(
                f"[{i}/{len(tickers)}] {ticker} -> {rec.direction} "
                f"{rec.size_pct:.1f}% conf {rec.confidence:.2f}"
            )
        except Exception:
            logger.exception("pipeline failed for ticker %s, skipping", ticker)
            console.print(f"[{i}/{len(tickers)}] {ticker} -> [red]FAILED (skipped)[/red]")
            continue

    # Only latch the idempotency key if at least one recommendation actually
    # landed -- a fully-failed run (e.g. every LLM call errored) should stay
    # retryable on the next invocation rather than being silently skipped.
    if recs:
        ledger.record_run(run_key)

    if recs:
        _render_table(recs)
    else:
        console.print("[yellow]No recommendations produced this run.[/yellow]")

    return recs
