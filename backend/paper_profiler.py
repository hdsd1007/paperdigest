"""
paper_profiler.py
-----------------
Classifies a parsed paper and produces a profile dict that steers
the summarizer (section emphasis, diagram count, math expectations).

One LLM call (max_tokens=512, temperature=0.0) — fast and deterministic.
On ANY failure, returns DEFAULT_PROFILE so the pipeline never blocks.
"""

import json
from llm_client import llm_call

# ── Defaults (match current behaviour when profiler is unavailable) ──────────

DEFAULT_PROFILE: dict = {
    "paper_type": "empirical",
    "math_density": "medium",
    "has_benchmarks": True,
    "key_metrics": [],
    "num_diagrams": 4,
    "num_components": 2,
    "needs_prerequisite": False,
    "emphasis": "",
    "authors": [],
    "year": "",
    "paper_url": "",
}

_VALID_PAPER_TYPES = {"empirical", "theoretical", "systems", "survey"}
_VALID_MATH_DENSITIES = {"low", "medium", "high"}

# ── Prompt ───────────────────────────────────────────────────────────────────

PROFILE_PROMPT = """You are an academic paper classifier. Given the beginning of a research paper, return a JSON object with these exact keys:

- "paper_type": one of "empirical", "theoretical", "systems", "survey"
- "math_density": one of "low", "medium", "high"
- "has_benchmarks": true if the paper reports quantitative benchmark results, else false
- "key_metrics": array of up to 4 strings like "accuracy: 92.3%" (empty array if none)
- "num_components": integer 1-5, how many distinct modules/components the method has
- "needs_prerequisite": true if the paper assumes complex background knowledge (e.g. autoencoders, attention, RL, diffusion) that a general ML reader might not have
- "num_diagrams": integer 4-6, how many diagrams would best illustrate this paper.
  Guidance: start at 4 (minimum), +1 if the method has a complex multi-stage pipeline, +1 for systems papers. Range 4-6.
- "authors": array of author name strings (first name + last name), e.g. ["Alice Smith", "Bob Jones"]. Extract from the paper header. If more than 5 authors, include the first 5 only.
- "year": 4-digit publication year as a string, e.g. "2024". Extract from the paper header, arxiv ID, or copyright notice. Empty string if unknown.
- "paper_url": the paper's URL if visible in the text (e.g. arxiv.org link). Empty string if not found.
- "emphasis": one sentence telling a summarizer what to focus on

Return ONLY the raw JSON object. No markdown fences, no preamble.

Paper text (first 15 000 chars):
{paper_text}"""


# ── Public API ───────────────────────────────────────────────────────────────

def profile_paper(paper_markdown: str) -> dict:
    """Classify the paper and return a steering profile for the summarizer.

    Guaranteed to return a valid profile dict — falls back to DEFAULT_PROFILE
    on any error (LLM failure, bad JSON, missing keys).
    """
    try:
        text_slice = paper_markdown[:15_000]
        resp = llm_call(
            prompt=PROFILE_PROMPT.format(paper_text=text_slice),
            max_tokens=768,
            temperature=0.0,
        )
        raw = resp.text.strip()

        # Strip accidental markdown fences
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        profile = json.loads(raw)
        return _validate_profile(profile)

    except Exception:
        return dict(DEFAULT_PROFILE)


# ── Validation ───────────────────────────────────────────────────────────────

def _validate_profile(profile: dict) -> dict:
    """Clamp / fix every field, falling back to defaults for bad values."""
    out = dict(DEFAULT_PROFILE)  # start from defaults

    pt = profile.get("paper_type", "")
    if pt in _VALID_PAPER_TYPES:
        out["paper_type"] = pt

    md = profile.get("math_density", "")
    if md in _VALID_MATH_DENSITIES:
        out["math_density"] = md

    out["has_benchmarks"] = bool(profile.get("has_benchmarks", True))

    km = profile.get("key_metrics")
    if isinstance(km, list):
        out["key_metrics"] = [str(m) for m in km[:4]]

    nd = profile.get("num_diagrams", 3)
    try:
        nd = int(nd)
    except (TypeError, ValueError):
        nd = 3
    out["num_diagrams"] = max(4, min(6, nd))

    nc = profile.get("num_components", 2)
    try:
        nc = int(nc)
    except (TypeError, ValueError):
        nc = 2
    out["num_components"] = max(1, min(5, nc))

    out["needs_prerequisite"] = bool(profile.get("needs_prerequisite", False))

    emphasis = profile.get("emphasis", "")
    if isinstance(emphasis, str):
        out["emphasis"] = emphasis

    authors = profile.get("authors", [])
    if isinstance(authors, list):
        out["authors"] = [str(a) for a in authors[:5]]

    year = profile.get("year", "")
    if isinstance(year, (str, int)):
        out["year"] = str(year).strip()

    paper_url = profile.get("paper_url", "")
    if isinstance(paper_url, str):
        out["paper_url"] = paper_url.strip()

    return out


def build_profile_notes(profile: dict) -> str:
    """Convert a profile dict into a short natural-language block
    that gets injected into the summarizer prompt."""
    if not profile or profile == DEFAULT_PROFILE:
        return ""

    parts = []
    parts.append(f"This is a {profile['paper_type']} paper with {profile['math_density']} math density.")

    if profile.get("has_benchmarks"):
        parts.append("It has benchmark results — highlight quantitative gains.")
    else:
        parts.append("No standard benchmarks — focus on qualitative contributions.")

    if profile.get("key_metrics"):
        parts.append("Key metrics: " + ", ".join(profile["key_metrics"]) + ".")

    nc = profile.get("num_components", 2)
    if nc >= 3:
        parts.append(f"Multi-component method ({nc} modules) — consider extra mechanism diagrams.")

    if profile.get("needs_prerequisite"):
        parts.append("Paper assumes complex prerequisite knowledge — consider a prerequisite explainer diagram (Arc 2 slot).")

    if profile.get("emphasis"):
        parts.append(profile["emphasis"])

    parts.append(f"Target {profile['num_diagrams']} diagrams.")

    return "PAPER PROFILE: " + " ".join(parts)
