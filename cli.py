"""trade-advisor CLI: run the pipeline, mirror to paper trading, settle, and score."""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from advisor.data.positions import parse_fidelity_csv
from advisor.ledger import Ledger
from advisor.run import run_pipeline
from advisor.schema import Recommendation

from evals.report import scorecard as build_scorecard
from shadow.paper import mirror_recommendation
from shadow.settle import settle as settle_recommendations

load_dotenv()

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(
    help="Advice-only, human-in-the-loop trade advisor with shadow-mode paper evaluation."
)

_warned_shadow_unavailable = False


def _mirror_safely(rec: Recommendation) -> None:
    """Call shadow.paper.mirror_recommendation, warning at most once per process
    if Alpaca is unconfigured or errors — the advise command must never fail
    because the paper-trading mirror is unavailable."""
    global _warned_shadow_unavailable
    try:
        order_id = mirror_recommendation(rec)
        if order_id is None and not _warned_shadow_unavailable:
            console.print(
                "[yellow]Shadow paper mirror skipped for one or more recs "
                "(Alpaca unconfigured, no matching position, or hold).[/yellow]"
            )
            _warned_shadow_unavailable = True
    except Exception:
        if not _warned_shadow_unavailable:
            logger.exception("Shadow paper mirror raised unexpectedly; continuing without it.")
            console.print("[yellow]Shadow paper mirror failed; continuing without it.[/yellow]")
            _warned_shadow_unavailable = True


@app.command()
def advise(
    watchlist: Path = typer.Option(Path("config/watchlist.yaml"), help="Path to watchlist YAML."),
) -> None:
    """Run the advisor pipeline and shadow-mirror each recommendation into paper trading."""
    recs = run_pipeline(watchlist_path=watchlist)
    for rec in recs:
        console.print(
            f"[bold]{rec.ticker}[/bold] {rec.direction} ({rec.confidence:.0%} confidence): {rec.thesis}"
        )
        _mirror_safely(rec)


@app.command()
def settle() -> None:
    """Check open recommendations for invalidation/horizon triggers and close them out."""
    ledger = Ledger()
    open_count = len(ledger.open_recommendations())
    outcomes = settle_recommendations(ledger=ledger)
    if not outcomes:
        if open_count == 0:
            console.print("No open recommendations to check.")
        else:
            console.print(
                f"Checked {open_count} open recommendation(s); none triggered (0 closed)."
            )
        return
    for outcome in outcomes:
        rec = ledger.get_recommendation(outcome.rec_id)
        label = f"{rec.ticker} {rec.direction}" if rec is not None else outcome.rec_id
        console.print(
            f"{label} closed ({outcome.close_reason}): "
            f"alpha {outcome.alpha_pct:.2f}pp, exit ${outcome.exit_price:.2f}"
        )


@app.command()
def scorecard() -> None:
    """Print the evaluation scorecard (hit rate, alpha, calibration, drawdown)."""
    build_scorecard()


@app.command("import-positions")
def import_positions(
    path: Path = typer.Argument(..., help="Path to a Fidelity positions CSV export."),
) -> None:
    """Parse a Fidelity positions CSV export and print the holdings as a table."""
    positions = parse_fidelity_csv(path)
    table = Table(title="Positions")
    table.add_column("Symbol")
    table.add_column("Quantity", justify="right")
    table.add_column("Current value", justify="right")
    for position in positions:
        table.add_row(position.symbol, f"{position.quantity:g}", f"${position.current_value:,.2f}")
    console.print(table)


def app_entry() -> None:
    app()


if __name__ == "__main__":
    app()
