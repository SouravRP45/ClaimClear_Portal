"""
analysis_agent.py — Core contradiction analysis between denial reason and policy text
"""
import json
import logging
import google.generativeai as genai
from models import DenialExtract, EvidenceItem, Rebuttal
from citation_verifier import CitationVerifier
from config import config

logger = logging.getLogger(__name__)


class AnalysisAgent:
    """
    Sends a carefully engineered prompt to Gemini that compares the denial reason
    against retrieved policy chunks and returns structured rebuttals + evidence items.
    """

    def __init__(self, gemini_api_key: str) -> None:
        genai.configure(api_key=gemini_api_key)
        self.model = genai.GenerativeModel(
            model_name=config.GEMINI_MODEL,
            generation_config=genai.types.GenerationConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
        self.verifier = CitationVerifier()

    def _format_chunks(self, chunks: list[dict]) -> str:
        """Formats retrieved chunks into numbered context blocks for the prompt."""
        formatted = []
        for i, chunk in enumerate(chunks):
            formatted.append(
                f"--- CHUNK {i + 1} (approx. {chunk.get('page_hint', 'unknown')}) ---\n"
                f"{chunk['text']}"
            )
        return "\n\n".join(formatted)

    def analyze(
        self,
        denial_extract: DenialExtract,
        retrieved_chunks: list[dict],
        source_full_text: str,
    ) -> tuple[bool, float, str, list[Rebuttal], list[EvidenceItem]]:
        """
        Core reasoning step: cross-references denial reason against policy chunks.

        Returns:
            (denial_valid, confidence, plain_english_summary, rebuttals, evidence_needed)
        """
        policy_context = self._format_chunks(retrieved_chunks)
        sections_cited = (
            ", ".join(denial_extract.policy_sections_cited)
            if denial_extract.policy_sections_cited
            else "none specified"
        )

        analysis_prompt = f"""SYSTEM INSTRUCTION:
You are a neutral insurance policy analyst helping a consumer understand their claim denial. Your job is to compare the insurer's stated reason for denial against the actual policy language. Be precise and factual. Do not make up policy language — only reference text provided to you in the POLICY CONTEXT section below. If the policy context does not contain text that supports or contradicts the denial, say so explicitly.

DENIAL INFORMATION:
- Insurer: {denial_extract.insurer_name}
- Claim Type: {denial_extract.claim_type.value}
- Denial Reason: {denial_extract.denial_reason_raw}
- Policy Sections Cited by Insurer: {sections_cited}

POLICY CONTEXT (retrieved from the consumer's actual policy document):
{policy_context}

YOUR TASK — Return ONLY a JSON object with exactly this structure:
{{
  "denial_valid": <true if the denial reason is clearly supported by the policy context above, false if it contradicts the policy or the policy context is insufficient to support it>,
  "confidence": <float between 0.0 and 1.0; use 0.9+ for very clear contradiction, 0.5-0.9 for ambiguous, below 0.5 for insufficient context>,
  "plain_english_summary": <one paragraph starting with "Your claim was denied because..." and if denial_valid is false, continuing with "However, your policy appears to state...">,
  "rebuttals": [
    {{
      "argument": <the specific legal or contractual argument the consumer can make in their appeal>,
      "supporting_clause": <EXACT verbatim text copied from the POLICY CONTEXT above that supports this argument — if none exists, use the string "NO_SUPPORTING_CLAUSE_FOUND">
    }}
  ],
  "evidence_needed": [
    {{
      "document": <name of the specific document to gather>,
      "reason": <why this document strengthens the appeal>,
      "priority": <"HIGH" | "MED" | "LOW">
    }}
  ]
}}

CRITICAL RULES YOU MUST FOLLOW:
1. supporting_clause MUST be copied verbatim from the POLICY CONTEXT above. Do NOT paraphrase or alter it. Do NOT invent text not present above.
2. If no policy context supports an argument, use "NO_SUPPORTING_CLAUSE_FOUND" in supporting_clause — never fabricate.
3. Generate between 2 and 4 rebuttals and between 3 and 6 evidence items.
4. evidence_needed must include at minimum: (a) the original Explanation of Benefits (EOB) or claim summary, and (b) the policy document itself.
5. confidence should reflect how clearly the policy text addresses the denial.
6. Output ONLY valid JSON. No markdown fences, no commentary."""

        try:
            response = self.model.generate_content(analysis_prompt)
            raw_json = response.text.strip()

            # Strip markdown code fences if model adds them
            if raw_json.startswith("```"):
                lines = raw_json.split("\n")
                lines = [l for l in lines if not l.startswith("```")]
                raw_json = "\n".join(lines)

            data = json.loads(raw_json)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in analysis: {e}")
            raise ValueError(
                "The AI returned an unexpected response format during analysis. "
                "Please try again."
            )
        except Exception as e:
            logger.error(f"Gemini API error during analysis: {e}")
            raise RuntimeError(f"AI service error during policy analysis: {str(e)}")

        # ── Parse rebuttals ─────────────────────────────────────────────────
        raw_rebuttals = data.get("rebuttals", [])
        rebuttals: list[Rebuttal] = []
        for r in raw_rebuttals:
            supporting_clause = r.get("supporting_clause", "NO_SUPPORTING_CLAUSE_FOUND")
            rebuttals.append(
                Rebuttal(
                    argument=r.get("argument", ""),
                    supporting_clause=supporting_clause,
                    clause_verified=False,  # will be set by verifier below
                )
            )

        # ── Apply citation verification ─────────────────────────────────────
        rebuttals = self.verifier.verify_all_rebuttals(rebuttals, source_full_text)

        # ── Parse evidence items ────────────────────────────────────────────
        raw_evidence = data.get("evidence_needed", [])
        evidence_items: list[EvidenceItem] = []
        for e in raw_evidence:
            priority = e.get("priority", "LOW").upper()
            if priority not in ("HIGH", "MED", "LOW"):
                priority = "LOW"
            evidence_items.append(
                EvidenceItem(
                    document=e.get("document", ""),
                    reason=e.get("reason", ""),
                    priority=priority,  # type: ignore[arg-type]
                )
            )

        # ── Ensure minimum required evidence items exist ────────────────────
        doc_names = [e.document.lower() for e in evidence_items]
        if not any("eob" in d or "explanation of benefit" in d or "claim summary" in d for d in doc_names):
            evidence_items.insert(0, EvidenceItem(
                document="Explanation of Benefits (EOB) or Claim Summary",
                reason="Provides the official record of what was submitted, processed, and denied.",
                priority="HIGH",
            ))
        if not any("policy" in d for d in doc_names):
            evidence_items.append(EvidenceItem(
                document="Your Full Insurance Policy Document",
                reason="The primary document proving your coverage terms and conditions.",
                priority="HIGH",
            ))

        return (
            bool(data.get("denial_valid", False)),
            float(data.get("confidence", 0.5)),
            str(data.get("plain_english_summary", "")),
            rebuttals,
            evidence_items,
        )
