"""
main.py
-------
FastAPI application.

Routes:
  POST /process         — Upload PDF, kick off pipeline, return session_id
  GET  /status/{sid}    — SSE progress stream
  GET  /result/{sid}    — Final HTML digest
  GET  /download/{sid}/{filename} — Download output file
  GET  /session/{sid}/info — Session metadata
  GET  /                — Serve frontend
"""

import os
import json
import shutil
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Generator

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import (
    HTMLResponse, FileResponse, StreamingResponse, JSONResponse
)
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
OUTPUTS_DIR = BASE_DIR / "outputs"
FRONTEND_DIR = BASE_DIR / "frontend"
OUTPUTS_DIR.mkdir(exist_ok=True)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="PaperDigest API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory session store ───────────────────────────────────────────────────
_sessions: dict[str, dict] = {}


def _emit(sid: str, step: str, message: str):
    _sessions[sid]["progress"].append({"step": step, "message": message})
    print(f"[{sid}] [{step}] {message}")


# ── Pipeline runner (background thread) ───────────────────────────────────────

def _generate_notebook_task(pdf_path: str, session_dir: str) -> dict:
    """Run notebook generation in a background thread.
    SSE events are emitted on the main thread (after future.result()) to keep
    the progress stream strictly sequential and avoid frontend node twitching.
    """
    from notebook_gen import generate_notebook
    return generate_notebook(pdf_path, session_dir)


