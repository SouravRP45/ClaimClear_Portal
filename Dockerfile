# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libmupdf-dev \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY backend/requirements.txt .

# Install CPU-only torch first to prevent downloading 2.5GB+ CUDA binaries (avoids Render build timeouts)
RUN pip install --prefix=/install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN useradd --create-home --shell /bin/bash claimclear

WORKDIR /app

# Copy backend source
COPY backend/ ./

# Copy frontend for static file serving
COPY frontend/ ../frontend/

# Pre-cache embedding model so container starts instantly without waiting for download at boot
ENV HF_HOME=/home/claimclear/.cache/huggingface
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

RUN chown -R claimclear:claimclear /app /home/claimclear && \
    chown -R claimclear:claimclear /app/../frontend 2>/dev/null || true

USER claimclear

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
