# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PaperDigest converts academic research paper PDFs into narrative digest articles (Substack-style) with AI-generated diagrams, key tables, and Jupyter notebooks. Uses **Google Gemini** for all LLM tasks. **PaperBanana** handles diagram generation (with art-direction rewriting for quality). **paper-to-notebook** generates runnable Colab notebooks.

## Reading Philosophy

When reading a paper, the natural flow is: title → abstract → images → conclusion → important tables.
PaperDigest mirrors this:

1. **Title + abstract story** — The Big Picture opens with a narrative retelling of the abstract
2. **AI figures** — Art-directed AI-generated diagrams illustrate key concepts
3. **Key tables** — 1-2 most important results/comparison tables surface in the digest
4. **Minimal code** — At most 2 pseudo-code snippets (not verbatim), placed only in technical sections
5. **Polish** — Multiple refinement passes produce a clean, professional reading experience

## Setup & Development

```bash
# First-time setup (creates conda env, installs deps, clones vendor libs)
bash setup.sh

# Install deps (if not done via setup.sh)
pip install -r requirements.txt
pip install nbformat google-genai

# Run the dev server
conda activate paperdigest
cd backend && uvicorn main:app --reload --port 8000
# Frontend served at http://localhost:8000
```

**Environment variables** (in `.env`):
- `GOOGLE_API_KEY` — required (used by Gemini, PaperBanana diagrams, and paper-to-notebook)
- `LLM_MODEL` (optional) — override model name (default: `gemini-2.5-flash`)
- `NUM_DIAGRAMS` (optional) — number of diagrams to generate, defaults to 10
- `P2N_API_URL` (optional) — paper-to-notebook API, defaults to Railway deployment
- `PAPERBANANA_ITERATIONS` (optional) — diagram refinement iterations, defaults to 3
- `ART_DIRECT` (optional) — number of art-direction passes per diagram (default: `1`). Set `0` to disable.
- `ORCHESTRATOR_ITERATIONS` (optional) — code-into-summary refinement passes, defaults to 5 (set 0 to skip)

## Architecture

**Stack:** FastAPI backend (Python 3.10+) + vanilla HTML/CSS/JS frontend (no build system, no npm).

### Processing Pipeline

PDF upload → `main.py` spawns a background thread that runs this pipeline sequentially:

1. **`pdf_parser.py`** — Gemini converts PDF to Markdown (via `llm_call()` from `llm_client.py`)
2. **`figure_extractor.py`** — PyMuPDF extracts original figures from the PDF (CPU-only, fast, archival only)
3. **`pdf_parser.py`** → `extract_abstract()` — Regex-based abstract extraction from parsed markdown
4. **`table_extractor.py`** — Regex finds markdown tables, LLM selects 1-2 most important ones
5. **`summarizer.py`** — Gemini generates narrative digest with `[DIAGRAM: ...]` and `[TABLE: N]` markers, using abstract for story opening and table descriptions for placement
6. **`art_director.py`** — LLM rewrites PaperBanana diagram specs into pixel-perfect art-direction format (hex codes, px dimensions, zone-by-zone layout). Controlled by `ART_DIRECT` env var.
7. **`diagram_gen.py`** — PaperBanana agentic pipeline renders diagrams to PNG. Uses `asyncio.run()` per diagram. Failures don't crash pipeline.
8. **`notebook_gen.py`** — Imports `run_pipeline` from `vendor/paper-to-notebook/backend/app.py` to generate notebooks locally. Falls back to hosted link on failure.
9. **`notebook_code_extractor.py`** — Extracts code cells from the generated `.ipynb`, pairs them with section headings, filters boilerplate. Returns `[{"title": ..., "code": ...}]`.
10. **`orchestrator.py`** → `refine_summary_with_code()` — LLM pass that inserts 1-2 pseudo-code snippets into the summary (preserves `[DIAGRAM:]` and `[TABLE:]` markers). Controlled by `ORCHESTRATOR_ITERATIONS` env var.
11. **`orchestrator.py`** → `build_final_html()` — Replaces markers with images, tables, renders Markdown to HTML with KaTeX.

### Digest Style

The summary is a **narrative technical blog post** (Substack-style). See `.claude/skills/digest-style/SKILL.md` for the full style guide. Key sections: The Big Picture → The Core Idea → How It Works → Results & Insights → Limitations & Future → Key Takeaways.

**Critical requirements:**
- All important equations from the paper MUST be preserved in LaTeX (`$...$` inline, `$$...$$` display)
- Concise, no filler — every sentence teaches something
- Diagrams placed inline right after the concept they illustrate
- AI-generated diagrams with art-directed specs for precision
- 1-2 key tables rendered in Results & Insights via `[TABLE: N]` markers
- At most 2 pseudo-code snippets (8-10 lines), not verbatim notebook code

### Orchestrator HTML Rendering (`orchestrator.py`)