def _run_pipeline(sid: str, pdf_path: str):
    session = _sessions[sid]
    session_dir = OUTPUTS_DIR / sid
    session_dir.mkdir(exist_ok=True)
    pipeline_t0 = time.time()

    try:
        # Step 1: Parse PDF
        _emit(sid, "ocr", "Extracting text from paper...")
        t0 = time.time()
        from pdf_parser import parse_pdf_to_markdown
        paper_markdown = parse_pdf_to_markdown(pdf_path)
        (session_dir / "paper.md").write_text(paper_markdown, encoding="utf-8")
        elapsed = time.time() - t0
        _emit(sid, "ocr", f"Extracted {len(paper_markdown):,} characters ({elapsed:.1f}s)")

        # ── Fork: notebook runs in parallel with Profile→Summary→Banana→Diagrams ──
        # Notebook only needs the PDF path, not the summary or diagrams.
        notebook_executor = ThreadPoolExecutor(max_workers=1)
        notebook_future = notebook_executor.submit(
            _generate_notebook_task, pdf_path, str(session_dir)
        )

        # Step 1b: Extract original figures from PDF (CPU-only, fast)
        _emit(sid, "figures", "Extracting original figures from PDF...")
        t0 = time.time()
        from figure_extractor import extract_figures, save_figures
        original_figures = extract_figures(pdf_path)
        if original_figures:
            save_figures(original_figures, str(session_dir))
        elapsed = time.time() - t0
        _emit(sid, "figures", f"Extracted {len(original_figures)} figure(s) ({elapsed:.1f}s)")
        session["original_figures"] = original_figures

        # Step 2: Profile paper (one fast LLM call to steer the summarizer)
        _emit(sid, "profile", "Profiling paper...")
        t0 = time.time()
        from paper_profiler import profile_paper
        profile = profile_paper(paper_markdown)
        elapsed = time.time() - t0
        _emit(sid, "profile", f"Profile: {profile['paper_type']}, math={profile['math_density']}, diagrams={profile['num_diagrams']} ({elapsed:.1f}s)")

        # Step 2b: Title + metadata — extract from parsed markdown
        from orchestrator import build_final_html, extract_title, extract_paper_metadata
        title = extract_title(paper_markdown)
        session["title"] = title
        _emit(sid, "title", f"Title: {title}")

        # Extract author/year/URL via regex (primary), profiler LLM (fallback)
        meta = extract_paper_metadata(paper_markdown)
        session["authors"] = meta["authors"] or profile.get("authors", [])
        session["year"] = meta["year"] or profile.get("year", "")
        session["paper_url"] = meta["paper_url"] or profile.get("paper_url", "")

        # Fetch citation count from Semantic Scholar (non-blocking, best-effort)
        from citation_count import fetch_citation_count
        citation_count = fetch_citation_count(
            paper_url=session["paper_url"],
            title=title,
        )
        session["citation_count"] = citation_count
        if citation_count is not None:
            _emit(sid, "citations", f"Citations: {citation_count:,}")
        else:
            _emit(sid, "citations", "Citation count not available")

        # Step 2c: Extract abstract (regex, instant)
        from pdf_parser import extract_abstract
        abstract = extract_abstract(paper_markdown)
        if abstract:
            _emit(sid, "profile", f"Abstract extracted ({len(abstract)} chars)")

        # Step 2d: Extract + select important tables
        _emit(sid, "tables", "Selecting key tables...")
        t0 = time.time()
        from table_extractor import extract_tables, select_important_tables
        all_tables = extract_tables(paper_markdown)
        important_tables = select_important_tables(all_tables) if all_tables else []
        elapsed = time.time() - t0
        session["important_tables"] = important_tables
        if important_tables:
            _emit(sid, "tables", f"Selected {len(important_tables)} key table(s) ({elapsed:.1f}s)")
        else:
            _emit(sid, "tables", f"No important tables found ({elapsed:.1f}s)")

        # Build table descriptions for the summarizer prompt
        table_descriptions = ""
        if important_tables:
            parts = []
            for i, t in enumerate(important_tables, 1):
                cap = t.get("caption", t.get("context", f"Table {i}"))
                parts.append(f"[TABLE: {i}] — {cap}")
            table_descriptions = "\n".join(parts)

        # Step 3: Summary + diagram descriptions (profile-aware)
        _emit(sid, "summarize", "Generating summary...")
        t0 = time.time()
        from summarizer import generate_summary, generate_banana_texts
        summary = generate_summary(paper_markdown, profile=profile, abstract=abstract, table_descriptions=table_descriptions)
        (session_dir / "summary.md").write_text(summary, encoding="utf-8")
        elapsed = time.time() - t0
        _emit(sid, "summarize", f"Summary complete ({elapsed:.1f}s)")

        t0 = time.time()
        banana_blocks = generate_banana_texts(paper_markdown, summary)
        elapsed = time.time() - t0
        _emit(sid, "banana_plan", f"{len(banana_blocks)} diagram(s) planned ({elapsed:.1f}s)")

        # Step 3c: Art-direct diagram specs
        art_direct_iters = int(os.getenv("ART_DIRECT", "1"))
        if art_direct_iters > 0:
            _emit(sid, "art_direct", "Art-directing diagram specs...")
            t0 = time.time()
            from art_director import art_direct_specs
            banana_blocks = art_direct_specs(banana_blocks, iterations=art_direct_iters)
            elapsed = time.time() - t0
            _emit(sid, "art_direct", f"Art-directed {len(banana_blocks)} diagram(s) ({elapsed:.1f}s)")

        # Step 4: Diagrams (run concurrently via asyncio.gather inside diagram_gen)
        from diagram_gen import generate_diagrams
        diagram_dir = session_dir / "diagrams"
        diagram_captions = [b.get("caption", f"Diagram {i+1}") for i, b in enumerate(banana_blocks)]
        session["diagram_captions"] = diagram_captions

        _emit(sid, "diagrams", f"Generating {len(banana_blocks)} diagram(s)...")
        t0 = time.time()
        diagram_paths = generate_diagrams(banana_blocks, str(diagram_dir))
        elapsed = time.time() - t0
        _emit(sid, "diagrams", f"{len(diagram_paths)} of {len(banana_blocks)} diagram(s) done ({elapsed:.1f}s)")

        # Step 4b: Generate table charts (matplotlib charts from important tables)
        table_chart_paths = []
        if important_tables:
            _emit(sid, "table_charts", f"Generating chart(s) for {len(important_tables)} table(s)...")
            t0 = time.time()
            from diagram_gen import generate_table_charts
            table_chart_paths = generate_table_charts(important_tables, str(diagram_dir))
            elapsed = time.time() - t0
            ok = sum(1 for p in table_chart_paths if p)
            _emit(sid, "table_charts", f"{ok}/{len(important_tables)} table chart(s) generated ({elapsed:.1f}s)")
        session["table_chart_paths"] = table_chart_paths

        # ── Collect notebook result (blocks if not done yet — likely finished earlier) ──
        _emit(sid, "notebook", "Generating notebook...")
        notebook_result = notebook_future.result()
        notebook_executor.shutdown(wait=False)
        strategy = notebook_result.get("strategy", "link")
        if strategy == "local":
            _emit(sid, "notebook", "Notebook generated locally")
        elif strategy == "api":
            _emit(sid, "notebook", "Notebook downloaded from API")
        else:
            _emit(sid, "notebook", "Using hosted notebook link")

        # Step 6: Extract code from notebook + refine summary
        from orchestrator import refine_summary_with_code
        from notebook_code_extractor import extract_code_snippets, extract_notebook_title

        code_snippets = []
        nb_path = notebook_result.get("ipynb_path")
        if nb_path and os.path.exists(nb_path):
            # Notebook title is a fallback only — the PDF-parsed title
            # (from extract_title) is the source of truth because the
            # notebook generator sometimes hallucinate a different title.
            if title == "Research Paper":
                nb_title = extract_notebook_title(nb_path)
                if nb_title:
                    title = nb_title
                    session["title"] = title
                    _emit(sid, "title", f"Title: {title}")

            try:
                t0 = time.time()
                code_snippets = extract_code_snippets(nb_path)
                elapsed = time.time() - t0
                _emit(sid, "code_extract", f"Extracted {len(code_snippets)} code snippet(s) from notebook ({elapsed:.1f}s)")
            except Exception as exc:
                _emit(sid, "code_extract", f"Code extraction skipped: {exc}")

        refinement_iters = int(os.getenv("ORCHESTRATOR_ITERATIONS", "5"))
        if code_snippets and refinement_iters > 0:
            _emit(sid, "refine", "Integrating code snippets into summary...")
            t0 = time.time()
            refined_summary = refine_summary_with_code(summary, code_snippets, refinement_iters)
            elapsed = time.time() - t0

            # Layer 3: Post-refinement safety net — revert if refinement lost
            # critical structural elements compared to the original summary
            import re as _re
            orig_headings = len(_re.findall(r"^## ", summary, _re.MULTILINE))
            ref_headings = len(_re.findall(r"^## ", refined_summary, _re.MULTILINE))
            orig_diagrams = len(_re.findall(r"\[DIAGRAM:\s*.+?\]", summary))
            ref_diagrams = len(_re.findall(r"\[DIAGRAM:\s*.+?\]", refined_summary))
            orig_tables = len(_re.findall(r"\[TABLE:\s*\d+\]", summary))
            ref_tables = len(_re.findall(r"\[TABLE:\s*\d+\]", refined_summary))

            if ref_headings < orig_headings or ref_diagrams < orig_diagrams or ref_tables < orig_tables:
                reason = []
                if ref_headings < orig_headings:
                    reason.append(f"headings {ref_headings}<{orig_headings}")
                if ref_diagrams < orig_diagrams:
                    reason.append(f"diagrams {ref_diagrams}<{orig_diagrams}")
                if ref_tables < orig_tables:
                    reason.append(f"tables {ref_tables}<{orig_tables}")
                _emit(sid, "refine", f"Refinement reverted: lost {', '.join(reason)} ({elapsed:.1f}s)")
                refined_summary = summary
            else:
                _emit(sid, "refine", f"Summary refined with code snippets ({elapsed:.1f}s)")

            (session_dir / "summary_refined.md").write_text(refined_summary, encoding="utf-8")
        else:
            refined_summary = summary

        # Step 6b: QC validation — fix invalid markers before rendering
        from orchestrator import validate_final_summary
        num_tables = len(session.get("important_tables", []))
        refined_summary, qc_warnings = validate_final_summary(refined_summary, num_tables)
        if qc_warnings:
            _emit(sid, "qc", f"QC fixed {len(qc_warnings)} issue(s): {'; '.join(qc_warnings)}")

        # Step 7: Final HTML
        _emit(sid, "orchestrate", "Building final digest...")
        t0 = time.time()
        html = build_final_html(
            summary=refined_summary,
            diagram_paths=diagram_paths,
            diagram_captions=diagram_captions,
            notebook_result=notebook_result,
            paper_title=title,
            authors=session.get("authors", []),
            year=session.get("year", ""),
            paper_url=session.get("paper_url", ""),
            citation_count=session.get("citation_count"),
            important_tables=session.get("important_tables"),
            table_chart_paths=session.get("table_chart_paths"),
        )
        html = html.replace("{SESSION_ID}", sid)

        html_path = session_dir / "digest.html"
        html_path.write_text(html, encoding="utf-8")
        elapsed = time.time() - t0
        _emit(sid, "orchestrate", f"Digest ready ({elapsed:.1f}s)")

        # Done
        total_elapsed = time.time() - pipeline_t0
        session["status"] = "done"
        session["result_path"] = str(html_path)
        session["notebook_result"] = notebook_result
        _emit(sid, "done", f"Your PaperDigest is ready! (total: {total_elapsed:.1f}s)")

    except Exception as exc:
        import traceback
        session["status"] = "error"
        session["error"] = str(exc)
        _emit(sid, "error", f"Pipeline failed: {exc}")
        traceback.print_exc()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/process")
