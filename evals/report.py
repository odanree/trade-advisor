"""Markdown + terminal scorecard over the closed recommendation ledger."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from rich.console import Console
from rich.table import Table

from advisor.data.providers.base import MarketDataProvider
from advisor.data.providers.yfinance import YFinanceProvider
from advisor.ledger import Ledger
from advisor.schema import Recommendation

from evals.metrics import Pair, calibration, hit_rate, max_drawdown, mean_alpha, median_alpha
from shadow.benchmark import alpha as compute_alpha

logger = logging.getLogger(__name__)


class OpenPositionRow:
    """One row of the unrealized-alpha section: a live mark-to-market snapshot.

    `alpha_pct` is None when a quote could not be fetched for this rec's
    ticker (or for SPY) -- the row still renders, showing "n/a" for alpha,
    rather than dropping the rec or breaking the scorecard.
    """

    def __init__(
        self,
        rec: Recommendation,
        days_held: int,
        days_to_horizon: int,
        alpha_pct: float | None,
    ) -> None:
        self.rec = rec
        self.days_held = days_held
        self.days_to_horizon = days_to_horizon
        self.alpha_pct = alpha_pct


def _unrealized_rows(
    open_recs: list[Recommendation],
    provider: MarketDataProvider,
    now: datetime,
) -> list[OpenPositionRow]:
    """Mark each open rec to market via `provider`, reusing shadow.benchmark's pure math.

    A quote failure (for the rec's ticker or for SPY) is caught per-row so one
    bad ticker never breaks the rest of the scorecard -- that row just gets
    alpha_pct=None, rendered as "n/a" downstream.
    """
    rows: list[OpenPositionRow] = []
    for rec in open_recs:
        days_held = (now - rec.created_at).days
        days_to_horizon = rec.horizon_days - days_held

        alpha_pct: float | None = None
        try:
            quote = provider.get_quote(rec.ticker)
            benchmark_quote = provider.get_quote("SPY")
            alpha_pct = compute_alpha(rec, quote, benchmark_quote)
        except Exception:
            logger.exception(
                "Failed to mark rec %s (%s) to market for the unrealized-alpha section; "
                "showing n/a for this row.",
                rec.id,
                rec.ticker,
            )

        rows.append(
            OpenPositionRow(
                rec=rec,
                days_held=days_held,
                days_to_horizon=days_to_horizon,
                alpha_pct=alpha_pct,
            )
        )
    return rows


def scorecard(ledger: Ledger | None = None, provider: MarketDataProvider | None = None) -> str:
    """Build a markdown scorecard over the closed recommendation ledger.

    Pretty-prints the same data to the terminal via rich as a side effect
    (best-effort — a rendering failure never blocks the markdown result), and
    returns the markdown string for programmatic use.

    Also renders a PROVISIONAL "open positions (unrealized)" section that
    marks every still-open recommendation to market via `provider` (default
    YFinanceProvider, dependency-injected for tests) -- this is not part of
    the settled track record used by the metrics above; it's a live-marked
    preview so a quote failure for any one ticker never breaks the rest of
    the scorecard.
    """
    ledger = ledger or Ledger()
    provider = provider or YFinanceProvider()
    pairs: list[Pair] = ledger.closed()
    open_recs = ledger.open_recommendations()
    cal = calibration(pairs)
    last_ten = sorted(pairs, key=lambda pair: pair[1].closed_at, reverse=True)[:10]
    now = datetime.now(UTC)
    open_rows = _unrealized_rows(open_recs, provider, now)

    markdown = _render_markdown(pairs, open_recs, cal, last_ten, open_rows)
    _render_rich(pairs, open_recs, cal, last_ten, open_rows)
    return markdown


def _render_markdown(
    pairs: list[Pair],
    open_recs: list,
    cal: list[dict],
    last_ten: list[Pair],
    open_rows: list[OpenPositionRow],
) -> str:
    lines: list[str] = ["# Trade Advisor Scorecard", "", "## Overall", ""]
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Closed recommendations | {len(pairs)} |")
    lines.append(f"| Hit rate | {hit_rate(pairs):.1%} |")
    lines.append(f"| Mean alpha (pp) | {mean_alpha(pairs):.2f} |")
    lines.append(f"| Median alpha (pp) | {median_alpha(pairs):.2f} |")
    lines.append(f"| Max drawdown (pp) | {max_drawdown(pairs):.2f} |")
    lines.append(f"| Still open | {len(open_recs)} |")
    lines.append("")

    lines.append("## Calibration")
    lines.append("")
    if cal:
        lines.append("| Confidence bucket | n | Hit rate |")
        lines.append("| --- | --- | --- |")
        for row in cal:
            lines.append(f"| {row['bucket']} | {row['n']} | {row['hit_rate']:.1%} |")
    else:
        lines.append("_No closed recommendations yet._")
    lines.append("")

    lines.append("## Last 10 closed")
    lines.append("")
    if last_ten:
        lines.append("| Ticker | Direction | Confidence | Alpha (pp) | Close reason |")
        lines.append("| --- | --- | --- | --- | --- |")
        for rec, outcome in last_ten:
            lines.append(
                f"| {rec.ticker} | {rec.direction} | {rec.confidence:.2f} "
                f"| {outcome.alpha_pct:.2f} | {outcome.close_reason} |"
            )
    else:
        lines.append("_No closed recommendations yet._")
    lines.append("")

    lines.append("## Open positions — unrealized, provisional (not part of the settled track record)")
    lines.append("")
    if open_rows:
        lines.append("| Ticker | Direction | Confidence | Days held | Days to horizon | Unrealized alpha (pp) |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for row in open_rows:
            alpha_str = f"{row.alpha_pct:.2f}" if row.alpha_pct is not None else "n/a"
            lines.append(
                f"| {row.rec.ticker} | {row.rec.direction} | {row.rec.confidence:.2f} "
                f"| {row.days_held} | {row.days_to_horizon} | {alpha_str} |"
            )
    else:
        lines.append("_No open recommendations._")
    lines.append("")

    return "\n".join(lines)


def _render_rich(
    pairs: list[Pair],
    open_recs: list,
    cal: list[dict],
    last_ten: list[Pair],
    open_rows: list[OpenPositionRow],
) -> None:
    """Best-effort terminal pretty-print; a failure here never breaks scorecard()."""
    try:
        console = Console()

        overall = Table(title="Overall")
        overall.add_column("Metric")
        overall.add_column("Value")
        overall.add_row("Closed recommendations", str(len(pairs)))
        overall.add_row("Hit rate", f"{hit_rate(pairs):.1%}")
        overall.add_row("Mean alpha (pp)", f"{mean_alpha(pairs):.2f}")
        overall.add_row("Median alpha (pp)", f"{median_alpha(pairs):.2f}")
        overall.add_row("Max drawdown (pp)", f"{max_drawdown(pairs):.2f}")
        overall.add_row("Still open", str(len(open_recs)))
        console.print(overall)

        if cal:
            cal_table = Table(title="Calibration")
            cal_table.add_column("Confidence bucket")
            cal_table.add_column("n")
            cal_table.add_column("Hit rate")
            for row in cal:
                cal_table.add_row(row["bucket"], str(row["n"]), f"{row['hit_rate']:.1%}")
            console.print(cal_table)

        if last_ten:
            recent = Table(title="Last 10 closed")
            recent.add_column("Ticker")
            recent.add_column("Direction")
            recent.add_column("Confidence")
            recent.add_column("Alpha (pp)")
            recent.add_column("Close reason")
            for rec, outcome in last_ten:
                recent.add_row(
                    rec.ticker,
                    rec.direction,
                    f"{rec.confidence:.2f}",
                    f"{outcome.alpha_pct:.2f}",
                    outcome.close_reason,
                )
            console.print(recent)

        if open_rows:
            unrealized = Table(
                title="Open positions — unrealized, provisional (not part of the settled track record)"
            )
            unrealized.add_column("Ticker")
            unrealized.add_column("Direction")
            unrealized.add_column("Confidence")
            unrealized.add_column("Days held")
            unrealized.add_column("Days to horizon")
            unrealized.add_column("Unrealized alpha (pp)")
            for row in open_rows:
                alpha_str = f"{row.alpha_pct:.2f}" if row.alpha_pct is not None else "n/a"
                unrealized.add_row(
                    row.rec.ticker,
                    row.rec.direction,
                    f"{row.rec.confidence:.2f}",
                    str(row.days_held),
                    str(row.days_to_horizon),
                    alpha_str,
                )
            console.print(unrealized)
    except Exception:
        logger.exception("Failed to render rich scorecard tables; markdown output is unaffected.")
