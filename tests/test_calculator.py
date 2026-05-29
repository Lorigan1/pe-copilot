"""Tests for the deterministic financial calculator (Layer 1.5).

Covers:
  - parse_extracted_text: header detection, label mapping, multi-column, blanks
  - evaluate_formula: arithmetic, negatives, missing deps, division by zero, safety
  - apply_calculations: dependency chaining, multi-period
  - inject_computed_values: blank fill, [COMPUTED] marker, non-blank preservation, nan handling
  - Integration: full NorthStar P&L calculation chain
  - Integration: BrightPath Education CSV (positive-cost Xero convention)
"""

import pytest

from app.models.calculation_rule import CalculationRule, LabelMapping
from app.services.calculator import (
    _parse_numeric,
    apply_calculations,
    evaluate_formula,
    inject_computed_values,
    parse_extracted_text,
)

# ─── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def northstar_mappings():
    """Label mappings for NorthStar Logistics."""
    return [
        LabelMapping(label="Net Sales", metric_name="net_sales"),
        LabelMapping(label="Cost of Sales", metric_name="cost_of_sales"),
        LabelMapping(label="Gross Profit", metric_name="gross_profit"),
        LabelMapping(label="Warehouse & Distribution", metric_name="warehouse_distribution"),
        LabelMapping(label="Fleet Operating Costs", metric_name="fleet_costs"),
        LabelMapping(label="Staff Costs", metric_name="staff_costs"),
        LabelMapping(label="Premises", metric_name="premises"),
        LabelMapping(label="Professional Fees", metric_name="professional_fees"),
        LabelMapping(label="Other Overheads", metric_name="other_overheads"),
        LabelMapping(label="Total Overheads", metric_name="total_overheads"),
        LabelMapping(label="Operating Profit Before D&A", metric_name="ebitda"),
        LabelMapping(label="Depreciation", metric_name="depreciation"),
        LabelMapping(label="Amortisation", metric_name="amortisation"),
        LabelMapping(label="Operating Profit", metric_name="operating_profit"),
        LabelMapping(label="Interest Payable", metric_name="interest_payable"),
        LabelMapping(label="Profit Before Tax", metric_name="pbt"),
        LabelMapping(label="Net Profit", metric_name="net_income"),
    ]


@pytest.fixture
def northstar_rules():
    """Calculation rules for NorthStar Logistics."""
    return [
        CalculationRule(
            metric_name="gross_profit",
            source_label="Gross Profit",
            formula="net_sales + cost_of_sales",
            description="Revenue minus Cost of Sales (costs stored as negative)",
        ),
        CalculationRule(
            metric_name="total_overheads",
            source_label="Total Overheads",
            formula="warehouse_distribution + fleet_costs + staff_costs + premises + professional_fees + other_overheads",
            description="Sum of all overhead line items",
        ),
        CalculationRule(
            metric_name="ebitda",
            source_label="Operating Profit Before D&A",
            formula="gross_profit + total_overheads",
            description="Gross Profit plus Total Overheads (overheads are negative)",
        ),
        CalculationRule(
            metric_name="operating_profit",
            source_label="Operating Profit",
            formula="ebitda + depreciation + amortisation",
            description="EBITDA plus D&A",
        ),
        CalculationRule(
            metric_name="pbt",
            source_label="Profit Before Tax",
            formula="operating_profit + interest_payable",
            description="Operating Profit plus Interest",
        ),
    ]


@pytest.fixture
def northstar_extracted_text():
    """Simulated pipe-separated extracted text from NorthStar Feb 2026 Excel."""
    return (
        "=== Sheet: P&L Summary ===\n"
        "NorthStar Logistics Ltd |  |  | \n"
        "Profit & Loss Summary — February 2026 |  |  | \n"
        " | Feb 2026 | Jan 2026 | Feb 2025\n"
        "Net Sales | 2609250 | 2450000 | 2280000\n"
        "Cost of Sales | -1435088 | -1347500 | -1254000\n"
        "Gross Profit |  |  | \n"
        "Warehouse & Distribution | -182648 | -171500 | -159600\n"
        "Fleet Operating Costs | -104770 | -85750 | -79800\n"
        "Staff Costs | -313110 | -294000 | -273600\n"
        "Premises | -54794 | -51450 | -47880\n"
        "Professional Fees | -6850 | -17150 | -15960\n"
        "Other Overheads | -36530 | -34300 | -31920\n"
        "Total Overheads |  |  | \n"
        "Operating Profit Before D&A |  |  | \n"
        "Depreciation | -65250 | -61250 | -57000\n"
        "Amortisation | -13050 | -12250 | -11400\n"
        "Operating Profit |  |  | \n"
        "Interest Payable | -19575 | -18375 | -17100\n"
        "Profit Before Tax |  |  | \n"
    )


# ─── _parse_numeric tests ─────────────────────────────────────────


