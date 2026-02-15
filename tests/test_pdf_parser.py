"""Tests for PDF parsing — Layer 1 of the normalisation pipeline.

Uses Helix Manufacturing (QuickBooks PDF board pack) as the reference case.
"""

import io
from pathlib import Path

import pytest

from app.services.pdf_parser import PDFParser

TESTDATA = Path(__file__).parent.parent / "testdata"


@pytest.fixture
def parser():
    return PDFParser()


@pytest.fixture
def helix_pdf():
    """Load the Helix Manufacturing sample PDF."""
    return (TESTDATA / "Helix_Manufacturing_Q4_2025.pdf").read_bytes()


# ─── Helix-specific tests ───────────────────────────────────────

class TestHelixPDF:
    """Verify the parser extracts Helix's board pack PDF correctly."""

    def test_parses_without_error(self, parser, helix_pdf):
        result = parser.parse(helix_pdf)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_extracts_cover_page(self, parser, helix_pdf):
        result = parser.parse(helix_pdf)
        assert "Helix Manufacturing" in result
        assert "Q4 2025" in result

    def test_extracts_executive_summary(self, parser, helix_pdf):
        """Page 2 commentary should come through."""
        result = parser.parse(helix_pdf)
        assert "Executive Summary" in result
        assert "turnover" in result.lower()

    def test_extracts_turnover(self, parser, helix_pdf):
        """Helix labels revenue as 'Turnover'."""
        result = parser.parse(helix_pdf)
        assert "Turnover" in result
        assert "3,200,000" in result

    def test_extracts_ebitda(self, parser, helix_pdf):
        result = parser.parse(helix_pdf)
        assert "EBITDA" in result
        assert "520,000" in result

    def test_extracts_gross_profit(self, parser, helix_pdf):
        result = parser.parse(helix_pdf)
        assert "Gross Profit" in result
        assert "1,344,000" in result

    def test_extracts_net_profit(self, parser, helix_pdf):
        result = parser.parse(helix_pdf)
        assert "Net Profit" in result
        assert "380,000" in result

    def test_extracts_bank_and_cash(self, parser, helix_pdf):
        """Helix labels cash balance as 'Bank & Cash'."""
        result = parser.parse(helix_pdf)
        assert "Bank & Cash" in result or "Bank &amp; Cash" in result
        assert "890,000" in result

    def test_extracts_total_debt(self, parser, helix_pdf):
        """Total debt = Term Loan (1.2M) + Overdraft (600K) = 1.8M."""
        result = parser.parse(helix_pdf)
        assert "Term Loan" in result
        assert "1,200,000" in result
        assert "Overdraft" in result
        assert "600,000" in result

    def test_extracts_net_assets(self, parser, helix_pdf):
        result = parser.parse(helix_pdf)
        assert "Net Assets" in result
        assert "2,290,000" in result

    def test_extracts_units_produced(self, parser, helix_pdf):
        """Helix's custom operational KPI."""
        result = parser.parse(helix_pdf)
        assert "Units Produced" in result
        assert "45,200" in result

    def test_extracts_headcount(self, parser, helix_pdf):
        result = parser.parse(helix_pdf)
        assert "142" in result

    def test_tables_have_pipe_separators(self, parser, helix_pdf):
        """Table rows should be pipe-separated."""
        result = parser.parse(helix_pdf)
        assert "|" in result

    def test_multiple_tables_extracted(self, parser, helix_pdf):
        """Should extract tables from pages 3, 4, and 5."""
        result = parser.parse(helix_pdf)
        assert "Table 1 (Page 3)" in result  # P&L
        assert "Table 1 (Page 4)" in result  # Balance Sheet
        assert "Table 1 (Page 5)" in result  # KPIs

    def test_prior_period_data_included(self, parser, helix_pdf):
        """Q3 2025 comparison data should also be extracted."""
        result = parser.parse(helix_pdf)
        assert "2,960,000" in result  # Q3 Turnover


# ─── Edge case tests ────────────────────────────────────────────

class TestPDFEdgeCases:
    """Edge cases the PDF parser should handle gracefully."""

    def test_empty_pdf(self, parser):
        """Minimal valid PDF with no content."""
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Spacer

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        doc.build([Spacer(1, 1)])
        result = parser.parse(buf.getvalue())
        assert isinstance(result, str)

    def test_text_only_pdf(self, parser):
        """PDF with text but no tables."""
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        styles = getSampleStyleSheet()
        doc.build([
            Paragraph("Revenue is £1,200,000 this quarter.", styles["Normal"]),
            Paragraph("EBITDA reached £200,000.", styles["Normal"]),
        ])
        result = parser.parse(buf.getvalue())
        assert isinstance(result, str)
        # Should still extract the text content
        assert "1,200,000" in result or "Revenue" in result

    def test_table_only_pdf(self, parser):
        """PDF with only a table, no running text."""
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        data = [
            ["Metric", "Value"],
            ["Revenue", "1,200,000"],
            ["EBITDA", "200,000"],
        ]
        doc.build([Table(data)])
        result = parser.parse(buf.getvalue())
        assert "Revenue" in result
        assert "1,200,000" in result
