"""
diagram_gen.py
--------------
Generates diagrams using PaperBanana (vendor clone).
Takes a list of {"filename", "caption", "text"} dicts, returns PNG file paths.
"""

import asyncio
import os
import pathlib
import re as _re
import shutil
import subprocess
import sys
import tempfile
from dotenv import load_dotenv

from llm_client import llm_call

load_dotenv()

ITERATIONS = int(os.getenv("PAPERBANANA_ITERATIONS", "3"))

# ── Vendor paths ─────────────────────────────────────────────────────────────
VENDOR_DIR = pathlib.Path(__file__).parent.parent / "vendor" / "paperbanana"
_VENDOR_DATA = VENDOR_DIR / "data"
_VENDOR_PROMPTS = VENDOR_DIR / "prompts"

# Add vendor root to sys.path at import time (thread-safe)
_vendor_str = str(VENDOR_DIR)
if _vendor_str not in sys.path:
    sys.path.insert(0, _vendor_str)

# Max concurrent diagram generations to avoid Gemini API rate limits
_MAX_CONCURRENT = 3

# ── Direct chart generation (bypass PaperBanana for Arc 4) ────────────────────

_CHART_PROMPT = """\
You are a matplotlib expert. Given a diagram description from a research paper,
produce a **single** Python script that generates a clean bar/line chart.

RULES:
1. Extract the EXACT numerical values from the description. Never invent data.
2. Use matplotlib only (no seaborn, plotly, etc.).
3. Save the figure to the path in the variable OUTPUT_PATH (already defined).
4. Use `plt.savefig(OUTPUT_PATH, dpi=150, bbox_inches="tight")` — no `plt.show()`.
5. Use a clean style: white background, legible fonts (size 11+), gridlines on y-axis.
6. Add data-value labels on top of each bar (or beside each point for line charts).
7. If multiple groups/methods, use grouped bars with a legend.
8. Do NOT use `fontfamily` in `tick_params()`. Set font family globally via `plt.rcParams['font.family'] = 'sans-serif'` at the top if needed.
9. Output ONLY the Python code. No explanation, no markdown fences.

DESCRIPTION:
{description}

CAPTION:
{caption}
"""


def _parse_markdown_table(md: str) -> tuple[list[str], list[list[str]]]:
    """Parse a markdown pipe-table into (headers, rows).

    Returns (headers, rows) where headers is a list of column names and
    rows is a list of lists of cell strings.
    """
    lines = [
        ln.strip() for ln in md.splitlines()
        if ln.strip().startswith("|")
    ]
    # Drop separator rows like |---|---|
    lines = [ln for ln in lines if not _re.match(r"^\|[\s\-:|]+\|$", ln)]
    if not lines:
        return [], []

    def _split_row(line: str) -> list[str]:
        # Remove leading/trailing pipes then split on inner pipes
        return [cell.strip() for cell in line.strip("|").split("|")]

    headers = _split_row(lines[0])
    rows = [_split_row(ln) for ln in lines[1:]]
    return headers, rows


# ── Deterministic table chart helpers ────────────────────────────────────────

def _try_parse_float(s: str) -> float | None:
    """Parse cell string to float, handling research paper quirks.

    Handles footnote markers (77.3*), parenthetical ranges (±0.1),
    percentage signs, thousands commas (1,600), dashes as None.
    """
    if not s or not s.strip():
        return None
    s = s.strip()
    # Dashes / em-dashes → None
    if s in ("-", "–", "—", "N/A", "n/a", ""):
        return None
    # Remove footnote markers, parenthetical ranges, percentage signs
    s = _re.sub(r"[*†‡§¶]", "", s)
    s = _re.sub(r"\(.*?\)", "", s)
    s = s.replace("%", "").replace(",", "")
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


_PARAM_KEYWORDS = {
    "epoch", "epochs", "param", "params", "parameters",
    "flops", "gflops", "tflops", "arch", "architecture",
    "backbone", "model", "method", "pre-train", "pretrain",
    "batch", "lr", "learning rate", "optimizer", "schedule",
    "layers", "heads", "dim", "hidden", "resolution", "res",
}