class TestParseNumeric:
    def test_plain_integer(self):
        assert _parse_numeric("1000") == 1000.0

    def test_plain_float(self):
        assert _parse_numeric("1234.56") == 1234.56

    def test_negative(self):
        assert _parse_numeric("-5000") == -5000.0

    def test_comma_separated(self):
        assert _parse_numeric("2,609,250") == 2609250.0

    def test_pound_symbol(self):
        assert _parse_numeric("£1,000") == 1000.0

    def test_dollar_symbol(self):
        assert _parse_numeric("$2500.00") == 2500.0

    def test_euro_symbol(self):
        assert _parse_numeric("€750") == 750.0

    def test_parenthesized_negative(self):
        assert _parse_numeric("(1852000)") == -1852000.0

    def test_empty_string(self):
        assert _parse_numeric("") is None

    def test_whitespace_only(self):
        assert _parse_numeric("   ") is None

    def test_non_numeric(self):
        assert _parse_numeric("hello") is None


# ─── parse_extracted_text tests ────────────────────────────────────


class TestParseExtractedText:
    def test_single_column(self):
        text = (
            " | Feb 2026\n"
            "Net Sales | 2609250\n"
            "Cost of Sales | -1852000\n"
        )
        mappings = [
            LabelMapping(label="Net Sales", metric_name="net_sales"),
            LabelMapping(label="Cost of Sales", metric_name="cost_of_sales"),
        ]
        result = parse_extracted_text(text, mappings)
        assert result["net_sales"]["Feb 2026"] == 2609250.0
        assert result["cost_of_sales"]["Feb 2026"] == -1852000.0

    def test_multi_column(self):
        text = (
            " | Feb 2026 | Jan 2026\n"
            "Net Sales | 2609250 | 2450000\n"
        )
        mappings = [LabelMapping(label="Net Sales", metric_name="net_sales")]
        result = parse_extracted_text(text, mappings)
        assert result["net_sales"]["Feb 2026"] == 2609250.0
        assert result["net_sales"]["Jan 2026"] == 2450000.0

    def test_blank_cells_are_none(self):
        text = (
            " | Feb 2026 | Jan 2026\n"
            "Gross Profit |  | \n"
        )
        mappings = [LabelMapping(label="Gross Profit", metric_name="gross_profit")]
        result = parse_extracted_text(text, mappings)
        assert result["gross_profit"]["Feb 2026"] is None
        assert result["gross_profit"]["Jan 2026"] is None

    def test_unmapped_labels_ignored(self):
        text = (
            " | Feb 2026\n"
            "Net Sales | 2609250\n"
            "Something Random | 999\n"
        )
        mappings = [LabelMapping(label="Net Sales", metric_name="net_sales")]
        result = parse_extracted_text(text, mappings)
        assert "net_sales" in result
        assert len(result) == 1

    def test_case_insensitive_matching(self):
        text = (
            " | Feb 2026\n"
            "net sales | 2609250\n"
        )
        mappings = [LabelMapping(label="Net Sales", metric_name="net_sales")]
        result = parse_extracted_text(text, mappings)
        assert "net_sales" in result

    def test_section_headers_reset(self):
        """New sections (===) should reset headers."""
        text = (
            "=== Sheet: P&L Summary ===\n"
            " | Feb 2026\n"
            "Net Sales | 2609250\n"
            "=== Sheet: Balance Sheet ===\n"
            "Net Sales | 999\n"  # No headers after reset, should be skipped
        )
        mappings = [LabelMapping(label="Net Sales", metric_name="net_sales")]
        result = parse_extracted_text(text, mappings)
        # The second "Net Sales" has no headers, so shouldn't overwrite
        assert result["net_sales"]["Feb 2026"] == 2609250.0

    def test_northstar_full_extraction(self, northstar_extracted_text, northstar_mappings):
        result = parse_extracted_text(northstar_extracted_text, northstar_mappings)

        # Raw values should be parsed
        assert result["net_sales"]["Feb 2026"] == 2609250.0
        assert result["cost_of_sales"]["Feb 2026"] == -1435088.0
        assert result["fleet_costs"]["Feb 2026"] == -104770.0

        # Formula cells should be None
        assert result["gross_profit"]["Feb 2026"] is None
        assert result["ebitda"]["Feb 2026"] is None
        assert result["total_overheads"]["Feb 2026"] is None

        # Multiple periods parsed
        assert result["net_sales"]["Jan 2026"] == 2450000.0
        assert result["net_sales"]["Feb 2025"] == 2280000.0


# ─── evaluate_formula tests ────────────────────────────────────────


