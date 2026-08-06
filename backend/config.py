"""
config.py — ClaimClear Environment Configuration
"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)


class Config:
    # ── LLM ────────────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

    # ── Embeddings ──────────────────────────────────────────────────────────
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    # ── RAG ─────────────────────────────────────────────────────────────────
    CHUNK_SIZE: int = 400       # words per chunk (approximate tokens)
    CHUNK_OVERLAP: int = 50     # overlapping words between consecutive chunks
    TOP_K_CHUNKS: int = 5       # chunks retrieved per query

    # ── Upload limits ────────────────────────────────────────────────────────
    MAX_FILE_SIZE_MB: float = 10.0

    # ── Rate limiting ────────────────────────────────────────────────────────
    RATE_LIMIT: str = "10/hour"

    # ── Versioning ───────────────────────────────────────────────────────────
    VERSION: str = "1.0.0"

    def __init__(self) -> None:
        if not self.GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY environment variable is not set.\n"
                "Get a free API key at https://aistudio.google.com/ and add it to your .env file:\n"
                "  GEMINI_API_KEY=your_key_here"
            )


config = Config()