async def process_paper(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    sid = str(uuid.uuid4())[:10]
    session_dir = OUTPUTS_DIR / sid
    session_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = str(session_dir / "paper.pdf")
    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    _sessions[sid] = {
        "status": "running",
        "progress": [],
        "result_path": None,
        "error": None,
        "title": "Research Paper",
        "notebook_result": {},
        "original_figures": [],
        "important_tables": [],
    }

    t = threading.Thread(target=_run_pipeline, args=(sid, pdf_path), daemon=True)
    t.start()

    return JSONResponse({"session_id": sid})


@app.get("/status/{sid}")
async def get_status(sid: str):
    if sid not in _sessions:
        raise HTTPException(404, "Session not found")

    def event_stream() -> Generator[str, None, None]:
        sent = 0
        while True:
            session = _sessions.get(sid, {})
            progress = session.get("progress", [])

            while sent < len(progress):
                event = progress[sent]
                yield f"data: {json.dumps(event)}\n\n"
                sent += 1

            status = session.get("status", "running")
            if status in ("done", "error"):
                yield f"data: {json.dumps({'step': status, 'message': status})}\n\n"
                break

            import time
            time.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/result/{sid}")
async def get_result(sid: str):
    session = _sessions.get(sid)
    if not session:
        raise HTTPException(404, "Session not found")
    if session["status"] != "done":
        raise HTTPException(409, f"Not ready yet: {session['status']}")

    html_path = session.get("result_path")
    if not html_path or not Path(html_path).exists():
        raise HTTPException(500, "Result file missing")

    return HTMLResponse(Path(html_path).read_text(encoding="utf-8"))


@app.get("/markdown/{sid}")
async def get_markdown(sid: str):
    """Serve the refined (or original) summary Markdown for export.

    Replaces [DIAGRAM: ...] markers with base64-embedded markdown images
    so the downloaded .md is self-contained with diagrams.
    """
    session = _sessions.get(sid)
    if not session:
        raise HTTPException(404, "Session not found")
    if session["status"] != "done":
        raise HTTPException(409, f"Not ready yet: {session['status']}")

    session_dir = OUTPUTS_DIR / sid
    # Prefer refined summary; fall back to original
    md_path = session_dir / "summary_refined.md"
    if not md_path.exists():
        md_path = session_dir / "summary.md"
    if not md_path.exists():
        raise HTTPException(404, "Markdown file not found")

    import re

    md_text = md_path.read_text(encoding="utf-8")

    # Collect diagram PNGs in order
    diagram_dir = session_dir / "diagrams"
    if diagram_dir.exists():
        diagram_files = sorted(diagram_dir.glob("*.png"))
    else:
        diagram_files = []

    # Replace [DIAGRAM: ...] markers with inline compressed WebP images
    from orchestrator import _compress_img_to_b64
    img_index = 0

    def _replace_marker(m):
        nonlocal img_index
        caption = m.group(1).strip()
        if img_index < len(diagram_files):
            b64 = _compress_img_to_b64(str(diagram_files[img_index]))
            img_index += 1
            return f"![{caption}](data:image/webp;base64,{b64})"
        img_index += 1
        return ""  # no image available, remove marker

    md_text = re.sub(r"\[DIAGRAM:\s*(.+?)\]", _replace_marker, md_text)

    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        md_text,
        media_type="text/markdown",
    )