class TestEvaluateFormula:
    def test_basic_addition(self):
        result = evaluate_formula("a + b", {"a": 100.0, "b": 200.0})
        assert result == 300.0

    def test_subtraction(self):
        result = evaluate_formula("a - b", {"a": 1000.0, "b": 400.0})
        assert result == 600.0

    def test_multiplication(self):
        result = evaluate_formula("a * b", {"a": 10.0, "b": 5.0})
        assert result == 50.0

    def test_division(self):
        result = evaluate_formula("a / b", {"a": 100.0, "b": 4.0})
        assert result == 25.0

    def test_negative_operands(self):
        """Common in PE data: cost_of_sales is stored as negative."""
        result = evaluate_formula(
            "net_sales + cost_of_sales",
            {"net_sales": 2609250.0, "cost_of_sales": -1852000.0},
        )
        assert result == 757250.0

    def test_multi_operand(self):
        result = evaluate_formula(
            "a + b + c",
            {"a": 100.0, "b": 200.0, "c": 300.0},
        )
        assert result == 600.0

    def test_missing_dependency_returns_none(self):
        result = evaluate_formula("a + b", {"a": 100.0})
        assert result is None

    def test_none_value_treated_as_missing(self):
        result = evaluate_formula("a + b", {"a": 100.0, "b": None})
        assert result is None

    def test_division_by_zero_returns_none(self):
        result = evaluate_formula("a / b", {"a": 100.0, "b": 0.0})
        assert result is None

    def test_parentheses(self):
        result = evaluate_formula("(a + b) * c", {"a": 10.0, "b": 20.0, "c": 3.0})
        assert result == 90.0

    def test_unary_negative(self):
        result = evaluate_formula("-a", {"a": 100.0})
        assert result == -100.0

    def test_unsafe_formula_rejected(self):
        """Formulas with function calls should be blocked."""
        result = evaluate_formula("__import__('os').system('ls')", {})
        assert result is None

    def test_unsafe_attribute_access_rejected(self):
        result = evaluate_formula("a.b", {"a": 100.0})
        assert result is None

    def test_empty_metrics(self):
        result = evaluate_formula("a + b", {})
        assert result is None

    def test_syntax_error_returns_none(self):
        result = evaluate_formula("a +* b", {"a": 1.0, "b": 2.0})
        assert result is None

    def test_result_is_rounded(self):
        result = evaluate_formula("a / b", {"a": 10.0, "b": 3.0})
        assert result == round(10.0 / 3.0, 2)


# ─── apply_calculations tests ─────────────────────────────────────


class TestApplyCalculations:
    def test_simple_single_rule(self):
        parsed = {
            "net_sales": {"Feb 2026": 2609250.0},
            "cost_of_sales": {"Feb 2026": -1852000.0},
        }
        rules = [
            CalculationRule(
                metric_name="gross_profit",
                source_label="Gross Profit",
                formula="net_sales + cost_of_sales",
            ),
        ]
        result = apply_calculations(parsed, rules)
        assert result["gross_profit"]["Feb 2026"] == 757250.0

    def test_dependency_chaining(self):
        """Later rules can use results of earlier rules."""
        parsed = {
            "a": {"P1": 100.0},
            "b": {"P1": 50.0},
        }
        rules = [
            CalculationRule(metric_name="c", source_label="C", formula="a + b"),
            CalculationRule(metric_name="d", source_label="D", formula="c * a"),
        ]
        result = apply_calculations(parsed, rules)
        assert result["c"]["P1"] == 150.0
        assert result["d"]["P1"] == 15000.0

    def test_multi_period(self):
        parsed = {
            "net_sales": {"Feb 2026": 2609250.0, "Jan 2026": 2450000.0},
            "cost_of_sales": {"Feb 2026": -1852000.0, "Jan 2026": -1715000.0},
        }
        rules = [
            CalculationRule(
                metric_name="gross_profit",
                source_label="Gross Profit",
                formula="net_sales + cost_of_sales",
            ),
        ]
        result = apply_calculations(parsed, rules)
        assert result["gross_profit"]["Feb 2026"] == 757250.0
        assert result["gross_profit"]["Jan 2026"] == 735000.0

    def test_missing_input_skips_period(self):
        """If a dependency is missing for one period, that period is skipped."""
        parsed = {
            "a": {"P1": 100.0, "P2": 200.0},
            "b": {"P1": 50.0},  # Missing P2
        }
        rules = [
            CalculationRule(metric_name="c", source_label="C", formula="a + b"),
        ]
        result = apply_calculations(parsed, rules)
        assert result["c"]["P1"] == 150.0
        assert "P2" not in result["c"]

    def test_empty_rules_returns_empty(self):
        parsed = {"a": {"P1": 100.0}}
        result = apply_calculations(parsed, [])
        assert result == {}


# ─── inject_computed_values tests ──────────────────────────────────


