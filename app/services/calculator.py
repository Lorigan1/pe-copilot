"""Deterministic financial calculator — Layer 1.5 of the normalisation engine.

Sits between extraction (Layer 1) and LLM normalisation (Layer 2).
Computes derived metrics from raw line items using company-specific rules,
filling in blank formula cells before Claude sees the data.

This ensures consistent calculations across periods, eliminating variance
artifacts that arise when the LLM infers values differently each time.
"""

import ast
import logging
import re

from app.models.calculation_rule import CalculationRule, LabelMapping

logger = logging.getLogger(__name__)

# AST node types allowed in formula evaluation (arithmetic only)
_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.USub,
    ast.UAdd,
)


def parse_extracted_text(
    text: str,
    label_mappings: list[LabelMapping],
) -> dict[str, dict[str, float | None]]:
    """Parse pipe-separated extracted text into structured metrics per period.

    Returns a nested dict: {internal_metric_name: {period_header: value}}.
    Blank cells (formula cells) are stored as None.

    Args:
        text: Extracted text from Layer 1 (pipe-separated rows).
        label_mappings: Maps row labels to internal metric names.

    Example output:
        {
            "net_sales": {"Feb 2026": 2609250.0, "Jan 2026": 2450000.0},
            "gross_profit": {"Feb 2026": None, "Jan 2026": None},
        }
    """
    label_to_metric = {m.label.strip().lower(): m.metric_name for m in label_mappings}
    result: dict[str, dict[str, float | None]] = {}
    headers: list[str] = []

    for line in text.split("\n"):
        # Skip section markers, separator lines, and blanks
        if line.startswith("===") or not line.strip():
            headers = []  # Reset headers on new section
            continue
        if line.startswith("---"):
            continue  # Visual separator — don't reset headers

        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 2:
            continue

        label = cells[0].strip()

        # Detect header row: if most non-empty cells look like period labels
        # (contain a year or quarter reference at a word boundary), treat as headers
        non_empty = [c for c in cells[1:] if c]
        if non_empty and all(
            re.search(r"(\b20\d{2}\b|Q[1-4])", c) for c in non_empty
        ):
            headers = [c for c in cells[1:]]
            continue

        # Skip rows without headers or with no label
        if not headers or not label:
            continue

        # Match label to internal metric name
        label_lower = label.strip().lower()
        metric_name = label_to_metric.get(label_lower)
        if metric_name is None:
            continue

        # Parse values for each period
        period_values: dict[str, float | None] = {}
        for i, header in enumerate(headers):
            if not header:
                continue
            raw_val = cells[i + 1].strip() if i + 1 < len(cells) else ""
            period_values[header] = _parse_numeric(raw_val)

        if period_values:
            result[metric_name] = period_values

    return result


def evaluate_formula(
    formula: str,
    metrics: dict[str, float | None],
) -> float | None:
    """Safely evaluate an arithmetic formula using metric values.

    Uses AST whitelist to ensure only arithmetic operations are allowed.
    Returns None if any dependency is missing or the formula is invalid.

    Args:
        formula: Arithmetic expression using metric names (e.g., "net_sales + cost_of_sales").
        metrics: Available metric values. None values mean the metric is missing.

    Returns:
        Computed float value, or None if evaluation fails.
    """
    # Build namespace from available metrics (skip None values)
    namespace = {}
    for name, value in metrics.items():
        if value is not None:
            namespace[name] = value

    try:
        tree = ast.parse(formula, mode="eval")

        # Safety check: only allow arithmetic nodes
        for node in ast.walk(tree):
            if not isinstance(node, _ALLOWED_NODES):
                logger.warning("Rejected unsafe formula node: %s in '%s'", type(node).__name__, formula)
                return None

        # Check all referenced names are available
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id not in namespace:
                return None  # Missing dependency

        code = compile(tree, "<formula>", "eval")
        result = eval(code, {"__builtins__": {}}, namespace)  # noqa: S307
        return round(float(result), 2)

    except (ValueError, TypeError, ZeroDivisionError, SyntaxError) as e:
        logger.warning("Formula evaluation failed for '%s': %s", formula, e)
        return None