def _classify_columns(
    headers: list[str], rows: list[list[str]]
) -> tuple[int, list[int]]:
    """Determine label column and metric columns.

    Returns (label_col_index, list_of_metric_col_indices).
    Raises RuntimeError if no numeric columns found.
    """
    n_cols = len(headers)
    n_rows = max(len(rows), 1)

    # Count how many cells per column parse as numeric
    numeric_counts = []
    for col in range(n_cols):
        count = sum(
            1 for row in rows
            if col < len(row) and _try_parse_float(row[col]) is not None
        )
        numeric_counts.append(count)

    # Label column: first column with <50% numeric values (usually method names)
    label_col = 0
    for col in range(n_cols):
        if numeric_counts[col] / n_rows < 0.5:
            label_col = col
            break

    # Numeric columns (>= 50% parseable values, excluding label col)
    numeric_cols = [
        col for col in range(n_cols)
        if col != label_col and numeric_counts[col] / n_rows >= 0.5
    ]

    if not numeric_cols:
        raise RuntimeError("no numeric columns found in table")

    # Filter out parameter columns by keyword matching
    metric_cols = []
    for col in numeric_cols:
        header_lower = headers[col].lower().strip()
        is_param = any(kw in header_lower for kw in _PARAM_KEYWORDS)
        if not is_param:
            metric_cols.append(col)

    # Fall back to all numeric if keyword filtering removed everything
    if not metric_cols:
        metric_cols = numeric_cols

    return label_col, metric_cols


def _detect_groups(
    rows: list[list[str]], label_col: int, metric_cols: list[int]
) -> tuple[list[list[str]], list[tuple[str, list[int]]]]:
    """Detect sub-header rows and split data into groups.

    Sub-header rows (e.g. "Methods without view data augmentations") have
    all metric cells empty.  Returns (data_rows, groups) where groups is
    a list of (group_name, [row_indices_into_data_rows]).
    """
    data_rows: list[list[str]] = []
    groups: list[tuple[str, list[int]]] = []
    current_group: tuple[str, list[int]] = ("", [])

    for row in rows:
        # Sub-header: all metric cells are empty / unparseable
        metrics_empty = all(
            col >= len(row) or _try_parse_float(row[col]) is None
            for col in metric_cols
        )
        label = row[label_col] if label_col < len(row) else ""

        if metrics_empty and label.strip():
            # Save current group if it has rows
            if current_group[1]:
                groups.append(current_group)
            current_group = (label.strip(), [])
        else:
            idx = len(data_rows)
            data_rows.append(row)
            current_group[1].append(idx)

    # Save last group
    if current_group[1]:
        groups.append(current_group)

    # If no groups detected, make one default group
    if not groups:
        groups = [("", list(range(len(data_rows))))]

    return data_rows, groups


def _pick_best_metrics(
    metric_cols: list[int], data_rows: list[list[str]], max_metrics: int = 4
) -> list[int]:
    """If >max metrics, pick those with most non-None values, prefer rightmost."""
    if len(metric_cols) <= max_metrics:
        return metric_cols

    scored = []
    for col in metric_cols:
        n_valid = sum(
            1 for row in data_rows
            if col < len(row) and _try_parse_float(row[col]) is not None
        )
        # (count, col_index) — higher count first, then rightmost as tiebreak
        scored.append((n_valid, col))

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    chosen = [t[1] for t in scored[:max_metrics]]
    # Maintain original column order
    chosen.sort()
    return chosen


def _validate_output(dest_path: str) -> None:
    """Check file exists, non-empty, not all-white."""
    if not os.path.exists(dest_path):
        raise RuntimeError("chart generation produced no output file")
    if os.path.getsize(dest_path) == 0:
        os.unlink(dest_path)
        raise RuntimeError("chart generation produced an empty file")
    try:
        from PIL import Image
        img = Image.open(dest_path).convert("RGB")
        extrema = img.getextrema()
        if all(lo > 250 and hi > 250 for lo, hi in extrema):
            os.unlink(dest_path)
            raise RuntimeError("chart generation produced an all-white image")
    except ImportError:
        pass


