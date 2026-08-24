"""Markdown + terminal scorecard over the closed recommendation ledger."""

from __future__ import annotations

import logging

from rich.console import Console
from rich.table import Table

from advisor.ledger import Ledger

from evals.metrics import Pair, calibration, hit_rate, max_drawdown, mean_alpha, median_alpha

logger = logging.getLogger(__name__)


def scorecard(ledger: Ledger | None = None) -> str:
    """Build a markdown scorecard over the closed recommendation ledger.

    Pretty-prints the same data to the terminal via rich as a side effect
    (best-effort — a rendering failure never blocks the markdown result), and
    returns the markdown string for programmatic use.
    """
    ledger = ledger or Ledger()
    pairs: list[Pair] = ledger.closed()
    open_recs = ledger.open_recommendations()
    cal = calibration(pairs)
    last_ten = sorted(pairs, key=lambda pair: pair[1].closed_at, reverse=True)[:10]

    markdown = _render_markdown(pairs, open_recs, cal, last_ten)
    _render_rich(pairs, open_recs, cal, last_ten)
    return markdown


def _render_markdown(pairs: list[Pair], open_recs: list, cal: list[dict], last_ten: list[Pair]) -> str:
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

    return "\n".join(lines)


def _render_rich(pairs: list[Pair], open_recs: list, cal: list[dict], last_ten: list[Pair]) -> None:
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
    except Exception:
        logger.exception("Failed to render rich scorecard tables; markdown output is unaffected.")
