"""
denial_extractor.py — Structured extraction from insurance denial letters using Gemini
"""
import json
import logging
import google.generativeai as genai
from models import DenialExtract, InsuranceLineType
from config import config

logger = logging.getLogger(__name__)

_EXTRACTION_SYSTEM_PROMPT = """You are an insurance claim analyst. Extract structured information from the insurance denial letter text provided. Be precise and conservative — if a field is not clearly present in the text, return "NOT FOUND" for string fields rather than guessing.

For claim_type, classify based on these rules:
- "health" if mentions: medical, hospital, treatment, prescription, physician, diagnosis, procedure, therapy
- "auto" if mentions: vehicle, car, accident, collision, comprehensive, liability, property damage to vehicle
- "property" if mentions: home, homeowner, dwelling, flood, fire, theft, renter
- "general" for anything else or if unclear

Return your answer as a JSON object with exactly these fields:
{
  "insurer_name": "string — name of the insurance company",
  "claim_number": "string — claim reference number from the letter",
  "denial_date": "string — date the denial was issued (e.g. January 15, 2025)",
  "claim_type": "health" | "auto" | "property" | "general",
  "denial_reason_raw": "string — verbatim denial reason exactly as written in the letter",
  "policy_sections_cited": ["list", "of", "section", "numbers", "mentioned"],
  "insurer_contact": "string — appeal mailing address and/or phone number from the letter"
}

Output ONLY valid JSON. No markdown, no explanation, no code fences."""


class DenialExtractor:
    """Extracts structured fields from insurance denial letter text using Gemini."""

    def __init__(self, gemini_api_key: str) -> None:
        genai.configure(api_key=gemini_api_key)
        self.model = genai.GenerativeModel(
            model_name=config.GEMINI_MODEL,
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,   # Low temperature for factual extraction
                response_mime_type="application/json",
            ),
        )

    def extract(self, denial_text: str) -> DenialExtract:
        """
        Extracts structured denial data from denial letter text.

        Makes two Gemini calls:
        1. Structured field extraction
        2. Plain-English summary of the denial reason

        Returns a fully populated DenialExtract model.
        """
        # ── Call 1: Structured extraction ────────────────────────────────────
        extraction_prompt = (
            f"{_EXTRACTION_SYSTEM_PROMPT}\n\n"
            f"DENIAL LETTER TEXT:\n{denial_text}"
        )

        try:
            extraction_response = self.model.generate_content(extraction_prompt)
            raw_json = extraction_response.text.strip()

            # Strip markdown code fences if model ignores the instruction
            if raw_json.startswith("```"):
                lines = raw_json.split("\n")
                lines = [l for l in lines if not l.startswith("```")]
                raw_json = "\n".join(lines)

            extracted = json.loads(raw_json)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in denial extraction: {e}\nRaw: {raw_json[:500]}")
            raise ValueError(
                "Could not parse structured data from the denial letter. "
                "The letter format may be unusual. Please ensure the PDF contains readable text."
            )
        except Exception as e:
            logger.error(f"Gemini API error during denial extraction: {e}")
            raise RuntimeError(
                f"AI service error during denial letter analysis: {str(e)}"
            )

        # ── Resolve claim_type safely ─────────────────────────────────────────
        raw_type = extracted.get("claim_type", "general").lower()
        try:
            claim_type = InsuranceLineType(raw_type)
        except ValueError:
            claim_type = InsuranceLineType.GENERAL

        denial_reason_raw = extracted.get("denial_reason_raw", "NOT FOUND")

        # ── Call 2: Plain-English summary of denial reason ───────────────────
        summary_prompt = (
            "Summarize this insurance denial reason in ONE plain-English sentence "
            "that a non-expert consumer can understand. Be concise and factual. "
            "Do not use insurance jargon. Start the sentence with 'Your claim was denied because'.\n\n"
            f"Denial reason: {denial_reason_raw}"
        )

        try:
            summary_model = genai.GenerativeModel(
                model_name=config.GEMINI_MODEL,
                generation_config=genai.types.GenerationConfig(temperature=0.3),
            )
            summary_response = summary_model.generate_content(summary_prompt)
            denial_reason_summary = summary_response.text.strip()
        except Exception as e:
            logger.warning(f"Could not generate denial reason summary: {e}")
            denial_reason_summary = f"Your claim was denied because: {denial_reason_raw}"

        return DenialExtract(
            insurer_name=extracted.get("insurer_name", "NOT FOUND"),
            claim_number=extracted.get("claim_number", "NOT FOUND"),
            denial_date=extracted.get("denial_date", "NOT FOUND"),
            claim_type=claim_type,
            denial_reason_raw=denial_reason_raw,
            denial_reason_summary=denial_reason_summary,
            policy_sections_cited=extracted.get("policy_sections_cited", []),
            insurer_contact=extracted.get("insurer_contact", "NOT FOUND"),
        )