The `_render_body()` function converts Markdown to HTML with special handling for:
- **`$$...$$` display math** — accumulated into `<div class="math-block">$$...$$</div>`
- **Inline `$...$` math** — protected from bold/italic/code formatting via placeholder system (`_protect_latex` / `_restore_latex`)
- **`[DIAGRAM: ...]` markers** — replaced with base64 `<figure>` tags
- **`[TABLE: N]` markers** — replaced with styled HTML tables from the paper's most important tables
- **`###`/`####` sub-headers** — rendered as `<h3>`/`<h4>` with inline formatting
- **Code blocks, blockquotes, ordered/unordered lists** — standard Markdown rendering (lists accept leading whitespace for indented/nested items)
- **KaTeX auto-render** — runs on page load to render all `$` and `$$` delimiters

Title extraction (`extract_title`) only accepts `# heading` lines to avoid picking up arXiv metadata.

### Key Patterns

- **Session management:** In-memory dict in `main.py` (`_sessions`), keyed by short UUID. Not persistent across restarts.
- **Progress streaming:** SSE via `/status/{sid}` endpoint; frontend polls with EventSource.
- **Inline diagram placement:** Summary contains `[DIAGRAM: description]` markers; orchestrator replaces them with images in order.
- **Table placement:** Summary contains `[TABLE: N]` markers; orchestrator replaces them with styled HTML tables from selected paper tables.
- **Notebook CTA:** Three buttons when ipynb exists — Download .ipynb, Open in Colab (links to `colab.research.google.com/#create=true`), Open App.
- **Graceful degradation:** Every pipeline stage has fallback handling — art-direction failure keeps original diagram spec, diagram failure skips that diagram, notebook failure falls back to hosted link, code extraction/refinement failure uses original summary. Table LLM calls retry once on empty response; on total failure, tables fall back to the 2 largest by row count.
- **Light theme:** White background, blue accent, clean typography. No dark mode.

### API Routes (main.py)

| Route | Method | Purpose |
|-------|--------|---------|
| `/process` | POST | Upload PDF, start pipeline, return `session_id` |
| `/status/{sid}` | GET | SSE progress stream |
| `/result/{sid}` | GET | Final HTML digest |
| `/download/{sid}/{filename}` | GET | Download output files |
| `/session/{sid}/info` | GET | Session metadata |
| `/` | GET | Serve frontend |

### Output Structure

Each session writes to `outputs/{session_id}/` with: `paper.pdf`, `paper.md`, `summary.md`, `summary_refined.md` (if code integration ran), `diagrams/*.png`, `original_figures/*.png` (extracted from PDF), `paper_notebook.ipynb`, `digest.html`.

## AI Model Usage

**All LLM calls** go through `backend/llm_client.py`:
- **`llm_call()`** — single entry point, calls Gemini via `google-generativeai` SDK
- **`LLMResponse`** dataclass — `.text`, `.input_tokens`, `.output_tokens`
- Default model: `gemini-2.5-flash` (overridable via `LLM_MODEL` env var)

**PaperBanana** (diagram generation) — vendor clone at `vendor/paperbanana/`, uses `google-genai` SDK internally:
- Text agents (planner, stylist, critic): `gemini-2.0-flash`
- Image generation (visualizer): `gemini-3-pro-image-preview`
- Called via `asyncio.run()` from `diagram_gen.py` — each diagram gets a fresh event loop
- `diagram_gen.py` adds `vendor/paperbanana/` to `sys.path` and sets data/prompt paths to vendor dir

**paper-to-notebook** uses `google-genai` SDK with `gemini-2.5-pro` for notebook generation.

## Vendor Dependencies

- **paperbanana** — cloned to `vendor/paperbanana/` during setup from `https://github.com/llmsresearch/paperbanana`. Agentic pipeline: Retriever → Planner → Stylist → Visualizer → Critic. Data at `vendor/paperbanana/data/`, prompts at `vendor/paperbanana/prompts/`.
- **paper-to-notebook** — cloned to `vendor/paper-to-notebook/` during setup. Entry point: `backend/app.py` → `run_pipeline(pdf_bytes, api_key=...)` returns `.ipynb` bytes.

## Important Notes

- **No API calls from Claude Code** — never run code that makes external API calls. All testing is done by the user.
- **No dry-run mode** — removed. No Anthropic/Claude LLM support — Gemini only.
- **No usage tracking** — `usage_tracker.py` was deleted.
- Frontend UI should NOT expose which models are used — user sees generic labels like "Parse PDF", "Generate Summary", etc.
- **Figure extraction** uses PyMuPDF (`fitz`) — extracts original figures for archival only (saved to `original_figures/`). No toggle UI; diagrams are AI-generated with art-direction.
- **Table extraction** is regex-based from parsed markdown + one LLM call for selection. Retries once; fallback picks 2 largest tables by row count so tables always appear if any exist.
- **No image caps** — diagrams render at full resolution (WebP quality 90). No width resize.
- **Results section** encouraged to have 2 diagrams (main comparison + ablation chart) for visual richness.
