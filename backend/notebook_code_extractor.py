"""
notebook_code_extractor.py
--------------------------
Extract code cells from a generated .ipynb notebook, paired with their
section headings. Used to integrate key implementation snippets into the
digest article.
"""

import json
import re


def _is_boilerplate(code: str) -> bool:
    """Return True if a code cell is boilerplate (imports-only, plotting, training loops, infrastructure)."""
    lines = [l.strip() for l in code.strip().splitlines() if l.strip() and not l.strip().startswith("#")]
    if not lines:
        return True

    # Pure import blocks
    if all(l.startswith(("import ", "from ", "!pip", "%")) for l in lines):
        return True

    # Plotting-only cells
    plot_keywords = {"plt.show", "plt.figure", "plt.plot", "plt.savefig", "plt.xlabel", "plt.ylabel"}
    if any(kw in code for kw in plot_keywords) and "def " not in code and "class " not in code:
        return True

    # Training loop cells (optimizer.step / loss.backward without class/function defs)
    if ("optimizer.step" in code or "loss.backward" in code) and "def " not in code and "class " not in code:
        return True

    # Infrastructure classes (not paper-specific algorithms)
    infra_keywords = [
        "Tokenizer", "PositionalEncoding", "Embedding(",
        "RolloutBuffer", "ReplayBuffer", "DataLoader",
    ]
    if any(kw in code for kw in infra_keywords):
        # Keep only if it contains a loss function or core algorithm
        if "loss" not in code.lower() and "reward" not in code.lower():
            return True

    # Generic model architecture (transformer layers, not paper algo)
    if re.search(r"class\s+\w*(Transformer|GPT|BERT|Model)\b", code):
        if "loss" not in code.lower() and "compute_loss" not in code:
            return True

    # Training orchestration / experiment loops
    if ("for step in" in code or "tqdm" in code or "progress_bar" in code):
        if "compute_loss" not in code:
            return True

    # Data generation utilities
    if re.search(r"def\s+generate_\w*data", code):
        return True

    return False


def _extract_heading(cell_source: str) -> str | None:
    """Extract a section heading from a markdown cell (e.g. '### 2.1 Title')."""
    for line in cell_source.strip().splitlines():
        m = re.match(r"^#{1,4}\s+(?:\d+[\.\d]*\s+)?(.+)", line.strip())
        if m:
            return m.group(1).strip()
    return None


def extract_notebook_title(ipynb_path: str) -> str | None:
    """Extract the paper title from the notebook's first markdown cell.

    paper-to-notebook puts the title as a ``# heading`` in the first cell.
    Returns None if no title is found.
    """
    with open(ipynb_path, "r", encoding="utf-8") as f:
        nb = json.load(f)

    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "markdown":
            continue
        source = "".join(cell.get("source", []))
        for line in source.strip().splitlines():
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("##"):
                return stripped[2:].strip()
        break  # only check the first markdown cell

    return None


def extract_code_snippets(ipynb_path: str) -> list[dict]:
    """
    Walk an .ipynb file and pair markdown heading cells with subsequent code cells.

    Returns:
        [{"title": "Scaled Dot-Product Attention", "code": "def scaled_dot_product..."}]
    """
    with open(ipynb_path, "r", encoding="utf-8") as f:
        nb = json.load(f)

    cells = nb.get("cells", [])
    snippets = []
    current_heading = None

    for cell in cells:
        cell_type = cell.get("cell_type", "")
        source = "".join(cell.get("source", []))

        if cell_type == "markdown":
            heading = _extract_heading(source)
            if heading:
                current_heading = heading

        elif cell_type == "code" and current_heading:
            code = source.strip()
            if code and not _is_boilerplate(code):
                snippets.append({
                    "title": current_heading,
                    "code": code,
                })
            # Reset heading — each heading pairs with one code cell
            current_heading = None

    return snippets