@app.get("/substack-html/{sid}")
async def get_substack_html(sid: str):
    """Serve clean semantic HTML optimized for pasting into Substack's editor.

    No CSS, no JS, no KaTeX — just headings, paragraphs, figures, code blocks.
    Math left as raw $/$$ delimiters (Substack renders LaTeX natively).
    Images embedded as base64 (Substack auto-hosts them on publish).
    """
    session = _sessions.get(sid)
    if not session:
        raise HTTPException(404, "Session not found")
    if session["status"] != "done":
        raise HTTPException(409, f"Not ready yet: {session['status']}")

    session_dir = OUTPUTS_DIR / sid

    # Read summary markdown
    md_path = session_dir / "summary_refined.md"
    if not md_path.exists():
        md_path = session_dir / "summary.md"
    if not md_path.exists():
        raise HTTPException(404, "Markdown file not found")

    md_text = md_path.read_text(encoding="utf-8")

    # Collect diagram PNGs in order
    diagram_dir = session_dir / "diagrams"
    if diagram_dir.exists():
        diagram_files = sorted(diagram_dir.glob("*.png"))
    else:
        diagram_files = []

    diagram_paths = [str(p) for p in diagram_files]
    diagram_captions = session.get(
        "diagram_captions",
        [f"Diagram {i+1}" for i in range(len(diagram_files))],
    )

    title = session.get("title", "Research Paper")

    from orchestrator import build_substack_html
    html = build_substack_html(
        summary=md_text,
        diagram_paths=diagram_paths,
        diagram_captions=diagram_captions,
        paper_title=title,
        important_tables=session.get("important_tables"),
    )

    return HTMLResponse(html, media_type="text/html")


