"""LaTeX-to-PNG rendering for Substack export.

Converts LaTeX math expressions to base64-encoded PNG images using
matplotlib's mathtext engine. No external TeX installation required.

Used only by the Substack export path in orchestrator.py.
The main digest continues to use KaTeX client-side rendering.
"""

import base64
import io
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


# ── Cache ────────────────────────────────────────────────────────────────────

_cache: dict[tuple[str, int, int, bool], str] = {}


def clear_cache() -> None:
    """Clear the render cache."""
    _cache.clear()


# ── Preprocessing ────────────────────────────────────────────────────────────

def _preprocess_latex(latex: str) -> str:
    """Adapt LaTeX for matplotlib's mathtext engine."""
    # \text{...} -> \mathrm{...}
    latex = re.sub(r"\\text\{", r"\\mathrm{", latex)
    # \textbf{...} -> \mathbf{...}
    latex = re.sub(r"\\textbf\{", r"\\mathbf{", latex)
    # \textit{...} -> \mathit{...}
    latex = re.sub(r"\\textit\{", r"\\mathit{", latex)
    # \operatorname{...} -> \mathrm{...}
    latex = re.sub(r"\\operatorname\{", r"\\mathrm{", latex)
    # Strip \left and \right (mathtext auto-sizes delimiters)
    latex = latex.replace(r"\left", "").replace(r"\right", "")
    # \| -> \Vert
    latex = latex.replace(r"\|", r"\Vert")
    # \mathbb -> \mathrm (mathtext has limited \mathbb support)
    latex = re.sub(r"\\mathbb\{", r"\\mathrm{", latex)
    # \bm{...} and \boldsymbol{...} -> \mathbf{...}
    latex = re.sub(r"\\bm\{", r"\\mathbf{", latex)
    latex = re.sub(r"\\boldsymbol\{", r"\\mathbf{", latex)
    # Remove \displaystyle (mathtext doesn't need it)
    latex = latex.replace(r"\displaystyle", "")
    # \ldots -> \cdots
    latex = latex.replace(r"\ldots", r"\cdots")
    # Fix bare subscripts/superscripts with no base variable (e.g. _{448})
    if latex.startswith("_") or latex.startswith("^"):
        latex = "{" + latex + "}"
    return latex


def _html_escape(text: str) -> str:
    """Escape HTML special characters."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


# ── Core renderer ────────────────────────────────────────────────────────────

def render_latex_to_b64png(
    latex: str,
    fontsize: int = 14,
    dpi: int = 150,
    transparent: bool = True,
) -> str | None:
    """Render a LaTeX expression to a base64-encoded PNG string.

    Args:
        latex: Raw LaTeX (without $ delimiters).
        fontsize: Font size in points.
        dpi: Resolution.
        transparent: Whether background is transparent.

    Returns:
        Base64 string of the PNG, or None if rendering fails.
    """
    latex = latex.strip()
    if not latex:
        return None

    cache_key = (latex, fontsize, dpi, transparent)
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        fig = plt.figure(figsize=(10, 1))
        fig.text(
            0.5, 0.5,
            f"${latex}$",
            fontsize=fontsize,
            math_fontfamily="cm",
            color="black",
            ha="center",
            va="center",
        )

        buf = io.BytesIO()
        fig.savefig(
            buf,
            format="png",
            dpi=dpi,
            bbox_inches="tight",
            pad_inches=0.05,
            transparent=transparent,
            facecolor="white" if not transparent else "none",
        )
        plt.close(fig)

        b64 = base64.b64encode(buf.getvalue()).decode()
        _cache[cache_key] = b64
        return b64
    except Exception:
        plt.close("all")
        return None


def render_latex_to_png_file(
    latex: str,
    fontsize: int = 16,
    dpi: int = 200,
) -> str | None:
    """Render LaTeX to a temporary PNG file on disk.

    Returns the file path, or None if rendering fails.
    Caller is responsible for deleting the file after use.
    """
    import tempfile

    latex = latex.strip()
    if not latex:
        return None

    latex = _preprocess_latex(latex)

    try:
        fig = plt.figure(figsize=(10, 1))
        fig.text(
            0.5, 0.5,
            f"${latex}$",
            fontsize=fontsize,
            math_fontfamily="cm",
            color="black",
            ha="center",
            va="center",
        )

        tmp = tempfile.NamedTemporaryFile(
            suffix=".png", delete=False, prefix="latex_"
        )
        tmp_path = tmp.name
        tmp.close()

        fig.savefig(
            tmp_path,
            format="png",
            dpi=dpi,
            bbox_inches="tight",
            pad_inches=0.05,
            transparent=False,
            facecolor="white",
        )
        plt.close(fig)
        return tmp_path
    except Exception:
        plt.close("all")
        return None


# ── Public API ───────────────────────────────────────────────────────────────

def latex_to_inline_img(raw_math: str) -> str:
    """Convert a $...$ inline math string to an <img> tag.

    Falls back to <code> styled text on render failure.
    """
    inner = raw_math.strip()
    if inner.startswith("$") and inner.endswith("$"):
        inner = inner[1:-1]

    inner = _preprocess_latex(inner)
    b64 = render_latex_to_b64png(inner, fontsize=13, dpi=150, transparent=True)

    if b64:
        alt = _html_escape(raw_math)
        return (
            f'<img src="data:image/png;base64,{b64}" '
            f'alt="{alt}" '
            f'style="vertical-align:middle;height:1.2em;display:inline;" />'
        )

    escaped = _html_escape(raw_math)
    return (
        f'<code style="background:#f0f0f0;padding:1px 4px;'
        f'font-size:0.9em;">{escaped}</code>'
    )


def latex_to_block_img(raw_math: str) -> str:
    """Convert a $$...$$ display math string to a centered <img> tag.

    Falls back to <pre><code> styled text on render failure.
    """
    inner = raw_math.strip()
    if inner.startswith("$$") and inner.endswith("$$"):
        inner = inner[2:-2].strip()

    inner = _preprocess_latex(inner)
    b64 = render_latex_to_b64png(inner, fontsize=16, dpi=200, transparent=False)

    if b64:
        alt = _html_escape(raw_math)
        return (
            f'<div style="text-align:center;margin:16px 0;">'
            f'<img src="data:image/png;base64,{b64}" '
            f'alt="{alt}" '
            f'style="max-width:90%;" />'
            f'</div>'
        )

    escaped = _html_escape(raw_math)
    return (
        f'<pre style="text-align:center;background:#f8f8f8;'
        f'padding:12px;overflow-x:auto;"><code>{escaped}</code></pre>'
    )
