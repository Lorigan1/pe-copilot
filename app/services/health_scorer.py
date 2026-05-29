"""Health scoring service — calculates green/amber/red status for companies.

Rule-based for MVP. Phase 3 could add ML-based scoring.
"""

import logging
from datetime import datetime

from app.models.company import Company

logger = logging.getLogger(__name__)


class HealthScorer:
    """Calculates health status for a portfolio company."""

    def score(
        self,
        company: Company,
        latest_variances: dict[str, float] | None = None,
        latest_missing_metrics: list[str] | None = None,
        staleness_amber_days: int = 21,
        staleness_red_days: int = 45,
    ) -> tuple[str, list[str]]:
        """Calculate health status and reasons.

        Returns:
            (status, reasons) where status is "green", "amber", or "red"
            and reasons is a list of human-readable explanations.
        """
        reasons: list[str] = []
        is_amber = False
        is_red = False

        # ─── Staleness check ───
        if company.last_update_at:
            days_since = (datetime.utcnow() - company.last_update_at).days

            if days_since > staleness_red_days:
                is_red = True
                reasons.append(f"No update in {days_since} days (threshold: {staleness_red_days})")
            elif days_since > staleness_amber_days:
                is_amber = True
                reasons.append(f"No update in {days_since} days (threshold: {staleness_amber_days})")
        else:
            is_amber = True
            reasons.append("No updates received yet")

        # ─── Variance check ───
        if latest_variances:
            metric_thresholds = {m.name: m.variance_threshold for m in company.canonical_metrics}

            for metric, variance in latest_variances.items():
                threshold = metric_thresholds.get(metric, 0.20)
                if abs(variance) > threshold:
                    direction = "increased" if variance > 0 else "decreased"
                    pct = abs(variance) * 100
                    reasons.append(f"{metric} {direction} by {pct:.1f}% (threshold: {threshold * 100:.0f}%)")

                    # Large negative variances on key metrics → red
                    if variance < -threshold and metric in ("revenue", "ebitda", "cash_balance"):
                        is_red = True
                    else:
                        is_amber = True

        # ─── Missing metrics check ───
        if latest_missing_metrics:
            if len(latest_missing_metrics) >= 3:
                is_red = True
                reasons.append(f"{len(latest_missing_metrics)} required metrics missing")
            elif latest_missing_metrics:
                is_amber = True
                reasons.append(f"Missing metrics: {', '.join(latest_missing_metrics)}")

        # Determine final status
        if is_red:
            status = "red"
        elif is_amber:
            status = "amber"
        else:
            status = "green"
            if not reasons:
                reasons.append("All metrics within normal ranges")

        return status, reasons


# Singleton
health_scorer = HealthScorer()
