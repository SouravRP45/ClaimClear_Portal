"""
citation_verifier.py — Verifies that LLM-quoted policy clauses exist in the source PDF
"""
import difflib
import logging

logger = logging.getLogger(__name__)


class CitationVerifier:
    """
    Prevents hallucinated policy clauses from reaching the user.
    Every clause quoted by the LLM must pass verification against the source PDF text
    before being marked as verified.
    """

    def verify(
        self,
        quoted_text: str,
        source_full_text: str,
        fuzzy_threshold: float = 0.85,
    ) -> bool:
        """
        Checks whether quoted_text exists (exactly or approximately) in source_full_text.

        Strategy:
        1. Exact substring match (case-insensitive, whitespace-normalized)
        2. Sliding window fuzzy match using difflib.SequenceMatcher
        3. Returns False if neither check passes — NEVER invents a match

        Args:
            quoted_text: The clause the LLM claims to have quoted verbatim
            source_full_text: Full text of the policy PDF
            fuzzy_threshold: Minimum similarity ratio to count as a match (0.0–1.0)

        Returns:
            True if the clause is verified; False otherwise
        """
        if not quoted_text or not source_full_text:
            return False

        # Reject sentinel value immediately
        if quoted_text.strip().upper() == "NO_SUPPORTING_CLAUSE_FOUND":
            return False

        # Normalize whitespace for comparison
        def normalize(text: str) -> str:
            return " ".join(text.lower().split())

        normalized_quote = normalize(quoted_text)
        normalized_source = normalize(source_full_text)

        # ── Step 1: Exact substring match ────────────────────────────────────
        if normalized_quote in normalized_source:
            logger.debug(f"Citation verified (exact match): '{quoted_text[:60]}...'")
            return True

        # ── Step 2: Sliding window fuzzy match ───────────────────────────────
        quote_len = len(normalized_quote)
        window_size = min(
            max(quote_len + 50, 200),   # window slightly larger than the quote
            400,                         # cap to avoid huge windows
        )
        step = max(window_size // 4, 50)

        source_len = len(normalized_source)
        best_ratio = 0.0

        i = 0
        while i < source_len:
            window = normalized_source[i: i + window_size]
            ratio = difflib.SequenceMatcher(
                None, normalized_quote, window, autojunk=False
            ).ratio()

            if ratio > best_ratio:
                best_ratio = ratio

            if ratio >= fuzzy_threshold:
                logger.debug(
                    f"Citation verified (fuzzy {ratio:.2f} >= {fuzzy_threshold}): "
                    f"'{quoted_text[:60]}...'"
                )
                return True

            i += step

        logger.info(
            f"Citation NOT verified (best ratio {best_ratio:.2f} < {fuzzy_threshold}): "
            f"'{quoted_text[:60]}...'"
        )
        return False

    def verify_all_rebuttals(
        self,
        rebuttals: list,   # list[Rebuttal] — avoiding circular import
        source_full_text: str,
    ) -> list:
        """
        Runs verify() on each rebuttal's supporting_clause.
        Mutates and returns the rebuttal list with clause_verified set.
        """
        for rebuttal in rebuttals:
            if rebuttal.supporting_clause.strip().upper() == "NO_SUPPORTING_CLAUSE_FOUND":
                rebuttal.clause_verified = False
                logger.info("Rebuttal marked unverified: sentinel value NO_SUPPORTING_CLAUSE_FOUND")
            else:
                rebuttal.clause_verified = self.verify(
                    rebuttal.supporting_clause, source_full_text
                )
        return rebuttals