class TestInjectComputedValues:
    def test_blank_cell_filled(self):
        text = (
            " | Feb 2026\n"
            "Net Sales | 2609250\n"
            "Cost of Sales | -1852000\n"
            "Gross Profit | \n"
        )
        computed = {"gross_profit": {"Feb 2026": 757250.0}}
        rules = [
            CalculationRule(
                metric_name="gross_profit",
                source_label="Gross Profit",
                formula="net_sales + cost_of_sales",
            ),
        ]
        result = inject_computed_values(text, computed, rules)
        assert "757250 [COMPUTED]" in result

    def test_non_blank_cell_preserved(self):
        """If the cell already has a value, don't overwrite it."""
        text = (
            " | Feb 2026\n"
            "Gross Profit | 999999\n"
        )
        computed = {"gross_profit": {"Feb 2026": 757250.0}}
        rules = [
            CalculationRule(
                metric_name="gross_profit",
                source_label="Gross Profit",
                formula="net_sales + cost_of_sales",
            ),
        ]
        result = inject_computed_values(text, computed, rules)
        assert "999999" in result
        assert "[COMPUTED]" not in result

    def test_computed_marker_present(self):
        text = (
            " | Feb 2026\n"
            "Gross Profit | \n"
        )
        computed = {"gross_profit": {"Feb 2026": 757250.0}}
        rules = [
            CalculationRule(
                metric_name="gross_profit",
                source_label="Gross Profit",
                formula="net_sales + cost_of_sales",
            ),
        ]
        result = inject_computed_values(text, computed, rules)
        assert "[COMPUTED]" in result

    def test_multi_column_injection(self):
        text = (
            " | Feb 2026 | Jan 2026\n"
            "Net Sales | 2609250 | 2450000\n"
            "Cost of Sales | -1852000 | -1715000\n"
            "Gross Profit |  | \n"
        )
        computed = {
            "gross_profit": {"Feb 2026": 757250.0, "Jan 2026": 735000.0},
        }
        rules = [
            CalculationRule(
                metric_name="gross_profit",
                source_label="Gross Profit",
                formula="net_sales + cost_of_sales",
            ),
        ]
        result = inject_computed_values(text, computed, rules)
        assert "757250 [COMPUTED]" in result
        assert "735000 [COMPUTED]" in result

    def test_no_computed_returns_original(self):
        text = " | Feb 2026\nNet Sales | 2609250\n"
        result = inject_computed_values(text, {}, [])
        assert result == text

    def test_unmatched_labels_untouched(self):
        text = (
            " | Feb 2026\n"
            "Random Row | 12345\n"
        )
        computed = {"gross_profit": {"Feb 2026": 757250.0}}
        rules = [
            CalculationRule(
                metric_name="gross_profit",
                source_label="Gross Profit",
                formula="net_sales + cost_of_sales",
            ),
        ]
        result = inject_computed_values(text, computed, rules)
        assert "12345" in result
        assert "[COMPUTED]" not in result


# ─── Full NorthStar integration test ──────────────────────────────


class TestNorthStarIntegration:
    """End-to-end test of the full NorthStar P&L calculation chain."""

    def test_full_calculation_chain(
        self, northstar_extracted_text, northstar_mappings, northstar_rules,
    ):
        # Step 1: Parse
        parsed = parse_extracted_text(northstar_extracted_text, northstar_mappings)

        # Verify raw data parsed correctly
        assert parsed["net_sales"]["Feb 2026"] == 2609250.0
        assert parsed["cost_of_sales"]["Feb 2026"] == -1435088.0
        assert parsed["gross_profit"]["Feb 2026"] is None

        # Step 2: Calculate
        computed = apply_calculations(parsed, northstar_rules)

        # Gross Profit = Net Sales + Cost of Sales
        assert computed["gross_profit"]["Feb 2026"] == 1174162.0
        assert computed["gross_profit"]["Jan 2026"] == 1102500.0

        # Total Overheads = sum of all overhead items
        expected_overheads_feb = -182648 + -104770 + -313110 + -54794 + -6850 + -36530
        assert computed["total_overheads"]["Feb 2026"] == expected_overheads_feb

        # EBITDA = Gross Profit + Total Overheads
        expected_ebitda_feb = 1174162.0 + expected_overheads_feb
        assert computed["ebitda"]["Feb 2026"] == expected_ebitda_feb

        # EBITDA should be positive (realistic PE company)
        assert expected_ebitda_feb > 0

        # Operating Profit = EBITDA + Depreciation + Amortisation
        expected_op_profit_feb = expected_ebitda_feb + (-65250) + (-13050)
        assert computed["operating_profit"]["Feb 2026"] == expected_op_profit_feb

        # PBT = Operating Profit + Interest Payable
        expected_pbt_feb = expected_op_profit_feb + (-19575)
        assert computed["pbt"]["Feb 2026"] == expected_pbt_feb

        # Step 3: Inject
        enriched = inject_computed_values(
            northstar_extracted_text, computed, northstar_rules,
        )
        assert "1174162 [COMPUTED]" in enriched
        assert "[COMPUTED]" in enriched

        # Count injected values — should have at least 5 rules × 3 periods (where deps exist)
        computed_count = enriched.count("[COMPUTED]")
        assert computed_count >= 10  # 5 rules × at least 2 periods each

    def test_jan_and_feb_ebitda_consistent(
        self, northstar_extracted_text, northstar_mappings, northstar_rules,
    ):
        """The key test: EBITDA should be calculated the same way across periods."""
        parsed = parse_extracted_text(northstar_extracted_text, northstar_mappings)
        computed = apply_calculations(parsed, northstar_rules)

        jan_ebitda = computed["ebitda"]["Jan 2026"]
        feb_ebitda = computed["ebitda"]["Feb 2026"]

        # Both should exist and be positive
        assert jan_ebitda is not None
        assert feb_ebitda is not None
        assert jan_ebitda > 0
        assert feb_ebitda > 0

        # Manually verify Jan
        jan_gross = 2450000.0 + (-1347500.0)  # 1,102,500
        jan_overheads = -171500 + -85750 + -294000 + -51450 + -17150 + -34300
        jan_expected = jan_gross + jan_overheads
        assert jan_ebitda == jan_expected

        # Manually verify Feb
        feb_gross = 2609250.0 + (-1435088.0)  # 1,174,162
        feb_overheads = -182648 + -104770 + -313110 + -54794 + -6850 + -36530
        feb_expected = feb_gross + feb_overheads
        assert feb_ebitda == feb_expected

        # The variance should be reasonable (not +149% as before)
        if jan_ebitda != 0:
            variance = (feb_ebitda - jan_ebitda) / abs(jan_ebitda)
            # Should be a modest change, not a wild swing
            assert abs(variance) < 0.2  # Less than 20% change

    def test_all_periods_calculated(
        self, northstar_extracted_text, northstar_mappings, northstar_rules,
    ):
        """All three periods (Feb 2026, Jan 2026, Feb 2025) should have computed values."""
        parsed = parse_extracted_text(northstar_extracted_text, northstar_mappings)
        computed = apply_calculations(parsed, northstar_rules)

        for metric in ["gross_profit", "total_overheads", "ebitda", "operating_profit", "pbt"]:
            assert "Feb 2026" in computed[metric], f"{metric} missing Feb 2026"
            assert "Jan 2026" in computed[metric], f"{metric} missing Jan 2026"
            assert "Feb 2025" in computed[metric], f"{metric} missing Feb 2025"


