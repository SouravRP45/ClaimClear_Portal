"""
main.py — ClaimClear FastAPI application entrypoint
"""
import uuid
import time
import traceback
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import config
from models import AnalysisResult, AppealResponse, ErrorResponse
from pdf_extractor import PDFExtractor
from rag_engine import RAGEngine
from denial_extractor import DenialExtractor
from analysis_agent import AnalysisAgent
from appeal_generator import AppealGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("claimclear")

# ── Module singletons (initialized at startup) ──────────────────────────────
rag_engine: RAGEngine | None = None
pdf_extractor: PDFExtractor | None = None
denial_extractor: DenialExtractor | None = None
analysis_agent: AnalysisAgent | None = None
appeal_generator: AppealGenerator | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize all expensive singletons on startup."""
    global rag_engine, pdf_extractor, denial_extractor, analysis_agent, appeal_generator

    logger.info(f"ClaimClear v{config.VERSION} starting up...")
    logger.info(f"LLM model: {config.GEMINI_MODEL}")
    logger.info(f"Embedding model: {config.EMBEDDING_MODEL}")

    # Verify API key is set (config.py raises ValueError if not)
    _ = config.GEMINI_API_KEY

    pdf_extractor = PDFExtractor()
    denial_extractor = DenialExtractor(config.GEMINI_API_KEY)
    analysis_agent = AnalysisAgent(config.GEMINI_API_KEY)

    templates_dir = str(Path(__file__).parent / "templates")
    appeal_generator = AppealGenerator(templates_dir)

    # Warm up embedding model
    logger.info("Warming up sentence-transformer model...")
    rag_engine = RAGEngine()
    _ = rag_engine.model.encode(["warming up"], show_progress_bar=False)
    logger.info("Model warm-up complete. ClaimClear is ready.")

    yield

    logger.info("ClaimClear shutting down.")


# ── Rate limiter ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="ClaimClear API",
    description="AI-powered insurance claim denial analysis and appeal generation",
    version=config.VERSION,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS (all origins for MVP — tighten in production) ───────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global exception handler ─────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal Server Error",
            detail=str(exc),
            suggestion="Please try again. If the problem persists, check the server logs.",
        ).model_dump(),
    )


# ── Mount frontend as static files ───────────────────────────────────────────
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/app", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
    logger.info(f"Frontend mounted at /app from {frontend_dir}")


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return {
        "name": "ClaimClear API",
        "version": config.VERSION,
        "status": "healthy",
        "docs": "/docs",
        "frontend": "/app",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model": config.GEMINI_MODEL,
        "embedding_model": config.EMBEDDING_MODEL,
        "version": config.VERSION,
    }


@app.post(
    "/analyze",
    response_model=AnalysisResult,
    summary="Analyze a claim denial against a policy document",
)
@limiter.limit(config.RATE_LIMIT)
async def analyze(
    request: Request,
    denial_letter: UploadFile = File(..., description="Insurance denial letter (PDF or TXT)"),
    policy_document: UploadFile = File(..., description="Insurance policy document (PDF)"),
):
    """
    Main analysis endpoint.
    Accepts two uploaded files, runs the full 5-step pipeline, and returns
    a structured AnalysisResult with rebuttals, evidence checklist, and summary.
    """
    start_time = time.time()
    session_id = str(uuid.uuid4())
    rag_built = False

    try:
        # ── Step 1: Read uploaded files ──────────────────────────────────────
        denial_bytes = await denial_letter.read()
        policy_bytes = await policy_document.read()

        # ── Step 2: Validate files ───────────────────────────────────────────
        # Policy must be PDF; denial can be PDF or plain text
        max_bytes = int(config.MAX_FILE_SIZE_MB * 1024 * 1024)

        if len(denial_bytes) > max_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"Denial letter exceeds {config.MAX_FILE_SIZE_MB} MB limit.",
            )
        if len(policy_bytes) > max_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"Policy document exceeds {config.MAX_FILE_SIZE_MB} MB limit.",
            )

        # ── Step 3: Extract text ─────────────────────────────────────────────
        # Denial letter: support PDF or plain text
        is_denial_pdf = denial_bytes.startswith(b"%PDF")
        if is_denial_pdf:
            pdf_extractor.validate_pdf(denial_bytes, config.MAX_FILE_SIZE_MB)
            denial_text, _ = pdf_extractor.extract_text(denial_bytes)
        else:
            # Plain text (e.g. sample denial .txt file)
            try:
                denial_text = denial_bytes.decode("utf-8", errors="replace")
            except Exception:
                raise HTTPException(status_code=400, detail="Could not read denial letter as text.")

        if not denial_text.strip():
            raise HTTPException(status_code=400, detail="Denial letter is empty after extraction.")

        # Policy must be PDF
        pdf_extractor.validate_pdf(policy_bytes, config.MAX_FILE_SIZE_MB)
        policy_text, _ = pdf_extractor.extract_text(policy_bytes)

        # ── Step 4: Extract structured denial data ───────────────────────────
        logger.info(f"[{session_id}] Extracting structured denial data...")
        try:
            denial_extract = denial_extractor.extract(denial_text)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Denial extraction failed: {str(e)}")

        # ── Step 5: Build RAG index ──────────────────────────────────────────
        logger.info(f"[{session_id}] Building policy RAG index...")
        try:
            rag_engine.build_index(policy_text, session_id)
            rag_built = True
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Policy indexing failed: {str(e)}")

        # ── Step 6: Retrieve relevant policy chunks ──────────────────────────
        logger.info(f"[{session_id}] Retrieving relevant policy chunks...")
        retrieved_chunks = rag_engine.retrieve(
            query=denial_extract.denial_reason_raw,
            session_id=session_id,
            top_k=config.TOP_K_CHUNKS,
        )

        # ── Step 7: Run contradiction analysis ──────────────────────────────
        logger.info(f"[{session_id}] Running contradiction analysis...")
        try:
            denial_valid, confidence, summary, rebuttals, evidence = analysis_agent.analyze(
                denial_extract=denial_extract,
                retrieved_chunks=retrieved_chunks,
                source_full_text=policy_text,
            )
        except Exception as e:
            if "AI service error" in str(e) or "Gemini" in str(e):
                raise HTTPException(status_code=503, detail=str(e))
            raise HTTPException(status_code=422, detail=str(e))

        # ── Step 8: Assemble result ──────────────────────────────────────────
        processing_time = round(time.time() - start_time, 2)
        logger.info(f"[{session_id}] Analysis complete in {processing_time}s")

        return AnalysisResult(
            analysis_id=session_id,
            denial_valid=denial_valid,
            confidence=confidence,
            plain_english_summary=summary,
            rebuttals=rebuttals,
            evidence_needed=evidence,
            denial_extract=denial_extract,
            processing_time_seconds=processing_time,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"[{session_id}] Unexpected error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
    finally:
        # Always clean up the ChromaDB index
        if rag_built:
            rag_engine.cleanup(session_id)


@app.post(
    "/appeal",
    response_model=AppealResponse,
    summary="Generate an appeal letter from a completed analysis",
)
async def generate_appeal(analysis: AnalysisResult):
    """
    Generates a formatted appeal letter from a completed AnalysisResult.
    The client must send back the full AnalysisResult (no server-side persistence).
    """
    try:
        return appeal_generator.generate(analysis)
    except Exception as e:
        logger.error(f"Appeal generation error: {e}")
        raise HTTPException(status_code=500, detail=f"Appeal generation failed: {str(e)}")


@app.get("/sample-denial", summary="Get the sample denial letter text for testing")
async def sample_denial():
    """Returns the sample denial letter text so users can test without uploading."""
    sample_path = Path(__file__).parent / "sample_data" / "sample_denial.txt"
    try:
        text = sample_path.read_text(encoding="utf-8")
        return {"text": text, "filename": "sample_denial.txt"}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Sample denial letter not found.")


@app.get("/benchmark", summary="Get benchmark test cases for accuracy evaluation")
async def benchmark():
    """Returns the 5 benchmark test cases for evaluating analysis accuracy."""
    import json
    benchmark_path = Path(__file__).parent / "sample_data" / "benchmark_cases.json"
    try:
        cases = json.loads(benchmark_path.read_text(encoding="utf-8"))
        return {"cases": cases, "count": len(cases)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Benchmark cases file not found.")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid benchmark JSON: {e}")