def apply_calculations(
    parsed_metrics: dict[str, dict[str, float | None]],
    rules: list[CalculationRule],
) -> dict[str, dict[str, float]]:
    """Apply calculation rules to compute derived metrics for each period.

    Rules are applied in order, so earlier rules can feed into later ones
    (e.g., gross_profit must be computed before ebitda).

    Args:
        parsed_metrics: {metric_name: {period: value}} from parse_extracted_text.
        rules: Ordered list of calculation rules.

    Returns:
        {metric_name: {period: computed_value}} for successfully computed metrics.
    """
    # Collect all periods from any metric
    all_periods: set[str] = set()
    for period_dict in parsed_metrics.values():
        all_periods.update(period_dict.keys())

    computed: dict[str, dict[str, float]] = {}

    for rule in rules:
        period_results: dict[str, float] = {}

        for period in sorted(all_periods):
            # Build a flat metrics dict for this period (extracted + previously computed)
            period_metrics: dict[str, float | None] = {}
            for metric_name, period_dict in parsed_metrics.items():
                period_metrics[metric_name] = period_dict.get(period)
            for metric_name, period_dict in computed.items():
                if period in period_dict:
                    period_metrics[metric_name] = period_dict[period]

            value = evaluate_formula(rule.formula, period_metrics)
            if value is not None:
                period_results[period] = value

        if period_results:
            computed[rule.metric_name] = period_results
            logger.debug("Computed %s: %s", rule.metric_name, period_results)

    return computed


def inject_computed_values(
    extracted_text: str,
    computed: dict[str, dict[str, float]],
    rules: list[CalculationRule],
) -> str:
    """Inject computed values back into the extracted text.

    Finds rows matching the source_label of each rule where cells are blank,
    and fills them with computed values marked [COMPUTED].

    Args:
        extracted_text: Original pipe-separated text from Layer 1.
        computed: {metric_name: {period: value}} from apply_calculations.
        rules: Calculation rules (used for source_label → metric_name mapping).

    Returns:
        Enriched text with computed values injected.
    """
    # Build lookup: source_label (lowercase) → (metric_name, computed periods)
    label_to_computed: dict[str, tuple[str, dict[str, float]]] = {}
    for rule in rules:
        if rule.metric_name in computed:
            label_to_computed[rule.source_label.strip().lower()] = (
                rule.metric_name,
                computed[rule.metric_name],
            )

    if not label_to_computed:
        return extracted_text

    headers: list[str] = []
    output_lines: list[str] = []

    for line in extracted_text.split("\n"):
        # Track section resets
        if line.startswith("==="):
            headers = []
            output_lines.append(line)
            continue
        if line.startswith("---"):
            output_lines.append(line)
            continue  # Visual separator — don't reset headers

        if not line.strip():
            output_lines.append(line)
            continue

        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 2:
            output_lines.append(line)
            continue

        label = cells[0].strip()

        # Detect header rows
        non_empty = [c for c in cells[1:] if c]
        if non_empty and all(re.search(r"(\b20\d{2}\b|Q[1-4])", c) for c in non_empty):
            headers = [c for c in cells[1:]]
            output_lines.append(line)
            continue

        # Check if this row matches a computed metric
        label_lower = label.strip().lower()
        if label_lower in label_to_computed and headers:
            metric_name, period_values = label_to_computed[label_lower]
            new_cells = [label]
            for i, header in enumerate(headers):
                original = cells[i + 1].strip() if i + 1 < len(cells) else ""
                if (not original or original.lower() == "nan") and header in period_values:
                    # Inject computed value
                    val = period_values[header]
                    formatted = str(int(val)) if val == int(val) else f"{val:.2f}"
                    new_cells.append(f"{formatted} [COMPUTED]")
                else:
                    new_cells.append(original)
            # Preserve trailing empty cells if original had them
            while len(new_cells) < len(cells):
                new_cells.append("")
            output_lines.append(" | ".join(new_cells))
        else:
            output_lines.append(line)

    return "\n".join(output_lines)


def _parse_numeric(raw: str) -> float | None:
    """Parse a string into a float, handling common accounting formats.

    Handles: plain numbers, negative numbers, parenthesized negatives,
    comma-separated thousands, currency symbols.
    Returns None for empty or unparseable strings.
    """
    if not raw:
        return None

    # Remove currency symbols, spaces, commas
    cleaned = raw.replace("£", "").replace("$", "").replace("€", "").replace(",", "").strip()

    if not cleaned:
        return None

    # Handle parenthesized negatives: (1000) → -1000
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]

    # Handle NaN (pandas fills blank CSV cells with "nan")
    if cleaned.lower() == "nan":
        return None

    try:
        return float(cleaned)
    except ValueError:
        return None