# ── Color palette and assignment ─────────────────────────────────────────────

_PALETTE = [
    "#4C78A8", "#F58518", "#E45756", "#72B7B2",
    "#54A24B", "#EECA3B", "#B279A2", "#FF9DA6",
]

_GROUP_PALETTES = [
    ["#4C78A8", "#6A9ACF"],  # blue family
    ["#F58518", "#FFB347"],  # orange family
    ["#E45756", "#FF8A80"],  # red family
    ["#54A24B", "#81C784"],  # green family
    ["#72B7B2", "#A0D6D1"],  # teal family
    ["#B279A2", "#CE93D8"],  # purple family
]


def _assign_group_colors(
    n_labels: int, groups: list[tuple[str, list[int]]]
) -> list[str]:
    """Assign bar colors per row, varying by group for visual distinction."""
    colors = ["#4C78A8"] * n_labels
    for g_idx, (_, row_indices) in enumerate(groups):
        base = _GROUP_PALETTES[g_idx % len(_GROUP_PALETTES)][0]
        for ri in row_indices:
            if ri < n_labels:
                colors[ri] = base
    return colors


# ── Chart title ───────────────────────────────────────────────────────────────

def _build_chart_title(label_header: str, metric_names: list[str]) -> str:
    """Build a descriptive chart title from column names."""
    metrics_str = " / ".join(metric_names)
    if len(metrics_str) > 40:
        metrics_str = " / ".join(n[:15] for n in metric_names[:3])
    title = f"{metrics_str} by {label_header}" if label_header else metrics_str
    return title[:60]


# ── Chart rendering ──────────────────────────────────────────────────────────

