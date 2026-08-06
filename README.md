# ClaimClear ⚖️

> **Your insurer said no. We'll show you why — and write your appeal.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green.svg)](https://fastapi.tiangolo.com)

---

## What Is This?

Every year, 1 in 5 insurance claims is denied on first submission. Yet fewer than 1% of policyholders ever appeal — despite an 80%+ overturn rate when they do. The reason? The process is opaque, intimidating, and time-consuming.

**ClaimClear** is an AI-powered claim denial decoder for individual policyholders. Upload your denial letter and your insurance policy document. In under 60 seconds, it tells you exactly why you were denied, cross-references the denial reason against your actual policy language, identifies contradictions the insurer may have made, and generates a professionally-written, evidence-backed appeal letter — ready to sign and send.

No account required. Works for health, auto, property, and any line of insurance. Free and open source.

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                      ClaimClear Pipeline                            │
│                                                                     │
│  [Denial Letter PDF]  ──┐                                           │
│                         ▼                                           │
│                    PDF Extractor                                     │
│                    (PyMuPDF + OCR)                                   │
│                         │                                           │
│                         ▼                                           │
│                   Denial Extractor  ──→  {insurer, reason, date}    │
│                   (Gemini + JSON)                                    │
│                         │                                           │
│  [Policy PDF]    ──┐    ▼                                           │
│                   │  RAG Engine  ──→  Top-5 relevant policy chunks  │
│                   │  (ChromaDB +                                     │
│                   │  sentence-transformers)                          │
│                   │    │                                             │
│                   │    ▼                                             │
│                   └─→ Analysis Agent  ──→  {denial_valid,           │
│                       (Gemini)              rebuttals,              │
│                         │                  evidence_needed}         │
│                         │                                           │
│                         ▼                                           │
│                  Citation Verifier  ──→  clause_verified flag       │
│                  (difflib fuzzy match)                               │
│                         │                                           │
│                         ▼                                           │
│                  Appeal Generator  ──→  Full formatted letter       │
│                  (Jinja2 templates)                                  │
│                         │                                           │
│                         ▼                                           │
│               Consumer-facing UI output                             │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Tool | Why |
|-------|------|-----|
| Frontend | HTML + Vanilla CSS + JS | Zero build step, instant deploy |
| Backend | Python + FastAPI | Async, clean API, Python AI ecosystem |
| PDF Parsing | PyMuPDF | Best accuracy on insurance PDFs with tables |
| Embeddings | sentence-transformers all-MiniLM-L6-v2 | Free, fully local, no API call |
| Vector DB | ChromaDB (in-memory) | Zero server setup, ephemeral, no cost |
| LLM | Google Gemini 2.5 Flash | 1M token context, generous free tier |
| Structured output | Pydantic v2 + Gemini JSON mode | Reliable typed extraction |
| Appeal templates | Jinja2 | Clean, customizable rendering |
| Deployment | Railway / Render / Docker | Free tier deployment in 5 minutes |

---

## Quick Start (Local)

### Prerequisites
- Python 3.11+
- A free Gemini API key from [aistudio.google.com](https://aistudio.google.com/)
- (Optional) Tesseract OCR for scanned PDFs: [Installation guide](https://github.com/tesseract-ocr/tesseract)

### Setup

```bash
# 1. Clone
git clone https://github.com/your-username/claimclear.git
cd claimclear

# 2. Configure environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# 3. Install dependencies
cd backend
pip install -r requirements.txt

# 4. Start the backend
uvicorn main:app --reload --port 8000
# API docs: http://localhost:8000/docs

# 5. In a second terminal, serve the frontend
python -m http.server 3000 --directory ../frontend
# Open: http://localhost:3000
```

**Or access the frontend via the backend (single server):**
After starting uvicorn, visit `http://localhost:8000/app` — the frontend is served as static files.

---

## Docker Deployment (Recommended)

```bash
# Build and run everything in one command
docker-compose up --build

# Frontend at: http://localhost:8000/app
# API at:      http://localhost:8000
# API docs at: http://localhost:8000/docs
```

---

## Deploy to Railway (Free, ~5 minutes)

1. Fork this repository
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
3. Select your fork
4. In Railway dashboard: **Variables** → Add `GEMINI_API_KEY=your_key_here`
5. Railway auto-detects `railway.toml` and deploys. Done.

---

## Deploy to Render (Free)

1. Fork this repository
2. Go to [render.com](https://render.com) → **New** → **Web Service** → connect GitHub repo
3. Render auto-detects `render.yaml`
4. In Render dashboard: **Environment** → Add `GEMINI_API_KEY=your_key_here`
5. Click **Deploy**. Done.

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health + version info |
| `/health` | GET | Detailed health check |
| `/analyze` | POST | Main analysis — accepts `denial_letter` + `policy_document` (multipart) |
| `/appeal` | POST | Generate appeal letter from `AnalysisResult` JSON |
| `/sample-denial` | GET | Returns sample denial letter text for testing |
| `/benchmark` | GET | Returns 5 benchmark test cases |

**Rate limit:** 10 requests/hour per IP on `/analyze`.

### Example: Analyze a Denial

```bash
curl -X POST http://localhost:8000/analyze \
  -F "denial_letter=@my_denial.pdf" \
  -F "policy_document=@my_policy.pdf"
```

### Response Schema

```json
{
  "analysis_id": "uuid",
  "denial_valid": false,
  "confidence": 0.87,
  "plain_english_summary": "Your claim was denied because...",
  "rebuttals": [
    {
      "argument": "Your policy explicitly covers...",
      "supporting_clause": "Section 4.2 states...",
      "clause_verified": true
    }
  ],
  "evidence_needed": [
    { "document": "EOB", "reason": "...", "priority": "HIGH" }
  ],
  "denial_extract": { "insurer_name": "...", "claim_number": "...", ... },
  "processing_time_seconds": 12.4,
  "legal_disclaimer": "This is educational analysis only..."
}
```

---

## Running Benchmarks

```bash
cd backend
python -c "
import json
from pathlib import Path

cases = json.loads(Path('sample_data/benchmark_cases.json').read_text())
print(f'Loaded {len(cases)} benchmark cases:')
for case in cases:
    print(f'  [{case[\"case_id\"]}] {case[\"description\"]}')
    print(f'        Expected denial_valid: {case[\"expected_denial_valid\"]}')
"
```

To run a live benchmark against the API:
```bash
# Start the backend first, then:
python -c "
import httpx, json
from pathlib import Path

cases = json.loads(Path('sample_data/benchmark_cases.json').read_text())
# Use the denial_reason and relevant_policy_clause from each case
# to manually construct test PDFs or call the /analyze endpoint
print('Use the benchmark_cases.json to build test fixtures and evaluate accuracy')
"
```

---

## Limitations & Disclaimers

- **Not legal advice.** ClaimClear is an educational tool. Always review generated appeals with a licensed insurance professional or attorney before submitting.
- **Accuracy depends on PDF quality.** Scanned images require OCR, which may introduce errors. Text-based PDFs produce the best results.
- **Hallucination prevention is built in** via citation verification, but is not perfect. Always verify quoted policy language against your original document.
- **Rate limited** to 10 analyses/hour per IP in the current MVP.
- **No persistence.** Each session is ephemeral. Close the browser and the analysis is gone.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Contributing

Pull requests welcome. Please open an issue first for significant changes.

**Found a bug?** Open an issue with the insurer name (redacted), claim type, and a description of what went wrong.
