"""Tests for the deterministic financial calculator (Layer 1.5).

Covers:
  - parse_extracted_text: header detection, label mapping, multi-column, blanks
  - evaluate_formula: arithmetic, negatives, missing deps, division by zero, safety
  - apply_calculations: dependency chaining, multi-period
  - inject_computed_values: blank fill, [COMPUTED] marker, non-blank preservation
  - Integration: full NorthStar P&L calculation chain
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
        "Cost of Sales | -1852000 | -1715000 | -1596000\n"
        "Gross Profit |  |  | \n"
        "Warehouse & Distribution | -260900 | -245000 | -228000\n"
        "Fleet Operating Costs | -149450 | -122500 | -114000\n"
        "Staff Costs | -382200 | -367500 | -342000\n"
        "Premises | -75000 | -73500 | -66000\n"
        "Professional Fees | -9800 | -24500 | -22800\n"
        "Other Overheads | -52200 | -49000 | -45600\n"
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
        assert result["cost_of_sales"]["Feb 2026"] == -1852000.0
        assert result["fleet_costs"]["Feb 2026"] == -149450.0

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
        assert parsed["cost_of_sales"]["Feb 2026"] == -1852000.0
        assert parsed["gross_profit"]["Feb 2026"] is None

        # Step 2: Calculate
        computed = apply_calculations(parsed, northstar_rules)

        # Gross Profit = Net Sales + Cost of Sales
        assert computed["gross_profit"]["Feb 2026"] == 757250.0
        assert computed["gross_profit"]["Jan 2026"] == 735000.0

        # Total Overheads = sum of all overhead items
        expected_overheads_feb = -260900 + -149450 + -382200 + -75000 + -9800 + -52200
        assert computed["total_overheads"]["Feb 2026"] == expected_overheads_feb

        # EBITDA = Gross Profit + Total Overheads
        expected_ebitda_feb = 757250.0 + expected_overheads_feb
        assert computed["ebitda"]["Feb 2026"] == expected_ebitda_feb

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
        assert "757250 [COMPUTED]" in enriched
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

        # Both should exist
        assert jan_ebitda is not None
        assert feb_ebitda is not None

        # Manually verify Jan
        jan_gross = 2450000.0 + (-1715000.0)  # 735000
        jan_overheads = -245000 + -122500 + -367500 + -73500 + -24500 + -49000
        jan_expected = jan_gross + jan_overheads
        assert jan_ebitda == jan_expected

        # Manually verify Feb
        feb_gross = 2609250.0 + (-1852000.0)  # 757250
        feb_overheads = -260900 + -149450 + -382200 + -75000 + -9800 + -52200
        feb_expected = feb_gross + feb_overheads
        assert feb_ebitda == feb_expected

        # The variance should be reasonable (not +149% as before)
        if jan_ebitda != 0:
            variance = (feb_ebitda - jan_ebitda) / abs(jan_ebitda)
            # Should be a modest change, not a wild swing
            assert abs(variance) < 1.0  # Less than 100% change

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
