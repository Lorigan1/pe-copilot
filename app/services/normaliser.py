"""The Normalisation Engine — core IP of PE CoPilot.

Three-layer pipeline:
  Layer 1: Format extraction (deterministic code — Excel, CSV, PDF parsers)
  Layer 2: LLM normalisation (Claude maps raw data to canonical metric schema)
  Layer 3: Validation and storage (Pydantic, variance calculation, health scoring)
"""

import json
import logging
from datetime import datetime

from app.config import settings
from app.models.llm_responses import NormalisationResponse, SummarisationResponse
from app.models.update import ProcessingStatus, SourceFileType, Update
from app.services import calculator
from app.services.email_sender import email_sender
from app.services.excel_parser import excel_parser
from app.services.firestore import firestore_service
from app.services.health_scorer import health_scorer
from app.services.llm import llm_service
from app.services.pdf_parser import pdf_parser
from app.services.storage import storage_service
from app.services.validators import validate_metrics

logger = logging.getLogger(__name__)

# ─── Prompt templates ─────────────────────────────────────────────

NORMALISATION_SYSTEM_PROMPT = """You are a financial data normalisation engine for a private equity fund. \
You receive raw financial data extracted from spreadsheets or PDFs sent by portfolio companies. \
Each company reports in a different format, with different labels, layouts, and conventions. \
Your job is to map this data to a canonical metric schema provided by the fund.

Return ONLY valid JSON matching the output schema. Be precise with numbers. \
If a metric is clearly present but labelled differently, map it (e.g. "Net Sales" → "revenue"). \
If a metric cannot be found, omit it from the metrics object. \
If a value is ambiguous, include it but set confidence to a lower value. \
Never fabricate numbers."""

NORMALISATION_USER_TEMPLATE = """COMPANY: {company_name}
SECTOR: {sector}
ACCOUNTING SYSTEM: {accounting_system}

CANONICAL METRIC SCHEMA (map to these):
{metric_schema_json}

COMPANY-SPECIFIC MAPPING NOTES:
{mapping_instructions}

RAW EXTRACTED DATA:
{extracted_text}

RETURN JSON:
{{
  "period": "string (e.g. Jan 2026, Q4 2025)",
  "metrics": {{ "metric_name": numeric_value, ... }},
  "unmapped_data": ["any notable data points that did not map to the schema"],
  "confidence": 0.0-1.0,
  "notes": "any caveats or assumptions made during mapping"
}}"""

SUMMARISATION_SYSTEM_PROMPT = """You are a senior PE analyst assistant reviewing a portfolio company \
update for a fund comptroller. Produce a concise summary (3–5 sentences) suitable for a busy professional. \
Be quantitative where the data supports it. Flag any risks, concerns, or anomalies. \
Suggest specific follow-up actions. Do not speculate beyond the data provided.

Return ONLY valid JSON matching the output schema."""

SUMMARISATION_USER_TEMPLATE = """COMPANY: {company_name} | SECTOR: {sector} | PERIOD: {period}

NORMALISED METRICS:
{normalised_metrics_json}

PREVIOUS PERIOD METRICS:
{previous_metrics_json}

VARIANCES (% change):
{variances_json}

RAW CONTEXT (extracted text):
{raw_context}

RETURN JSON:
{{
  "summary": "3–5 sentence summary",
  "risks": ["specific risk 1", "specific risk 2"],
  "action_items": ["follow-up 1", "follow-up 2"]
}}"""