@app.get("/substack-text/{sid}")
async def get_substack_text(sid: str):
    """Serve text-focused HTML for Substack paste (no images at all).

    Math as Unicode, diagrams as placeholder text, tables as plain HTML.
    This format actually survives Substack's editor paste.
    """
    session = _sessions.get(sid)
    if not session:
        raise HTTPException(404, "Session not found")
    if session["status"] != "done":
        raise HTTPException(409, f"Not ready yet: {session['status']}")

    session_dir = OUTPUTS_DIR / sid

    md_path = session_dir / "summary_refined.md"
    if not md_path.exists():
        md_path = session_dir / "summary.md"
    if not md_path.exists():
        raise HTTPException(404, "Markdown file not found")

    md_text = md_path.read_text(encoding="utf-8")
    title = session.get("title", "Research Paper")

    from orchestrator import build_substack_text_html
    html = build_substack_text_html(
        summary=md_text,
        paper_title=title,
        important_tables=session.get("important_tables"),
    )

    return HTMLResponse(html, media_type="text/html")


@app.get("/download/{sid}/{filename}")
async def download_file(sid: str, filename: str):
    safe_name = Path(filename).name
    file_path = OUTPUTS_DIR / sid / safe_name
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(str(file_path), filename=safe_name)


@app.get("/view-notebook/{sid}")
async def view_notebook(sid: str):
    """Render the generated .ipynb as a viewable HTML page."""
    session = _sessions.get(sid)
    if not session:
        raise HTTPException(404, "Session not found")

    nb_path = None
    nb_result = session.get("notebook_result", {})
    if nb_result.get("ipynb_path"):
        nb_path = Path(nb_result["ipynb_path"])
    if not nb_path or not nb_path.exists():
        # Fallback: look for the file directly
        nb_path = OUTPUTS_DIR / sid / "paper_notebook.ipynb"
    if not nb_path.exists():
        raise HTTPException(404, "Notebook not found")

    from notebook_viewer import render_notebook_html
    title = session.get("title", "Paper Notebook")
    html = render_notebook_html(str(nb_path), title)
    return HTMLResponse(html)


@app.get("/session/{sid}/info")
async def session_info(sid: str):
    session = _sessions.get(sid)
    if not session:
        raise HTTPException(404, "Session not found")
    info = {
        "status": session["status"],
        "title": session.get("title", ""),
        "error": session.get("error"),
        "notebook": session.get("notebook_result", {}),
    }
    if session.get("citation_count") is not None:
        info["citation_count"] = session["citation_count"]
    return info


# ── Serve frontend ────────────────────────────────────────────────────────────
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")