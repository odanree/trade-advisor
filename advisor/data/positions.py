"""Parse Fidelity's "Positions" CSV export into Position models.

Fidelity's export is not a clean table: alongside the real holding rows it
mixes in a "Pending Activity" row, blank separator lines, and a multi-line
footer disclaimer with no Symbol/Quantity at all. This parser is defensive
about all of that and only keeps rows that look like a real ticker holding.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

from advisor.schema import Position

logger = logging.getLogger(__name__)

# A plausible equity/ETF/money-market ticker: letters, digits, dots, hyphens.
# Fidelity money-market symbols carry a trailing "**" which is stripped
# before this check runs.
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _clean_money(raw: str) -> float | None:
    """Strip "$" and "," from a money field and parse it, or None if unparsable."""
    if raw is None:
        return None
    cleaned = raw.replace("$", "").replace(",", "").strip()
    if not cleaned or cleaned in {"--", "n/a", "N/A"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _clean_symbol(raw: str) -> str | None:
    """Strip trailing "**" (money market marker) and validate ticker shape."""
    if raw is None:
        return None
    symbol = raw.strip().rstrip("*").strip()
    if not symbol:
        return None
    if not _TICKER_RE.match(symbol.upper()):
        return None
    return symbol.upper()


def parse_fidelity_csv(path: Path) -> list[Position]:
    """Parse a Fidelity positions export, skipping junk/footer/pending rows."""
    positions: list[Position] = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            logger.warning("no header row found in %s", path)
            return positions

        for row in reader:
            symbol_raw = row.get("Symbol")
            if symbol_raw is None or not symbol_raw.strip():
                continue
            if symbol_raw.strip().lower().startswith("pending activity"):
                continue

            symbol = _clean_symbol(symbol_raw)
            if symbol is None:
                logger.debug("skipping row with non-ticker Symbol %r", symbol_raw)
                continue

            quantity = _clean_money(row.get("Quantity"))
            if quantity is None:
                logger.debug("skipping row for %s with unparsable Quantity", symbol)
                continue

            current_value = _clean_money(row.get("Current Value")) or 0.0

            positions.append(
                Position(symbol=symbol, quantity=quantity, current_value=current_value)
            )

    return positions