class NormaliserService:
    """Orchestrates the three-layer normalisation pipeline."""

    async def process_update(self, update: Update) -> Update:
        """Run the full normalisation pipeline on an update.

        Steps:
        1. Download the raw file from GCS
        2. Extract text/tables (Layer 1)
        3. Normalise via Claude (Layer 2)
        4. Validate, calculate variances (Layer 3)
        5. Summarise via Claude
        6. Save to Firestore
        """
        try:
            # Mark as processing
            update.processing_status = ProcessingStatus.PROCESSING
            await firestore_service.save_update(update)

            # Get company info for context
            company = await firestore_service.get_company(update.company_id)
            if not company:
                raise ValueError(f"Company {update.company_id} not found")

            # ─── Layer 1: Extract ───
            logger.info("Layer 1: Extracting data from %s", update.source_file_type)
            extracted_text = await self._extract(update)
            update.extracted_text = extracted_text

            # ─── Layer 1.5: Deterministic Calculations ───
            if company.calculation_rules:
                logger.info("Layer 1.5: Applying deterministic calculations")
                extracted_text = self._calculate(extracted_text, company)

            # ─── Layer 2: Normalise via LLM ───
            logger.info("Layer 2: Normalising via Claude")
            metric_schema = [m.model_dump() for m in company.canonical_metrics]
            normalisation = await self._normalise(
                extracted_text=extracted_text,
                company_name=company.name,
                sector=company.sector,
                accounting_system=company.accounting_system,
                mapping_instructions=company.mapping_instructions,
                metric_schema=metric_schema,
            )

            update.normalised_metrics = normalisation.metrics
            update.metrics_period = normalisation.period or update.metrics_period
            update.llm_confidence = normalisation.confidence

            # ─── Layer 3: Validate ───
            logger.info("Layer 3: Validating and computing variances")

            # Check for missing required metrics
            required_metrics = [m.name for m in company.canonical_metrics if m.is_required]
            update.missing_metrics = [
                m for m in required_metrics if m not in normalisation.metrics
            ]

            # Calculate variances against previous update
            previous = await firestore_service.get_previous_update(
                update.company_id, update.id
            )
            if previous and previous.normalised_metrics:
                update.variances = self._calculate_variances(
                    current=normalisation.metrics,
                    previous=previous.normalised_metrics,
                )

            # ─── Layer 3.5: Sanity checks ───
            logger.info("Layer 3.5: Running deterministic metric validation")
            validation = validate_metrics(
                metrics=update.normalised_metrics,
                previous_metrics=previous.normalised_metrics if previous else None,
                variances=update.variances,
            )
            if validation.errors:
                update.processing_status = ProcessingStatus.NEEDS_REVIEW
                update.processing_error = "; ".join(validation.errors)
            if validation.warnings:
                logger.warning(
                    "Metric validation warnings for %s: %s",
                    update.id, validation.warnings,
                )

            # ─── Summarise ───
            logger.info("Generating summary via Claude (Haiku)")
            validation_context = (
                "\n\nVALIDATION WARNINGS:\n" + "\n".join(validation.warnings)
                if validation.warnings else ""
            )
            summary = await self._summarise(
                company_name=company.name,
                sector=company.sector,
                period=update.metrics_period,
                normalised_metrics=normalisation.metrics,
                previous_metrics=previous.normalised_metrics if previous else {},
                variances=update.variances,
                raw_context=extracted_text[:3000] + validation_context,  # Truncate + warnings
            )

            update.llm_summary = summary.summary
            update.llm_risks = summary.risks
            update.llm_action_items = summary.action_items

            # Determine processing status (Layer 3.5 may have already set NEEDS_REVIEW)
            if (
                update.processing_status != ProcessingStatus.NEEDS_REVIEW
                and (update.llm_confidence < 0.5 or len(update.missing_metrics) > 2)
            ):
                update.processing_status = ProcessingStatus.NEEDS_REVIEW
                logger.warning(
                    "Update marked as needs_review: confidence=%.2f, missing=%d",
                    update.llm_confidence,
                    len(update.missing_metrics),
                )
            elif update.processing_status != ProcessingStatus.NEEDS_REVIEW:
                update.processing_status = ProcessingStatus.COMPLETED

            update.processed_at = datetime.utcnow()

            # ─── Health scoring ───
            logger.info("Scoring company health for %s", company.name)
            company.last_update_at = datetime.utcnow()
            previous_health = company.health_status

            new_status, reasons = health_scorer.score(
                company=company,
                latest_variances=update.variances,
                latest_missing_metrics=update.missing_metrics,
            )
            company.health_status = new_status
            company.health_reasons = reasons

            await firestore_service.update_company(
                update.company_id,
                type("_", (), {"model_dump": lambda self, **kw: {
                    "last_update_at": company.last_update_at,
                    "health_status": new_status,
                    "health_reasons": reasons,
                }})(),
            )

            # Track if health status changed (for alert emails)
            if previous_health != new_status:
                logger.warning(
                    "Health status changed for %s: %s → %s (reasons: %s)",
                    company.name, previous_health, new_status, reasons,
                )
                update._health_changed = True
                update._previous_health = previous_health
            else:
                update._health_changed = False

        except Exception as e:
            logger.exception("Processing failed for update %s", update.id)
            update.processing_status = ProcessingStatus.FAILED
            update.processing_error = str(e)

        # Save final state
        await firestore_service.save_update(update)

        # ─── Send alert email if health changed ───
        if getattr(update, "_health_changed", False):
            try:
                fund = await firestore_service.get_fund(company.fund_id)
                recipient = fund.manager_email if fund else ""
                fund_name = fund.name if fund else "Unknown Fund"

                if recipient:
                    await email_sender.send_health_alert(
                        recipient_email=recipient,
                        company_name=company.name,
                        previous_status=getattr(update, "_previous_health", "green"),
                        new_status=company.health_status,
                        reasons=company.health_reasons,
                        fund_name=fund_name,
                    )
            except Exception as email_exc:
                logger.error(
                    "Failed to send health alert for %s: %s",
                    company.name, email_exc,
                )

        return update

    # ─── Layer 1: Extraction ──────────────────────────────────

    def _calculate(self, extracted_text: str, company) -> str:
        """Layer 1.5: Apply deterministic calculations to fill blank formula cells.

        Uses company-specific label mappings and calculation rules to compute
        derived metrics (e.g., Gross Profit, EBITDA) from raw line items.
        Falls back to original text if calculation fails.
        """
        try:
            parsed = calculator.parse_extracted_text(
                extracted_text, company.label_mappings
            )
            computed = calculator.apply_calculations(parsed, company.calculation_rules)
            if computed:
                enriched = calculator.inject_computed_values(
                    extracted_text, computed, company.calculation_rules
                )
                n_computed = sum(len(v) for v in computed.values())
                logger.info(
                    "Calculation layer: computed %d values for %s",
                    n_computed, company.name,
                )
                return enriched
            return extracted_text
        except Exception as e:
            logger.warning(
                "Calculation layer failed for %s: %s. Using raw extraction.",
                company.name, e,
            )
            return extracted_text

    async def _extract(self, update: Update) -> str:
        """Extract text from the raw file based on its type."""
        if not update.raw_file_urls:
            raise ValueError("No raw files to process")

        file_bytes = await storage_service.download_file(update.raw_file_urls[0])

        match update.source_file_type:
            case SourceFileType.EXCEL:
                return excel_parser.parse_excel(file_bytes)
            case SourceFileType.CSV:
                return excel_parser.parse_csv(file_bytes)
            case SourceFileType.PDF:
                return pdf_parser.parse(file_bytes)
            case SourceFileType.EMAIL_TEXT:
                return file_bytes.decode("utf-8", errors="replace")
            case _:
                raise ValueError(f"Unsupported file type: {update.source_file_type}")

    # ─── Layer 2: LLM Normalisation ──────────────────────────

    async def _normalise(
        self,
        extracted_text: str,
        company_name: str,
        sector: str,
        accounting_system: str,
        mapping_instructions: str,
        metric_schema: list[dict],
    ) -> NormalisationResponse:
        """Send extracted data to Claude for normalisation."""
        user_prompt = NORMALISATION_USER_TEMPLATE.format(
            company_name=company_name,
            sector=sector,
            accounting_system=accounting_system,
            metric_schema_json=json.dumps(metric_schema, indent=2),
            mapping_instructions=mapping_instructions or "None specified",
            extracted_text=extracted_text[:8000],  # Cap for context window
        )

        response_dict = await llm_service.call_json(
            system_prompt=NORMALISATION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=settings.claude_model_normalisation,
        )

        return NormalisationResponse(**response_dict)

    # ─── Summarisation ────────────────────────────────────────

    async def _summarise(
        self,
        company_name: str,
        sector: str,
        period: str,
        normalised_metrics: dict,
        previous_metrics: dict,
        variances: dict,
        raw_context: str,
    ) -> SummarisationResponse:
        """Generate a human-readable summary via Claude."""
        user_prompt = SUMMARISATION_USER_TEMPLATE.format(
            company_name=company_name,
            sector=sector,
            period=period,
            normalised_metrics_json=json.dumps(normalised_metrics, indent=2),
            previous_metrics_json=json.dumps(previous_metrics, indent=2) if previous_metrics else "No previous data",
            variances_json=json.dumps(variances, indent=2) if variances else "No previous data for comparison",
            raw_context=raw_context,
        )

        response_dict = await llm_service.call_json(
            system_prompt=SUMMARISATION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=settings.claude_model_fast,
            max_tokens=2048,
        )

        return SummarisationResponse(**response_dict)

    # ─── Layer 3: Variance Calculation ────────────────────────

    def _calculate_variances(
        self,
        current: dict[str, float | int | None],
        previous: dict[str, float | int | None],
    ) -> dict[str, float]:
        """Calculate period-over-period percentage changes."""
        variances: dict[str, float] = {}

        for metric, current_val in current.items():
            if current_val is None:
                continue
            prev_val = previous.get(metric)
            if prev_val is None or prev_val == 0:
                continue
            try:
                change = (float(current_val) - float(prev_val)) / abs(float(prev_val))
                variances[metric] = round(change, 4)
            except (TypeError, ValueError, ZeroDivisionError):
                continue

        return variances


# Singleton
normaliser_service = NormaliserService()