def _draw_single_metric(
    labels: list[str], values: list[float], metric_name: str,
    groups: list[tuple[str, list[int]]], dest_path: str,
    title: str = "",
) -> None:
    """Horizontal bar chart for a single metric column, sorted by value."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Sort by value
    paired = list(zip(labels, values, range(len(labels))))
    paired.sort(key=lambda t: t[1])
    s_labels = [t[0] for t in paired]
    s_values = [t[1] for t in paired]
    orig_idx = [t[2] for t in paired]

    # Colors by group
    raw_colors = _assign_group_colors(len(labels), groups)
    s_colors = [raw_colors[i] for i in orig_idx]

    fig, ax = plt.subplots(figsize=(10, max(4, len(labels) * 0.45)))
    plt.rcParams["font.family"] = "sans-serif"

    bars = ax.barh(
        range(len(s_labels)), s_values, color=s_colors,
        edgecolor="white", height=0.7,
    )
    ax.set_yticks(range(len(s_labels)))
    ax.set_yticklabels(s_labels, fontsize=10)
    ax.set_xlabel(metric_name, fontsize=11)
    ax.xaxis.grid(True, linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Value labels
    max_val = max(s_values) if s_values else 1
    for bar, val in zip(bars, s_values):
        ax.text(
            bar.get_width() + max_val * 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"{val:.1f}", va="center", fontsize=9,
        )

    # Highlight best (rightmost bar = highest value)
    if bars:
        bars[-1].set_edgecolor("#333333")
        bars[-1].set_linewidth(1.5)

    # Group legend if multiple named groups
    named_groups = [(name, idxs) for name, idxs in groups if name]
    if len(named_groups) > 1:
        from matplotlib.patches import Patch
        legend_handles = []
        for g_idx, (name, _) in enumerate(named_groups):
            family = _GROUP_PALETTES[g_idx % len(_GROUP_PALETTES)]
            legend_handles.append(Patch(facecolor=family[0], label=name))
        ax.legend(handles=legend_handles, loc="lower right", fontsize=8, framealpha=0.8)

    if title:
        ax.set_title(title, fontsize=13, fontweight="bold", pad=12)

    plt.tight_layout()
    plt.savefig(dest_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _draw_grouped_metrics(
    labels: list[str], metric_names: list[str],
    metric_values: list[list[float]],
    groups: list[tuple[str, list[int]]], dest_path: str,
    title: str = "",
) -> None:
    """Grouped horizontal bar chart for 2-4 metric columns."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    n_labels = len(labels)
    n_metrics = len(metric_names)
    bar_height = 0.8 / n_metrics
    y_positions = np.arange(n_labels)

    fig, ax = plt.subplots(figsize=(10, max(4, n_labels * 0.55)))
    plt.rcParams["font.family"] = "sans-serif"

    for m_idx, (m_name, m_vals) in enumerate(zip(metric_names, metric_values)):
        offsets = y_positions + (m_idx - n_metrics / 2 + 0.5) * bar_height
        color = _PALETTE[m_idx % len(_PALETTE)]
        bars = ax.barh(
            offsets, m_vals, height=bar_height * 0.9,
            color=color, label=m_name, edgecolor="white",
        )
        # Value labels
        max_val = max(m_vals) if m_vals else 1
        for bar, val in zip(bars, m_vals):
            if val > 0:
                ax.text(
                    bar.get_width() + max_val * 0.01,
                    bar.get_y() + bar.get_height() / 2,
                    f"{val:.1f}", va="center", fontsize=7,
                )

    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels, fontsize=10)
    ax.xaxis.grid(True, linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(fontsize=9, loc="lower right", framealpha=0.8)

    # Group separators
    named_groups = [(name, idxs) for name, idxs in groups if name]
    if len(named_groups) > 1:
        for _name, idxs in named_groups:
            if idxs:
                y_top = max(idxs) + 0.5
                if y_top < n_labels - 0.5:
                    ax.axhline(y=y_top, color="#cccccc", linestyle="--", linewidth=0.8)

    if title:
        ax.set_title(title, fontsize=13, fontweight="bold", pad=12)

    plt.tight_layout()
    plt.savefig(dest_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _draw_chart(
    headers: list[str], data_rows: list[list[str]],
    label_col: int, metric_cols: list[int],
    groups: list[tuple[str, list[int]]], dest_path: str,
) -> str:
    """Dispatch to single or grouped chart renderer. Returns chart title."""
    # Extract labels (truncate long names)
    labels = []
    for row in data_rows:
        raw = row[label_col] if label_col < len(row) else "?"
        if len(raw) > 40:
            raw = raw[:37] + "..."
        labels.append(raw)

    # Extract metric values
    metric_names = [
        headers[c] if c < len(headers) else f"Metric {c}"
        for c in metric_cols
    ]
    metric_values: list[list[float]] = []
    for col in metric_cols:
        vals = []
        for row in data_rows:
            v = _try_parse_float(row[col]) if col < len(row) else None
            vals.append(v if v is not None else 0.0)
        metric_values.append(vals)

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    # Build a descriptive chart title from the column headers
    label_header = headers[label_col] if label_col < len(headers) else "Method"
    title = _build_chart_title(label_header, metric_names)

    if len(metric_cols) == 1:
        _draw_single_metric(labels, metric_values[0], metric_names[0],
                            groups, dest_path, title=title)
    else:
        _draw_grouped_metrics(labels, metric_names, metric_values,
                              groups, dest_path, title=title)

    return title


# ── Table chart entry point ──────────────────────────────────────────────────

def _generate_table_chart(table_markdown: str, caption: str, dest_path: str) -> tuple[str, str]:
    """Generate a matplotlib chart from a markdown table deterministically.

    No LLM, no subprocess, no temp files — pure Python with matplotlib.
    Returns (dest_path, chart_title).
    """
    headers, rows = _parse_markdown_table(table_markdown)
    if not headers:
        raise RuntimeError("could not parse any headers from the markdown table")

    label_col, metric_cols = _classify_columns(headers, rows)
    data_rows, groups = _detect_groups(rows, label_col, metric_cols)
    metric_cols = _pick_best_metrics(metric_cols, data_rows)

    if not data_rows:
        raise RuntimeError("no data rows after filtering sub-headers")

    title = _draw_chart(headers, data_rows, label_col, metric_cols, groups, dest_path)
    _validate_output(dest_path)
    return dest_path, title


def generate_table_charts(important_tables: list[dict], output_dir: str) -> list[str | None]:
    """Generate matplotlib charts for selected important tables.

    Returns a list the same length as important_tables — each element is a
    PNG path on success or None on failure.
    """
    os.makedirs(output_dir, exist_ok=True)
    results: list[str | None] = []
    total = len(important_tables)

    for i, table in enumerate(important_tables):
        table_md = table.get("markdown", "")
        caption = table.get("caption", table.get("context", f"Table {i + 1}"))
        dest = os.path.join(output_dir, f"table_chart_{i + 1}.png")

        print(f"[diagram_gen] Generating table chart {i + 1}/{total}...")
        try:
            path, title = _generate_table_chart(table_md, caption, dest)
            important_tables[i]["caption"] = title
            print(f"[diagram_gen] Table chart {i + 1}/{total} — OK ({title})")
            results.append(path)
        except Exception as exc:
            print(f"[diagram_gen] Table chart {i + 1}/{total} — FAILED: {type(exc).__name__}: {exc}")
            results.append(None)

    succeeded = sum(1 for r in results if r)
    print(f"[diagram_gen] Table charts done: {succeeded}/{total} succeeded")
    return results


async def _generate_chart_direct(description: str, caption: str,
                                 dest_path: str) -> str:
    """Generate a matplotlib chart directly via LLM, bypassing PaperBanana."""
    # 1. Ask LLM to write matplotlib code
    prompt = _CHART_PROMPT.format(description=description, caption=caption)
    resp = await asyncio.to_thread(llm_call, prompt)
    code = resp.text.strip()

    # Strip markdown fences if present
    code = _re.sub(r"^```(?:python)?\s*\n?", "", code)
    code = _re.sub(r"\n?```\s*$", "", code)

    # 2. Write code to a temp file with OUTPUT_PATH injected
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        # Inject output path as first line
        f.write(f'OUTPUT_PATH = r"{dest_path}"\n\n')
        f.write(code)
        script_path = f.name

    # 3. Execute the script
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            stderr = result.stderr[:500] if result.stderr else "(no stderr)"
            raise RuntimeError(f"matplotlib script failed (rc={result.returncode}): {stderr}")
    finally:
        os.unlink(script_path)

    # 4. Validate output
    if not os.path.exists(dest_path):
        raise RuntimeError("matplotlib script ran but produced no output file")
    if os.path.getsize(dest_path) == 0:
        os.unlink(dest_path)
        raise RuntimeError("matplotlib script produced an empty file")

    # Check for all-white image (blank placeholder)
    try:
        from PIL import Image
        img = Image.open(dest_path).convert("RGB")
        extrema = img.getextrema()  # ((min_r, max_r), (min_g, max_g), (min_b, max_b))
        if all(lo > 250 and hi > 250 for lo, hi in extrema):
            os.unlink(dest_path)
            raise RuntimeError("matplotlib script produced an all-white image")
    except ImportError:
        pass  # PIL not available — skip white-check

    return dest_path


async def _run_single(text: str, caption: str, dest_path: str,
                      diagram_type_str: str = "methodology") -> str:
    from paperbanana import PaperBananaPipeline, GenerationInput, DiagramType
    from paperbanana.core.config import Settings

    # Map string type to DiagramType enum
    _type_map = {
        "statistical_plot": DiagramType.STATISTICAL_PLOT,
        "methodology": DiagramType.METHODOLOGY,
    }
    dtype = _type_map.get(diagram_type_str.lower(), DiagramType.METHODOLOGY)

    # Point all data paths at the vendor clone so PaperBanana finds its
    # reference images, guidelines, and prompt templates regardless of CWD.
    settings = Settings(
        vlm_provider="gemini",
        image_provider="google_imagen",
        refinement_iterations=ITERATIONS,
        reference_set_path=str(_VENDOR_DATA / "reference_sets"),
        guidelines_path=str(_VENDOR_DATA / "guidelines"),
        output_dir=str(pathlib.Path(dest_path).parent),
        save_iterations=False,
    )
    pipeline = PaperBananaPipeline(settings=settings)

    result = await pipeline.generate(
        GenerationInput(
            source_context=text,
            communicative_intent=caption,
            diagram_type=dtype,
        )
    )



    # Validate the result before copying
    if not result or not getattr(result, "image_path", None):
        raise RuntimeError("PaperBanana returned no image_path")
    if not os.path.exists(result.image_path):
        raise RuntimeError(f"PaperBanana image_path does not exist: {result.image_path}")
    if os.path.getsize(result.image_path) == 0:
        raise RuntimeError(f"PaperBanana produced empty file: {result.image_path}")

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    shutil.copy(result.image_path, dest_path)
    return dest_path


def _preflight_check() -> str | None:
    """Verify SDK and API key before burning tokens on planner/stylist.
    Returns an error message string, or None if OK."""
    try:
        from google.genai import types
        if not hasattr(types, "ImageConfig"):
            return "google-genai SDK missing types.ImageConfig — upgrade with: pip install -U google-genai"
        if not hasattr(types, "GenerateContentConfig"):
            return "google-genai SDK missing types.GenerateContentConfig"
    except ImportError:
        return "google-genai SDK not installed"
    if not os.getenv("GOOGLE_API_KEY"):
        return "GOOGLE_API_KEY not set"
    return None


async def _run_all(banana_blocks: list[dict], output_dir: str) -> list[str]:
    """Run all diagram generations concurrently with a semaphore cap."""
    sem = asyncio.Semaphore(_MAX_CONCURRENT)
    total = len(banana_blocks)

    async def _guarded(idx: int, block: dict) -> str | None:
        name = block.get("filename", f"diagram_{idx}")
        dest = os.path.join(output_dir, f"{idx:03d}_{name}.png")

        # Determine diagram type — force Arc 4 to statistical_plot
        dtype = block.get("diagram_type", "methodology")
        arc_level = block.get("arc_level")
        if arc_level == 4 and dtype.lower() == "methodology":
            dtype = "statistical_plot"

        is_chart = (arc_level == 4 or dtype.lower() == "statistical_plot")
        route = "direct" if is_chart else "banana"
        print(f"[diagram_gen] ({idx}/{total}) Generating '{name}' (type={dtype}, arc={arc_level}, chart={route})...")
        async with sem:
            try:
                if is_chart:
                    path = await _generate_chart_direct(block["text"], block["caption"], dest)
                else:
                    path = await _run_single(block["text"], block["caption"], dest, diagram_type_str=dtype)
                print(f"[diagram_gen] ({idx}/{total}) '{name}' — OK")
                return path
            except Exception as exc:
                cause = exc
                if hasattr(exc, "last_attempt"):
                    inner = exc.last_attempt.exception()
                    if inner is not None:
                        cause = inner
                print(f"[diagram_gen] ({idx}/{total}) '{name}' — FAILED: {type(cause).__name__}: {cause}")
                return None

    results = await asyncio.gather(
        *[_guarded(i, b) for i, b in enumerate(banana_blocks, 1)]
    )
    paths = [p for p in results if p and os.path.exists(p)]
    failed = total - len(paths)
    print(f"[diagram_gen] Done: {len(paths)} succeeded, {failed} failed out of {total}")
    return paths


def generate_diagrams(banana_blocks: list[dict], output_dir: str) -> list[str]:
    """Synchronous entry point. Returns list of PNG paths."""
    # Fail fast: check SDK + key before making any API calls
    err = _preflight_check()
    if err:
        print(f"[diagram_gen] Preflight failed, skipping all diagrams: {err}")
        return []

    os.makedirs(output_dir, exist_ok=True)
    return asyncio.run(_run_all(banana_blocks, output_dir))
