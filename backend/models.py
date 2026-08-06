"""
models.py — All Pydantic v2 schemas for ClaimClear
"""
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


class InsuranceLineType(str, Enum):
    HEALTH = "health"
    AUTO = "auto"
    PROPERTY = "property"
    GENERAL = "general"


class DenialExtract(BaseModel):
    insurer_name: str = Field(description="Name of the insurance company")
    claim_number: str = Field(description="Claim reference number")
    denial_date: str = Field(description="Date the denial was issued")
    claim_type: InsuranceLineType = Field(description="Line of insurance (health/auto/property/general)")
    denial_reason_raw: str = Field(description="Verbatim denial reason text from the letter")
    denial_reason_summary: str = Field(description="Plain-English 1-sentence summary of denial reason")
    policy_sections_cited: list[str] = Field(
        default_factory=list,
        description="Policy section numbers the insurer cited in the denial"
    )
    insurer_contact: str = Field(description="Insurer's appeal mailing address and/or phone number")


class EvidenceItem(BaseModel):
    document: str = Field(description="Name/type of document to gather")
    reason: str = Field(description="Why this document supports the appeal")
    priority: Literal["HIGH", "MED", "LOW"] = Field(description="Priority level for gathering this document")


class Rebuttal(BaseModel):
    argument: str = Field(description="The contractual/legal argument the consumer can make")
    supporting_clause: str = Field(
        description="Exact verbatim text from the policy that supports this argument, "
                    "or 'NO_SUPPORTING_CLAUSE_FOUND' if none exists"
    )
    clause_verified: bool = Field(
        default=False,
        description="True only if CitationVerifier confirmed this clause exists in the source PDF"
    )


class AnalysisResult(BaseModel):
    analysis_id: str = Field(description="UUID for this analysis session")
    denial_valid: bool = Field(
        description="True if the denial is clearly supported by policy language; "
                    "False if it contradicts the policy or is unsupported"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0.0-1.0")
    plain_english_summary: str = Field(description="Consumer-friendly paragraph explaining the situation")
    rebuttals: list[Rebuttal] = Field(description="Arguments the consumer can make in their appeal")
    evidence_needed: list[EvidenceItem] = Field(description="Prioritized list of documents to gather")
    denial_extract: DenialExtract = Field(description="Structured data extracted from the denial letter")
    processing_time_seconds: float = Field(description="Total server-side processing time in seconds")
    legal_disclaimer: str = Field(
        default=(
            "This is educational analysis only, not legal advice. "
            "Review with a licensed insurance professional before submitting."
        ),
        description="Mandatory legal disclaimer shown to the user"
    )


class AppealResponse(BaseModel):
    analysis_id: str = Field(description="UUID matching the originating AnalysisResult")
    appeal_letter: str = Field(description="Full rendered appeal letter text")
    template_used: str = Field(description="Which Jinja2 template was selected")


class ErrorResponse(BaseModel):
    error: str = Field(description="Short error type label")
    detail: str = Field(description="Human-readable explanation of what went wrong")
    suggestion: str = Field(description="What the user can try to fix the problem")
