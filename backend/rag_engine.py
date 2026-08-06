"""
rag_engine.py — Pure-numpy in-memory vector store for policy document retrieval.

Replaces ChromaDB to avoid the C++ build tools requirement on Windows.
For MVP-scale policy documents (a few hundred chunks) numpy cosine similarity
is more than fast enough and requires zero compilation.
"""
import re
import logging
import numpy as np
from sentence_transformers import SentenceTransformer
from config import config

logger = logging.getLogger(__name__)


class RAGEngine:
    """
    Builds an ephemeral in-memory vector index from policy text and retrieves
    the most semantically relevant chunks for a given denial reason query.

    Implementation: sentence-transformers embeddings + numpy cosine similarity.
    No C++ compilation required — works on any platform.
    """

    def __init__(self) -> None:
        logger.info(f"Loading embedding model: {config.EMBEDDING_MODEL}")
        self.model = SentenceTransformer(config.EMBEDDING_MODEL)
        # session_id → {"chunks": list[str], "metadatas": list[dict],
        #                "embeddings": np.ndarray (N, D)}
        self._store: dict[str, dict] = {}
        logger.info("RAGEngine (numpy backend) initialized")

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _extract_page_hint(self, words: list[str], word_start: int) -> str:
        """Scans backwards to find the nearest [PAGE N] marker."""
        partial = " ".join(words[:word_start])
        matches = list(re.finditer(r"\[PAGE (\d+)\]", partial))
        if matches:
            return f"approx. page {matches[-1].group(1)}"
        return "page unknown"

    @staticmethod
    def _cosine_similarity(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
        """
        Computes cosine similarity between a 1-D query vector and each row
        of a 2-D embedding matrix.

        Returns a 1-D array of similarities in range [-1, 1].
        """
        query_norm = np.linalg.norm(query_vec)
        matrix_norms = np.linalg.norm(matrix, axis=1)

        # Avoid division by zero
        safe_norms = np.where(matrix_norms == 0, 1e-10, matrix_norms)
        safe_query_norm = query_norm if query_norm > 0 else 1e-10

        dots = matrix @ query_vec  # (N,)
        return dots / (safe_norms * safe_query_norm)

    # ── Public API ───────────────────────────────────────────────────────────

    def build_index(self, full_text: str, session_id: str) -> str:
        """
        Chunks the policy text, embeds each chunk, and stores everything
        in memory keyed by session_id.

        Args:
            full_text: Full extracted policy text with [PAGE N] markers
            session_id: Unique session UUID

        Returns:
            session_id (collection name, for API compatibility)
        """
        words = full_text.split()
        total_words = len(words)

        if total_words == 0:
            raise ValueError("Policy document produced no text to index.")

        chunk_size = config.CHUNK_SIZE
        chunk_overlap = config.CHUNK_OVERLAP
        step = chunk_size - chunk_overlap

        chunks: list[str] = []
        metadatas: list[dict] = []

        chunk_index = 0
        word_start = 0

        while word_start < total_words:
            word_end = min(word_start + chunk_size, total_words)
            chunk_words = words[word_start:word_end]
            chunk_text = " ".join(chunk_words)
            page_hint = self._extract_page_hint(words, word_start)

            chunks.append(chunk_text)
            metadatas.append({
                "chunk_index": chunk_index,
                "page_hint": page_hint,
                "word_start": word_start,
                "word_end": word_end,
            })

            chunk_index += 1
            word_start += step
            if word_end == total_words:
                break

        logger.info(f"[{session_id}] Created {len(chunks)} chunks from {total_words} words")

        # Embed all chunks in one batched call
        embeddings: np.ndarray = self.model.encode(
            chunks,
            batch_size=32,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,   # pre-normalize for faster cosine sim
        )

        self._store[session_id] = {
            "chunks": chunks,
            "metadatas": metadatas,
            "embeddings": embeddings,  # shape: (N, embedding_dim)
        }

        logger.info(
            f"[{session_id}] Indexed {len(chunks)} chunks "
            f"(embedding shape: {embeddings.shape})"
        )
        return session_id

    def retrieve(self, query: str, session_id: str, top_k: int = 5) -> list[dict]:
        """
        Retrieves the top_k most semantically relevant chunks for a query.

        Returns:
            List of dicts sorted by relevance (most relevant first):
            {"text": str, "chunk_index": int, "page_hint": str, "distance": float}

        Note: "distance" here is 1 - cosine_similarity so that lower = more relevant,
        matching the ChromaDB convention used in analysis_agent.py.
        """
        if session_id not in self._store:
            raise ValueError(
                f"No policy index found for session '{session_id}'. "
                "The index may have already been cleaned up."
            )

        store = self._store[session_id]
        chunks = store["chunks"]
        metadatas = store["metadatas"]
        embeddings: np.ndarray = store["embeddings"]

        # Embed the query (normalized)
        query_vec: np.ndarray = self.model.encode(
            [query],
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )[0]

        # Cosine similarity (embeddings are pre-normalized → dot product == cosine sim)
        similarities = embeddings @ query_vec  # (N,)

        # Take top_k indices (highest similarity)
        k = min(top_k, len(chunks))
        top_indices = np.argpartition(similarities, -k)[-k:]
        top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]

        retrieved: list[dict] = []
        for idx in top_indices:
            retrieved.append({
                "text": chunks[idx],
                "chunk_index": int(metadatas[idx]["chunk_index"]),
                "page_hint": metadatas[idx]["page_hint"],
                "distance": float(1.0 - similarities[idx]),  # convert to distance
            })

        if retrieved:
            logger.info(
                f"[{session_id}] Retrieved {len(retrieved)} chunks "
                f"(top similarity: {1.0 - retrieved[0]['distance']:.4f})"
            )
        return retrieved

    def cleanup(self, session_id: str) -> None:
        """Removes the session index from memory."""
        if session_id in self._store:
            del self._store[session_id]
            logger.info(f"[{session_id}] Cleaned up in-memory index")
        else:
            logger.warning(f"[{session_id}] cleanup called but session not found")