# ─── NaN handling (CSV/pandas blanks) ────────────────────────────


class TestNanHandling:
    """Pandas fills blank CSV cells with NaN — calculator must treat as None."""

    def test_parse_numeric_nan(self):
        assert _parse_numeric("nan") is None

    def test_parse_numeric_nan_uppercase(self):
        assert _parse_numeric("NaN") is None

    def test_csv_format_with_nan_cells(self):
        """CSV parser output uses 'nan' for blank cells."""
        text = (
            "=== CSV Data ===\n"
            "Account | Jan 2026\n"
            "----------------------------------------\n"
            "Revenue | 875000.0\n"
            "Cost of Sales | 437500.0\n"
            "Gross Profit | nan\n"
        )
        mappings = [
            LabelMapping(label="Revenue", metric_name="revenue"),
            LabelMapping(label="Cost of Sales", metric_name="cost_of_sales"),
            LabelMapping(label="Gross Profit", metric_name="gross_profit"),
        ]
        parsed = parse_extracted_text(text, mappings)
        assert parsed["revenue"]["Jan 2026"] == 875000.0
        assert parsed["cost_of_sales"]["Jan 2026"] == 437500.0
        assert parsed["gross_profit"]["Jan 2026"] is None

    def test_inject_replaces_nan_cells(self):
        """Injection should treat 'nan' cells as blank and fill them."""
        text = (
            "Account | Jan 2026\n"
            "----------------------------------------\n"
            "Gross Profit | nan\n"
        )
        computed = {"gross_profit": {"Jan 2026": 437500.0}}
        rules = [
            CalculationRule(
                metric_name="gross_profit",
                source_label="Gross Profit",
                formula="revenue - cost_of_sales",
            ),
        ]
        result = inject_computed_values(text, computed, rules)
        assert "437500 [COMPUTED]" in result
        assert "nan" not in result

    def test_separator_does_not_reset_headers(self):
        """Dashed separator lines from CSV parser should not clear headers."""
        text = (
            "Account | Jan 2026\n"
            "----------------------------------------\n"
            "Revenue | 875000.0\n"
        )
        mappings = [LabelMapping(label="Revenue", metric_name="revenue")]
        parsed = parse_extracted_text(text, mappings)
        assert "revenue" in parsed
        assert parsed["revenue"]["Jan 2026"] == 875000.0


# ─── BrightPath Education integration test (Xero/CSV) ────────────


