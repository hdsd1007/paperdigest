# PaperDigest

Convert academic research paper PDFs into narrative digest articles (Substack-style) with AI-generated diagrams, key tables, and Jupyter notebooks. Powered by Google Gemini.

## Prerequisites

- **Python 3.11+** (via [conda](https://docs.conda.io/en/latest/miniconda.html) or [miniforge](https://github.com/conda-forge/miniforge))
- **Git** (for cloning vendor dependencies)
- **Google API Key** — get one free at [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

## Quick Start

```bash
# 1. Clone the repo
git clone <repo-url>
cd PaperDigest

# 2. Run setup (creates conda env, installs deps, clones vendor libs)
bash setup.sh

# 3. Add your API key
#    Edit .env and set GOOGLE_API_KEY=your_key_here

# 4. Activate the environment
conda activate paperdigest

# 5. Start the server
cd backend && uvicorn main:app --reload --port 8000

# 6. Open in your browser
#    http://localhost:8000
```

## Usage

1. Open `http://localhost:8000` in your browser
2. Upload a research paper PDF
3. Wait for the pipeline to process (progress shown in real-time)
4. View your digest — includes narrative summary, AI diagrams, key tables
5. Download the generated notebook (.ipynb) or open in Google Colab

## Environment Variables

Set these in your `.env` file (created from `.env.example` by `setup.sh`):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_API_KEY` | Yes | — | Google AI Studio API key |
| `LLM_MODEL` | No | `gemini-2.5-flash` | Gemini model to use |
| `NUM_DIAGRAMS` | No | `10` | Number of AI diagrams to generate |
| `PAPERBANANA_ITERATIONS` | No | `3` | Diagram refinement iterations |
| `ART_DIRECT` | No | `1` | Art-direction passes per diagram (0 to disable) |
| `ORCHESTRATOR_ITERATIONS` | No | `5` | Code-into-summary refinement passes |
| `P2N_API_URL` | No | Railway deploy | paper-to-notebook API URL |

## Project Structure

```
PaperDigest/
├── backend/            # FastAPI application
│   ├── main.py         # API routes & pipeline orchestration
│   ├── llm_client.py   # Gemini API wrapper
│   ├── pdf_parser.py   # PDF → Markdown conversion
│   ├── summarizer.py   # Narrative digest generation
│   ├── diagram_gen.py  # AI diagram generation (PaperBanana)
│   ├── art_director.py # Diagram art-direction
│   ├── table_extractor.py  # Key table extraction
│   ├── orchestrator.py # Final HTML rendering (Markdown + KaTeX)
│   ├── notebook_gen.py # Jupyter notebook generation
│   └── ...
├── frontend/
│   └── index.html      # Single-page UI (vanilla HTML/CSS/JS)
├── setup.sh            # One-shot setup script
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
└── CLAUDE.md           # Project documentation
```

## Pipeline

PDF upload triggers this sequence:

1. **Parse PDF** — Gemini converts PDF to Markdown
2. **Extract figures** — PyMuPDF pulls original figures (archival)
3. **Extract tables** — Finds markdown tables, LLM selects the 1-2 most important
4. **Generate summary** — Narrative digest with `[DIAGRAM:]` and `[TABLE:]` placeholders
5. **Art-direct diagrams** — LLM rewrites diagram specs for precision rendering
6. **Generate diagrams** — PaperBanana renders AI diagrams to PNG
7. **Generate notebook** — Creates a runnable Colab notebook from the paper
8. **Refine with code** — Inserts pseudo-code snippets into the summary
9. **Build HTML** — Final digest with embedded diagrams, tables, and KaTeX math

## Troubleshooting

- **"GOOGLE_API_KEY not set"** — Make sure you added your key to `.env`
- **Diagram generation fails** — Pipeline continues gracefully; diagrams are skipped
- **Notebook generation fails** — Falls back to a hosted notebook link
- **Port 8000 in use** — Change port: `uvicorn main:app --reload --port 8001`
