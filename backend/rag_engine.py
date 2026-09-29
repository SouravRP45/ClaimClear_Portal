"""
rag_engine.py — Lightweight in-memory vector store for policy document retrieval.

Uses Google Gemini Embeddings (models/gemini-embedding-001) + NumPy cosine similarity.
Runs entirely in API + NumPy, requiring zero heavy PyTorch/CUDA packages, and comfortably
stays under 80MB memory (well within Render's 512MB free tier limit).
"""
import re
import logging
import numpy as np
import google.generativeai as genai
from config import config

logger = logging.getLogger(__name__)


class RAGEngine:
    """
    Builds an ephemeral in-memory vector index from policy text and retrieves
    the most semantically relevant chunks for a given denial reason query.

    Implementation: Google Gemini Embeddings + pure NumPy cosine similarity.
    No PyTorch, zero C++ compilation, minimal RAM footprint (<80MB).
    """

    def __init__(self) -> None:
        self.embedding_model = config.EMBEDDING_MODEL
        genai.configure(api_key=config.GEMINI_API_KEY)
        # session_id → {"chunks": list[str], "metadatas": list[dict],
        #                "embeddings": np.ndarray (N, D)}
        self._store: dict[str, dict] = {}
        logger.info(f"RAGEngine initialized with embedding model: {self.embedding_model}")

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _extract_page_hint(self, words: list[str], word_start: int) -> str:
        """Scans backwards to find the nearest [PAGE N] marker."""
        partial = " ".join(words[:word_start])
        matches = list(re.finditer(r"\[PAGE (\d+)\]", partial))
        if matches:
            return f"approx. page {matches[-1].group(1)}"
        return "page unknown"

    def _embed_texts(self, texts: list[str]) -> np.ndarray:
        """
        Embeds a list of texts using Gemini API with batching and L2 normalization.
        Pre-normalizing makes cosine similarity a simple dot product.
        """
        if not texts:
            return np.empty((0, 3072), dtype=np.float32)

        batch_size = 50
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            res = genai.embed_content(
                model=self.embedding_model,
                content=batch,
            )
            # res['embedding'] contains the list of embeddings for the batch
            emb_list = res.get("embedding", [])
            # Handle both single list (if single item) or list of lists
            if emb_list and isinstance(emb_list[0], (int, float)):
                all_embeddings.append(emb_list)
            else:
                all_embeddings.extend(emb_list)

        embeddings = np.array(all_embeddings, dtype=np.float32)

        # L2-normalize each vector (rows)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1e-10, norms)
        return embeddings / norms

    # ── Public API ───────────────────────────────────────────────────────────

    def build_index(self, full_text: str, session_id: str) -> str:
        """
        Chunks the policy text, embeds each chunk using Gemini Embeddings,
        and stores everything in memory keyed by session_id.
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

        # Embed all chunks
        embeddings = self._embed_texts(chunks)

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
        matching the convention used in analysis_agent.py.
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

        # Embed the query (normalized vector of shape (D,))
        query_vec = self._embed_texts([query])[0]

        # Cosine similarity (both embeddings and query_vec are pre-normalized)
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