class TestBrightPathIntegration:
    """End-to-end test for BrightPath: Xero CSV with positive-cost convention."""

    @pytest.fixture
    def brightpath_csv_text(self):
        """Simulates CSV parser output for BrightPath Jan 2026."""
        return (
            "=== CSV Data ===\n"
            "Account | Jan 2026\n"
            "----------------------------------------\n"
            "Total Income | 875000.0\n"
            "Course Fees | 620000.0\n"
            "Corporate Training Contracts | 180000.0\n"
            "Government Grants | 50000.0\n"
            "Other Income | 25000.0\n"
            "Total Cost of Sales | 437500.0\n"
            "Materials & Course Content | 87500.0\n"
            "Instructor Costs | 262500.0\n"
            "Facility Hire | 87500.0\n"
            "Gross Profit | nan\n"
            "Total Expenses | 306250.0\n"
            "Salaries & Wages | 175000.0\n"
            "Rent & Utilities | 43750.0\n"
            "Marketing & Advertising | 35000.0\n"
            "Technology & Software | 26250.0\n"
            "Depreciation | 17500.0\n"
            "Insurance | 8750.0\n"
            "EBITDA | nan\n"
            "Net Profit | nan\n"
            "Cash and Bank Accounts | 520000.0\n"
            "Total Debt Outstanding | 1100000.0\n"
            "Net Assets | 1850000.0\n"
            "Headcount | 78.0\n"
        )

    @pytest.fixture
    def brightpath_mappings(self):
        return [
            LabelMapping(label="Total Income", metric_name="revenue"),
            LabelMapping(label="Total Cost of Sales", metric_name="cost_of_sales"),
            LabelMapping(label="Gross Profit", metric_name="gross_profit"),
            LabelMapping(label="Total Expenses", metric_name="total_expenses"),
            LabelMapping(label="Depreciation", metric_name="depreciation"),
            LabelMapping(label="EBITDA", metric_name="ebitda"),
            LabelMapping(label="Net Profit", metric_name="net_income"),
            LabelMapping(label="Cash and Bank Accounts", metric_name="cash_balance"),
            LabelMapping(label="Total Debt Outstanding", metric_name="total_debt"),
            LabelMapping(label="Net Assets", metric_name="net_assets"),
            LabelMapping(label="Headcount", metric_name="headcount"),
        ]

    @pytest.fixture
    def brightpath_rules(self):
        return [
            CalculationRule(
                metric_name="gross_profit",
                source_label="Gross Profit",
                formula="revenue - cost_of_sales",
                description="Revenue minus Cost of Sales (Xero stores costs as positive)",
            ),
            CalculationRule(
                metric_name="ebitda",
                source_label="EBITDA",
                formula="revenue - cost_of_sales - total_expenses + depreciation",
                description="Gross Profit minus opex plus depreciation add-back",
            ),
            CalculationRule(
                metric_name="net_income",
                source_label="Net Profit",
                formula="revenue - cost_of_sales - total_expenses",
                description="Revenue minus all costs",
            ),
        ]

    def test_parsing_extracts_all_metrics(
        self, brightpath_csv_text, brightpath_mappings,
    ):
        parsed = parse_extracted_text(brightpath_csv_text, brightpath_mappings)

        assert parsed["revenue"]["Jan 2026"] == 875000.0
        assert parsed["cost_of_sales"]["Jan 2026"] == 437500.0
        assert parsed["total_expenses"]["Jan 2026"] == 306250.0
        assert parsed["depreciation"]["Jan 2026"] == 17500.0
        assert parsed["cash_balance"]["Jan 2026"] == 520000.0
        assert parsed["total_debt"]["Jan 2026"] == 1100000.0
        assert parsed["net_assets"]["Jan 2026"] == 1850000.0
        assert parsed["headcount"]["Jan 2026"] == 78.0

        # Formula cells should be None
        assert parsed["gross_profit"]["Jan 2026"] is None
        assert parsed["ebitda"]["Jan 2026"] is None
        assert parsed["net_income"]["Jan 2026"] is None

    def test_positive_cost_subtraction_formulas(
        self, brightpath_csv_text, brightpath_mappings, brightpath_rules,
    ):
        """Xero uses positive costs — formulas must subtract, not add."""
        parsed = parse_extracted_text(brightpath_csv_text, brightpath_mappings)
        computed = apply_calculations(parsed, brightpath_rules)

        # Gross Profit = 875,000 - 437,500 = 437,500
        assert computed["gross_profit"]["Jan 2026"] == 437500.0

        # EBITDA = 875,000 - 437,500 - 306,250 + 17,500 = 148,750
        assert computed["ebitda"]["Jan 2026"] == 148750.0

        # Net Income = 875,000 - 437,500 - 306,250 = 131,250
        assert computed["net_income"]["Jan 2026"] == 131250.0

    def test_ebitda_margin_reasonable(
        self, brightpath_csv_text, brightpath_mappings, brightpath_rules,
    ):
        """EBITDA margin should be reasonable for an education company."""
        parsed = parse_extracted_text(brightpath_csv_text, brightpath_mappings)
        computed = apply_calculations(parsed, brightpath_rules)

        revenue = parsed["revenue"]["Jan 2026"]
        ebitda = computed["ebitda"]["Jan 2026"]
        margin = ebitda / revenue

        # 17% EBITDA margin — reasonable for education
        assert 0.10 < margin < 0.30

    def test_injection_fills_all_nan_cells(
        self, brightpath_csv_text, brightpath_mappings, brightpath_rules,
    ):
        parsed = parse_extracted_text(brightpath_csv_text, brightpath_mappings)
        computed = apply_calculations(parsed, brightpath_rules)
        enriched = inject_computed_values(brightpath_csv_text, computed, brightpath_rules)

        assert "437500 [COMPUTED]" in enriched   # Gross Profit
        assert "148750 [COMPUTED]" in enriched   # EBITDA
        assert "131250 [COMPUTED]" in enriched   # Net Profit

        # No nan cells should remain for computed metrics
        for line in enriched.split("\n"):
            if "[COMPUTED]" in line:
                assert "nan" not in line.lower()

    def test_non_formula_rows_unchanged(
        self, brightpath_csv_text, brightpath_mappings, brightpath_rules,
    ):
        """Rows with existing values should not be modified."""
        parsed = parse_extracted_text(brightpath_csv_text, brightpath_mappings)
        computed = apply_calculations(parsed, brightpath_rules)
        enriched = inject_computed_values(brightpath_csv_text, computed, brightpath_rules)

        # Revenue row should be unchanged
        assert "Total Income | 875000.0" in enriched
        assert "Total Cost of Sales | 437500.0" in enriched
        assert "Headcount | 78.0" in enriched


