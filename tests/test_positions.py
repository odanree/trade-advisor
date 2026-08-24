"""advisor.data.positions.parse_fidelity_csv: junk-row and formatting resilience."""

from __future__ import annotations

from pathlib import Path

from advisor.data.positions import parse_fidelity_csv

_SAMPLE_CSV = """\
"Account Number","Account Name","Symbol","Description","Quantity","Last Price","Last Price Change","Current Value","Today's Gain/Loss Dollar","Today's Gain/Loss Percent","Total Gain/Loss Dollar","Total Gain/Loss Percent","Percent Of Account","Cost Basis Total","Average Cost Basis","Type"
"Z12345678","INDIVIDUAL","AAPL","APPLE INC","10","$225.50","+$1.20","$2,255.00","+$12.00","+0.53%","+$500.00","+28.5%","45.10%","$1,755.00","$175.50","Cash"
"Z12345678","INDIVIDUAL","MSFT**","MICROSOFT CORP","5.5","$410.00","+$3.10","$2,255.00","+$17.05","+0.76%","+$300.00","+15.3%","45.10%","$1,955.00","$355.45","Cash"
"Z12345678","INDIVIDUAL","","Pending Activity","","","","$0.00","","","","","0.00%","",""
"Z12345678","INDIVIDUAL","SPAXX**","MONEY MARKET","1,234.56","$1.00","$0.00","$1,234.56","$0.00","0.00%","$0.00","0.00%","24.70%","$1,234.56","$1.00","Cash"

"The data and information in this spreadsheet is provided by Fidelity for informational purposes only, and is not guaranteed for accuracy, completeness, timeliness."
"Brokerage services provided by Fidelity Brokerage Services LLC, Member NYSE, SIPC."
"""


def test_parse_fidelity_csv_clean(tmp_path: Path) -> None:
    csv_path = tmp_path / "positions.csv"
    csv_path.write_text(_SAMPLE_CSV, encoding="utf-8")

    positions = parse_fidelity_csv(csv_path)
    by_symbol = {p.symbol: p for p in positions}

    assert set(by_symbol) == {"AAPL", "MSFT", "SPAXX"}
    assert len(positions) == 3

    aapl = by_symbol["AAPL"]
    assert aapl.quantity == 10.0
    assert aapl.current_value == 2255.00

    msft = by_symbol["MSFT"]
    assert msft.symbol == "MSFT"  # trailing ** stripped
    assert msft.quantity == 5.5

    spaxx = by_symbol["SPAXX"]
    assert spaxx.quantity == 1234.56  # comma thousands separator handled
    assert spaxx.current_value == 1234.56

    # Junk rows (blank-symbol "Pending Activity" row, footer disclaimer lines) never
    # produce a Position.
    assert "Pending Activity" not in by_symbol
    assert not any("Fidelity" in p.symbol or "Brokerage" in p.symbol for p in positions)
