"""
appeal_generator.py — Jinja2-based appeal letter renderer
"""
import os
from datetime import date
import logging
from jinja2 import Environment, FileSystemLoader, select_autoescape
from models import AnalysisResult, AppealResponse, InsuranceLineType

logger = logging.getLogger(__name__)


class AppealGenerator:
    """Renders professional appeal letters using Jinja2 templates."""

    TEMPLATE_MAP = {
        InsuranceLineType.HEALTH: "appeal_health.j2",
        InsuranceLineType.AUTO: "appeal_auto.j2",
        InsuranceLineType.PROPERTY: "appeal_auto.j2",   # auto template covers property too
        InsuranceLineType.GENERAL: "appeal_general.j2",
    }

    def __init__(self, templates_dir: str) -> None:
        self.env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=select_autoescape(["html"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        logger.info(f"AppealGenerator initialized with templates from: {templates_dir}")

    def generate(self, analysis: AnalysisResult) -> AppealResponse:
        """
        Selects the appropriate template based on claim_type and renders
        the full appeal letter.

        Returns:
            AppealResponse with the rendered letter and template name used.
        """
        claim_type = analysis.denial_extract.claim_type
        template_name = self.TEMPLATE_MAP.get(claim_type, "appeal_general.j2")

        try:
            template = self.env.get_template(template_name)
        except Exception as e:
            logger.error(f"Template not found: {template_name} — {e}")
            # Fall back to general template
            template_name = "appeal_general.j2"
            template = self.env.get_template(template_name)

        # Sort evidence items: HIGH first, then MED, then LOW
        priority_order = {"HIGH": 0, "MED": 1, "LOW": 2}
        sorted_evidence = sorted(
            analysis.evidence_needed,
            key=lambda e: priority_order.get(e.priority, 99),
        )

        # Only include rebuttals with verified clauses or non-sentinel supporting clauses
        valid_rebuttals = [
            r for r in analysis.rebuttals
            if r.clause_verified or r.supporting_clause.strip().upper() != "NO_SUPPORTING_CLAUSE_FOUND"
        ]

        context = {
            "today_date": date.today().strftime("%B %d, %Y"),
            "analysis": analysis,
            "denial_extract": analysis.denial_extract,
            "rebuttals": valid_rebuttals,
            "evidence_needed": sorted_evidence,
            "all_rebuttals": analysis.rebuttals,
        }

        rendered = template.render(**context)
        logger.info(
            f"Generated appeal letter using template '{template_name}' "
            f"({len(rendered)} characters)"
        )

        return AppealResponse(
            analysis_id=analysis.analysis_id,
            appeal_letter=rendered,
            template_used=template_name,
        )