# ─── Helix Manufacturing integration test (PDF/QuickBooks) ───────


class TestHelixIntegration:
    """End-to-end test for Helix: PDF board pack with multi-table extraction."""

    @pytest.fixture
    def helix_pdf_text(self):
        """Simulates PDF parser output for Helix Q4 2025 board pack."""
        return (
            "--- Text (Page 1) ---\n"
            "HELIX MANUFACTURING LTD\n"
            "Board Pack - Q4 2025\n"
            "\n"
            "--- Text (Page 2) ---\n"
            "Executive Summary\n"
            "Q4 2025 was a solid quarter.\n"
            "\n"
            "--- Table 1 (Page 3) ---\n"
            " | Q4 2025 | Q3 2025\n"
            "Turnover | 3,500,000 | 3,342,000\n"
            "Cost of Goods Sold | 2,100,000 | 2,038,000\n"
            "Gross Profit |  | \n"
            "Operating Expenses | 735,000 | 702,000\n"
            "EBITDA |  | \n"
            "Depreciation & Amortisation | 112,000 | 108,000\n"
            "Net Income |  | \n"
            "\n"
            "--- Table 1 (Page 4) ---\n"
            " | Q4 2025 | Q3 2025\n"
            "Bank & Cash | 680,000 | 590,000\n"
            "Term Loan | 1,200,000 | 1,250,000\n"
            "Overdraft Facility | 150,000 | 180,000\n"
            "Total Debt |  | \n"
            "Net Assets | 4,200,000 | 4,050,000\n"
            "\n"
            "--- Table 1 (Page 5) ---\n"
            " | Q4 2025 | Q3 2025\n"
            "Units Produced | 28,500 | 27,100\n"
            "Capacity Utilisation | 87% | 84%\n"
            "Headcount | 142 | 140\n"
        )

    @pytest.fixture
    def helix_mappings(self):
        return [
            LabelMapping(label="Turnover", metric_name="revenue"),
            LabelMapping(label="Cost of Goods Sold", metric_name="cogs"),
            LabelMapping(label="Gross Profit", metric_name="gross_profit"),
            LabelMapping(label="Operating Expenses", metric_name="operating_expenses"),
            LabelMapping(label="EBITDA", metric_name="ebitda"),
            LabelMapping(label="Depreciation & Amortisation", metric_name="dep_amort"),
            LabelMapping(label="Net Income", metric_name="net_income"),
            LabelMapping(label="Bank & Cash", metric_name="cash_balance"),
            LabelMapping(label="Term Loan", metric_name="term_loan"),
            LabelMapping(label="Overdraft Facility", metric_name="overdraft"),
            LabelMapping(label="Total Debt", metric_name="total_debt"),
            LabelMapping(label="Net Assets", metric_name="net_assets"),
            LabelMapping(label="Units Produced", metric_name="units_produced"),
            LabelMapping(label="Headcount", metric_name="headcount"),
        ]

    @pytest.fixture
    def helix_rules(self):
        return [
            CalculationRule(
                metric_name="gross_profit",
                source_label="Gross Profit",
                formula="revenue - cogs",
                description="Turnover minus COGS",
            ),
            CalculationRule(
                metric_name="ebitda",
                source_label="EBITDA",
                formula="gross_profit - operating_expenses",
                description="GP minus opex",
            ),
            CalculationRule(
                metric_name="net_income",
                source_label="Net Income",
                formula="ebitda - dep_amort",
                description="EBITDA minus D&A",
            ),
            CalculationRule(
                metric_name="total_debt",
                source_label="Total Debt",
                formula="term_loan + overdraft",
                description="Term Loan plus Overdraft",
            ),
        ]

    def test_multi_table_parsing(self, helix_pdf_text, helix_mappings):
        """Parser should extract metrics across multiple tables/pages."""
        parsed = parse_extracted_text(helix_pdf_text, helix_mappings)

        # P&L table (page 3)
        assert parsed["revenue"]["Q4 2025"] == 3500000.0
        assert parsed["cogs"]["Q4 2025"] == 2100000.0
        assert parsed["gross_profit"]["Q4 2025"] is None
        assert parsed["operating_expenses"]["Q4 2025"] == 735000.0

        # Balance sheet table (page 4)
        assert parsed["cash_balance"]["Q4 2025"] == 680000.0
        assert parsed["term_loan"]["Q4 2025"] == 1200000.0
        assert parsed["overdraft"]["Q4 2025"] == 150000.0
        assert parsed["total_debt"]["Q4 2025"] is None

        # KPI table (page 5)
        assert parsed["units_produced"]["Q4 2025"] == 28500.0
        assert parsed["headcount"]["Q4 2025"] == 142.0

    def test_quarterly_headers_detected(self, helix_pdf_text, helix_mappings):
        """Q4 2025 and Q3 2025 headers should be detected correctly."""
        parsed = parse_extracted_text(helix_pdf_text, helix_mappings)

        assert "Q4 2025" in parsed["revenue"]
        assert "Q3 2025" in parsed["revenue"]
        assert parsed["revenue"]["Q3 2025"] == 3342000.0

    def test_pl_calculation_chain(
        self, helix_pdf_text, helix_mappings, helix_rules,
    ):
        """Full P&L chain: GP → EBITDA → NI."""
        parsed = parse_extracted_text(helix_pdf_text, helix_mappings)
        computed = apply_calculations(parsed, helix_rules)

        # Q4 2025: GP = 3,500,000 - 2,100,000 = 1,400,000
        assert computed["gross_profit"]["Q4 2025"] == 1400000.0

        # Q4 2025: EBITDA = 1,400,000 - 735,000 = 665,000
        assert computed["ebitda"]["Q4 2025"] == 665000.0

        # Q4 2025: NI = 665,000 - 112,000 = 553,000
        assert computed["net_income"]["Q4 2025"] == 553000.0

        # Q3 2025: GP = 3,342,000 - 2,038,000 = 1,304,000
        assert computed["gross_profit"]["Q3 2025"] == 1304000.0

        # Q3 2025: EBITDA = 1,304,000 - 702,000 = 602,000
        assert computed["ebitda"]["Q3 2025"] == 602000.0

        # Q3 2025: NI = 602,000 - 108,000 = 494,000
        assert computed["net_income"]["Q3 2025"] == 494000.0

    def test_debt_calculation(
        self, helix_pdf_text, helix_mappings, helix_rules,
    ):
        """Total Debt = Term Loan + Overdraft — cross-table formula."""
        parsed = parse_extracted_text(helix_pdf_text, helix_mappings)
        computed = apply_calculations(parsed, helix_rules)

        # Q4 2025: 1,200,000 + 150,000 = 1,350,000
        assert computed["total_debt"]["Q4 2025"] == 1350000.0

        # Q3 2025: 1,250,000 + 180,000 = 1,430,000
        assert computed["total_debt"]["Q3 2025"] == 1430000.0

    def test_ebitda_margin_reasonable(
        self, helix_pdf_text, helix_mappings, helix_rules,
    ):
        """EBITDA margin should be reasonable for manufacturing."""
        parsed = parse_extracted_text(helix_pdf_text, helix_mappings)
        computed = apply_calculations(parsed, helix_rules)

        revenue = parsed["revenue"]["Q4 2025"]
        ebitda = computed["ebitda"]["Q4 2025"]
        margin = ebitda / revenue

        # 19% EBITDA margin — reasonable for manufacturing
        assert 0.10 < margin < 0.30

    def test_injection_across_tables(
        self, helix_pdf_text, helix_mappings, helix_rules,
    ):
        """Computed values should be injected into the correct table rows."""
        parsed = parse_extracted_text(helix_pdf_text, helix_mappings)
        computed = apply_calculations(parsed, helix_rules)
        enriched = inject_computed_values(helix_pdf_text, computed, helix_rules)

        # P&L computed values
        assert "1400000 [COMPUTED]" in enriched   # Gross Profit Q4
        assert "665000 [COMPUTED]" in enriched    # EBITDA Q4
        assert "553000 [COMPUTED]" in enriched    # Net Income Q4

        # Balance sheet computed value
        assert "1350000 [COMPUTED]" in enriched   # Total Debt Q4

        # Count computed markers — 4 rules × 2 periods = 8
        assert enriched.count("[COMPUTED]") == 8

    def test_qoq_variance_reasonable(
        self, helix_pdf_text, helix_mappings, helix_rules,
    ):
        """Quarter-on-quarter variances should be modest (not wild swings)."""
        parsed = parse_extracted_text(helix_pdf_text, helix_mappings)
        computed = apply_calculations(parsed, helix_rules)

        for metric in ["gross_profit", "ebitda", "net_income"]:
            q4 = computed[metric]["Q4 2025"]
            q3 = computed[metric]["Q3 2025"]
            variance = (q4 - q3) / abs(q3)
            assert abs(variance) < 0.15, f"{metric} QoQ variance {variance:.1%} too large"
