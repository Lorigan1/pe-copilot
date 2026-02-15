"""Tests for CSV parsing — Layer 1 of the normalisation pipeline.

Uses BrightPath Education (Xero CSV export) as the reference case.
"""

import io
from pathlib import Path

import pytest

from app.services.excel_parser import ExcelParser

TESTDATA = Path(__file__).parent.parent / "testdata"


@pytest.fixture
def parser():
    return ExcelParser()


@pytest.fixture
def brightpath_csv():
    """Load the BrightPath Education sample CSV."""
    return (TESTDATA / "BrightPath_Education_Jan2026.csv").read_bytes()


# ─── BrightPath-specific tests ──────────────────────────────────

class TestBrightPathCSV:
    """Verify the parser extracts BrightPath's Xero-style flat CSV correctly."""

    def test_parses_without_error(self, parser, brightpath_csv):
        result = parser.parse_csv(brightpath_csv)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_header(self, parser, brightpath_csv):
        result = parser.parse_csv(brightpath_csv)
        assert "Account" in result
        assert "Jan 2026" in result

    def test_contains_revenue_line(self, parser, brightpath_csv):
        """BrightPath labels revenue as 'Total Income'."""
        result = parser.parse_csv(brightpath_csv)
        assert "Total Income" in result
        assert "875000" in result

    def test_contains_expense_breakdown(self, parser, brightpath_csv):
        result = parser.parse_csv(brightpath_csv)
        assert "Salaries & Wages" in result
        assert "175000" in result

    def test_contains_balance_sheet_items(self, parser, brightpath_csv):
        result = parser.parse_csv(brightpath_csv)
        assert "Cash and Bank Accounts" in result
        assert "520000" in result
        assert "Total Debt Outstanding" in result
        assert "1100000" in result

    def test_contains_net_profit(self, parser, brightpath_csv):
        result = parser.parse_csv(brightpath_csv)
        assert "Net Profit" in result
        assert "131250" in result

    def test_contains_headcount(self, parser, brightpath_csv):
        result = parser.parse_csv(brightpath_csv)
        assert "Headcount" in result
        assert "78" in result

    def test_contains_depreciation(self, parser, brightpath_csv):
        """Depreciation is needed to calculate EBITDA from the mapping instructions."""
        result = parser.parse_csv(brightpath_csv)
        assert "Depreciation" in result
        assert "17500" in result

    def test_output_has_separator(self, parser, brightpath_csv):
        """Columns should be pipe-separated for readability."""
        result = parser.parse_csv(brightpath_csv)
        assert "|" in result


# ─── Edge case tests ────────────────────────────────────────────

class TestCSVEdgeCases:
    """Edge cases the parser should handle gracefully."""

    def test_empty_csv(self, parser):
        result = parser.parse_csv(b"")
        assert isinstance(result, str)

    def test_header_only_csv(self, parser):
        result = parser.parse_csv(b"Account,Value\n")
        assert isinstance(result, str)
        assert "Account" in result

    def test_semicolon_delimiter(self, parser):
        """European-style CSV with semicolons."""
        csv = b"Metric;Value\nRevenue;1200000\nEBITDA;200000\n"
        result = parser.parse_csv(csv)
        assert "Revenue" in result
        assert "1200000" in result

    def test_tab_delimiter(self, parser):
        """TSV-style export."""
        csv = b"Metric\tValue\nRevenue\t1200000\n"
        result = parser.parse_csv(csv)
        assert "Revenue" in result
        assert "1200000" in result

    def test_quoted_fields_with_commas(self, parser):
        """Fields containing commas should be handled."""
        csv = b'Metric,Value\n"Salaries, Wages & Benefits",350000\nRevenue,1200000\n'
        result = parser.parse_csv(csv)
        assert "Salaries" in result
        assert "350000" in result

    def test_latin1_encoding(self, parser):
        """Non-UTF8 encoding (common from older accounting systems)."""
        csv = "Metric,Value\nTurnover\xa3,1200000\n".encode("latin-1")
        result = parser.parse_csv(csv)
        assert "1200000" in result

    def test_large_csv_truncated(self, parser):
        """CSVs with >200 rows should be truncated."""
        header = "Metric,Value\n"
        rows = "".join(f"Row{i},{i * 1000}\n" for i in range(300))
        csv = (header + rows).encode("utf-8")
        result = parser.parse_csv(csv)
        assert "truncated" in result.lower()

    def test_mixed_numeric_and_text(self, parser):
        """Handle columns with mixed types."""
        csv = b"Account,Jan 2026,Notes\nRevenue,1200000,audited\nEBITDA,200000,estimate\n"
        result = parser.parse_csv(csv)
        assert "Revenue" in result
        assert "audited" in result
