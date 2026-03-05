"""
orchestrator.py
---------------
Replaces [DIAGRAM: ...] markers with images and assembles the final HTML digest.
"""

import os
import re
import base64
import markdown2


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _img_to_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _compress_img_to_b64(path: str, quality: int = 90) -> str:
    """Compress a PNG to WebP at full resolution, return base64."""
    from PIL import Image
    import io
    img = Image.open(path)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


# ─────────────────────────────────────────────────────────────────────────────
# Markdown → HTML helpers
# ─────────────────────────────────────────────────────────────────────────────

def _markdown_to_html_sections(summary: str) -> list[dict]:
    """
    Split the Markdown summary into section dicts:
      {"heading": str, "body": str, "anchor": str}
    """
    sections = []
    current = None

    for line in summary.split("\n"):
        m = re.match(r"^##\s+(.+)", line)
        if m:
            if current:
                sections.append(current)
            heading = m.group(1).strip()
            anchor = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
            current = {"heading": heading, "body": "", "anchor": anchor}
        elif current is not None:
            current["body"] += line + "\n"

    if current:
        sections.append(current)

    return sections


def _strip_backtick_wrapped_math(text: str) -> str:
    """Strip backticks that wrap $...$ or $$...$$ math expressions.

    The LLM sometimes writes `$x$` or `$$E = mc^2$$` — backtick-wrapped math.
    markdown2 converts the backtick content to <code>, which HTML-escapes the
    math placeholder and breaks restoration. Strip the backticks early so the
    protect/restore cycle works cleanly.
    """
    # `$$...$$` → $$...$$
    text = re.sub(r'`(\$\$.+?\$\$)`', r'\1', text)
    # `$...$` → $...$  (but not `$$`)
    text = re.sub(r'`(\$(?!\$).+?\$)`', r'\1', text)
    return text


def _strip_post_equation_blocks(text: str) -> str:
    """Remove variable-interpretation paragraphs that follow display math.

    Detects patterns like:
        $$equation$$
        Here, $X$ is the..., $Y$ is the..., $Z$ is the...

    These blocks contain dense inline math that often renders as raw text.
    The summarizer prompt forbids them, but the LLM still generates them.
    """
    lines = text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        result.append(lines[i])
        # Check if this line closes a display-math block (contains $$)
        if "$$" in lines[i]:
            # Look ahead past blank lines for an interpretation paragraph
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                first_line = lines[j].strip()
                # Common openers for variable-interpretation blocks
                openers = (
                    "here,", "where ", "in this equation",
                    "in the above", "in this formula",
                    "in the equation", "here $", "where $",
                )
                if any(first_line.lower().startswith(op) for op in openers):
                    # Count inline $...$ fragments in the paragraph
                    # Collect the full paragraph (until blank line or heading)
                    para_lines = []
                    k = j
                    while k < len(lines) and lines[k].strip() != "" and not lines[k].strip().startswith("#"):
                        para_lines.append(lines[k])
                        k += 1
                    para = " ".join(para_lines)
                    inline_count = len(re.findall(r"(?<!\$)\$(?!\$).+?(?<!\$)\$(?!\$)", para))
                    if inline_count >= 3:
                        # Skip the blank lines and the interpretation paragraph
                        i = k
                        continue
        i += 1
    return "\n".join(result)


def _protect_display_math(text: str) -> tuple[str, list[str]]:
    """Replace $$...$$ display math blocks with HTML comment placeholders.

    Blank lines around the placeholder force markdown2 to treat it as a
    separate block rather than embedding it inside a <p>.
    """
    blocks = []

    def _replace(m):
        blocks.append(m.group(0))
        return f"\n\n<!--MATH_BLOCK_{len(blocks)-1}-->\n\n"

    text = re.sub(r"\$\$(.*?)\$\$", _replace, text, flags=re.DOTALL)
    return text, blocks


def _protect_inline_math(text: str) -> tuple[str, list[str]]:
    """Replace $...$ inline math with HTML comment placeholders."""
    inlines = []

    def _replace(m):
        inlines.append(m.group(0))
        return f"<!--MATH_INLINE_{len(inlines)-1}-->"

    text = re.sub(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", _replace, text)
    return text, inlines


def _protect_diagrams(text: str) -> tuple[str, list[str]]:
    """Replace [DIAGRAM: ...] markers with HTML comment placeholders."""
    markers = []

    def _replace(m):
        markers.append(m.group(0))
        return f"\n\n<!--DIAGRAM_{len(markers)-1}-->\n\n"

    text = re.sub(r"\[DIAGRAM:\s*(.+?)\]", _replace, text)
    return text, markers


def _restore_display_math(html: str, blocks: list[str]) -> str:
    """Restore $$...$$ blocks as styled math-block divs.

    Handles normal placeholders and HTML-escaped versions.
    """
    for i, block in enumerate(blocks):
        placeholder = f"<!--MATH_BLOCK_{i}-->"
        escaped = f"&lt;!--MATH_BLOCK_{i}--&gt;"
        replacement = f'<div class="math-block">{block}</div>'
        # Remove wrapping <p> tags if markdown2 added them
        html = html.replace(f"<p>{placeholder}</p>", replacement)
        html = html.replace(f"<p>{escaped}</p>", replacement)
        html = html.replace(f"<code>{placeholder}</code>", replacement)
        html = html.replace(f"<code>{escaped}</code>", replacement)
        html = html.replace(escaped, replacement)
        html = html.replace(placeholder, replacement)
    return html


def _restore_inline_math(html: str, inlines: list[str]) -> str:
    """Restore inline $...$ math expressions.

    Handles three scenarios:
      1. Normal placeholder: <!--MATH_INLINE_N-->
      2. HTML-escaped (inside <code>): &lt;!--MATH_INLINE_N--&gt;
      3. Wrapped in <code> tags: <code><!--MATH_INLINE_N--></code>
    """
    for i, inline in enumerate(inlines):
        placeholder = f"<!--MATH_INLINE_{i}-->"
        escaped = f"&lt;!--MATH_INLINE_{i}--&gt;"
        # Strip <code> wrapping around the placeholder
        html = html.replace(f"<code>{placeholder}</code>", inline)
        html = html.replace(f"<code>{escaped}</code>", inline)
        # Replace HTML-escaped version (may appear without <code> wrapper too)
        html = html.replace(escaped, inline)
        # Normal replacement
        html = html.replace(placeholder, inline)
    return html


def _protect_tables(text: str) -> tuple[str, list[str]]:
    """Replace [TABLE: N] markers with HTML comment placeholders."""
    markers = []

    def _replace(m):
        markers.append(m.group(0))
        return f"\n\n<!--TABLE_{len(markers)-1}-->\n\n"

    text = re.sub(r"\[TABLE:\s*(\d+)\]", _replace, text)
    return text, markers


def _protect_code_blocks(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Replace fenced code blocks with placeholders before markdown2 processing.

    Returns (text_with_placeholders, [(lang, code), ...]).
    """
    blocks = []

    def _replace(m):
        lang = m.group(1) or "text"
        code = m.group(2)
        blocks.append((lang, code))
        return f"\n\n<!--CODE_BLOCK_{len(blocks)-1}-->\n\n"

    text = re.sub(r"```([\w-]*)\n(.*?)```", _replace, text, flags=re.DOTALL)
    return text, blocks


def _dedent_markdown_lines(text: str) -> str:
    """Strip 4-space indent from lines that are clearly markdown formatting.

    After code blocks are replaced with placeholders, any remaining 4-space
    indented lines (list items, blockquotes, headings) get misinterpreted as
    preformatted code by markdown2. This function strips the indent from lines
    that start with recognisable markdown markers.
    """
    out = []
    for line in text.split("\n"):
        # Match 4+ spaces followed by a markdown marker: *, -, >, digit., #
        m = re.match(r'^( {4,})([*\->]|\d+\.|#{1,4} )', line)
        if m:
            # Strip exactly 4 spaces of indent
            line = line[4:]
        out.append(line)
    return "\n".join(out)


# Language tags recognised by highlight.js that we want to display.
# Anything else (e.g. "php-template", "output") is normalised to "python" or "text".
_KNOWN_LANGS = {
    "python", "javascript", "js", "typescript", "ts",
    "bash", "shell", "sh", "sql", "cpp", "c", "java",
    "json", "yaml", "toml", "text", "plaintext", "",
}


def _restore_code_blocks(html: str, blocks: list[tuple[str, str]]) -> str:
    """Restore code block placeholders as Carbon-styled code windows."""
    for i, (lang, code) in enumerate(blocks):
        placeholder = f"<!--CODE_BLOCK_{i}-->"
        # Normalise nonsense lang tags produced by the LLM (e.g. "php-template")
        display_lang = lang if lang in _KNOWN_LANGS else "python"
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        replacement = (
            f'<div class="code-window">'
            f'<div class="code-chrome">'
            f'<div class="code-dots"><span></span><span></span><span></span></div>'
            f'<span class="code-lang">{display_lang}</span>'
            f'</div>'
            f'<pre><code class="language-{display_lang}">{escaped}</code></pre>'
            f'</div>'
        )
        html = html.replace(f"<p>{placeholder}</p>", replacement)
        html = html.replace(placeholder, replacement)
    return html


def _restore_diagrams(
    html: str,
    markers: list[str],
    img_b64_list: list[tuple[str, str]],
    diagram_counter: list[int],
) -> str:
    """Restore diagram placeholders with AI-generated images."""
    for i in range(len(markers)):
        placeholder = f"<!--DIAGRAM_{i}-->"
        idx = diagram_counter[0]
        if idx < len(img_b64_list):
            b64, caption = img_b64_list[idx]
            replacement = (
                f'<figure class="paper-diagram">'
                f'<img src="data:image/webp;base64,{b64}" alt="{caption}" />'
                f'</figure>'
            )
        else:
            replacement = ""
        html = html.replace(f"<p>{placeholder}</p>", replacement)
        html = html.replace(placeholder, replacement)
        diagram_counter[0] += 1
    return html


def _restore_table_markers(
    html: str,
    markers: list[str],
    important_tables: list[dict] | None = None,
    table_chart_paths: list[str | None] | None = None,
) -> str:
    """Restore [TABLE: N] placeholders with chart images or styled HTML tables."""
    if not important_tables:
        important_tables = []

    for i, marker in enumerate(markers):
        placeholder = f"<!--TABLE_{i}-->"

        # Extract table index from original marker: [TABLE: N]
        m = re.search(r"\[TABLE:\s*(\d+)\]", marker)
        if m:
            table_num = int(m.group(1)) - 1  # 1-indexed -> 0-indexed
        else:
            table_num = i

        # Prefer chart image if available
        if (table_chart_paths
                and 0 <= table_num < len(table_chart_paths)
                and table_chart_paths[table_num]):
            chart_path = table_chart_paths[table_num]
            caption = ""
            if 0 <= table_num < len(important_tables):
                caption = important_tables[table_num].get("caption", f"Table {table_num + 1}")
            else:
                caption = f"Table {table_num + 1}"
            b64 = _compress_img_to_b64(chart_path)
            replacement = (
                f'<figure class="paper-diagram">'
                f'<img src="data:image/webp;base64,{b64}" alt="{caption}" />'
                f'<figcaption>Table {table_num + 1}: {caption}</figcaption>'
                f'</figure>'
            )
        elif 0 <= table_num < len(important_tables):
            # Fallback: render as HTML table
            table = important_tables[table_num]
            caption = table.get("caption", f"Table {table_num + 1}")
            table_html = markdown2.markdown(
                table["markdown"],
                extras=["tables"],
            )
            replacement = (
                f'<div class="paper-table">'
                f'<div class="table-caption">Table {table_num + 1}: {caption}</div>'
                f'<div class="table-scroll">{table_html}</div>'
                f'</div>'
            )
        else:
            replacement = ""

        html = html.replace(f"<p>{placeholder}</p>", replacement)
        html = html.replace(placeholder, replacement)

    return html


def _strip_raw_tables(text: str) -> str:
    """Remove raw markdown pipe-tables from summary text.

    Tables should only appear via [TABLE: N] markers (already protected).
    Any remaining pipe-tables are LLM artifacts that cause duplicate rendering.
    """
    lines = text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        # Detect start of a pipe-table block
        if lines[i].strip().startswith("|"):
            block_start = i
            while i < len(lines) and lines[i].strip().startswith("|"):
                i += 1
            block = lines[block_start:i]
            # Only strip if it looks like a real table (has separator row)
            has_sep = any(re.match(r"^\|[\s\-:|]+\|$", ln.strip()) for ln in block)
            if has_sep and len(block) >= 3:
                # Replace table block with empty line (preserve spacing)
                result.append("")
            else:
                result.extend(block)
        else:
            result.append(lines[i])
            i += 1
    return "\n".join(result)


def _render_body(body: str, img_b64_list: list[tuple[str, str]],
                 diagram_counter: list[int],
                 important_tables: list[dict] | None = None,
                 table_chart_paths: list[str | None] | None = None) -> str:
    """Convert a section body (Markdown) to HTML using markdown2.

    [DIAGRAM: ...] markers are replaced with actual images from img_b64_list
    in the order they appear (tracked via diagram_counter[0]).
    [TABLE: N] markers are replaced with styled HTML tables.
    """
    text = body.strip()
    if not text:
        return ""

    # Pre-process: strip post-equation interpretation blocks (dense $var$ paragraphs).
    # Must run BEFORE the protect/restore cycle to avoid corrupted inline math.
    text = _strip_post_equation_blocks(text)

    # Pre-process: strip backticks wrapping math before the protect/restore cycle.
    # The LLM sometimes writes `$x$` which breaks restoration.
    text = _strip_backtick_wrapped_math(text)

    # Pre-process: protect special content from markdown2.
    # ORDER MATTERS: math must be protected BEFORE code blocks, because
    # the LLM sometimes wraps text-with-math-placeholders inside a fenced
    # code block, which would freeze the placeholder before it can be restored.
    text, math_blocks  = _protect_display_math(text)
    text, math_inlines = _protect_inline_math(text)
    text, code_blocks  = _protect_code_blocks(text)   # after math
    text = _dedent_markdown_lines(text)                # fix indented markdown after code blocks
    text, diag_markers = _protect_diagrams(text)
    text, table_markers = _protect_tables(text)
    text = _strip_raw_tables(text)

    # Convert with markdown2
    html = markdown2.markdown(text, extras=[
        "cuddled-lists",
        "code-friendly",
        "tables",
    ])

    # Post-process: restore in REVERSE order of protection.
    html = _restore_table_markers(html, table_markers, important_tables, table_chart_paths)
    html = _restore_code_blocks(html, code_blocks)
    html = _restore_diagrams(html, diag_markers, img_b64_list, diagram_counter)
    html = _restore_inline_math(html, math_inlines)
    html = _restore_display_math(html, math_blocks)

    return html


# ─────────────────────────────────────────────────────────────────────────────
# LLM refinement — integrate code snippets into summary
# ─────────────────────────────────────────────────────────────────────────────

def _strip_prose_code_fences(text: str) -> str:
    """Remove fenced code blocks that contain prose rather than actual code.

    The LLM sometimes wraps explanatory text in ```php-template or similar
    bogus lang tags. These blocks contain MATH_INLINE placeholders that break
    rendering. Unwrap them back to plain markdown so text survives intact.
    """
    PROSE_LANGS = {"php-template", "output", "plaintext", "text", ""}
    # Strip HTML comments first (e.g. <!--MATH_INLINE_N-->) before checking
    # for code tokens, because --> contains -> which false-positives on "->".
    CODE_TOKENS = ("def ", "class ", "import ", "return ", "for ", " = ", "()")

    def _replace(m):
        lang = m.group(1)
        body = m.group(2).strip()
        clean_body = re.sub(r'<!--.*?-->', '', body)
        if lang in PROSE_LANGS and not any(tok in clean_body for tok in CODE_TOKENS):
            return "\n\n" + body + "\n\n"
        return m.group(0)

    return re.sub(r'```([\w-]*)\n(.*?)```', _replace, text, flags=re.DOTALL)
def _cap_code_blocks(text: str, max_blocks: int = 5, max_lines: int = 20) -> str:
    """Enforce hard limits: at most *max_blocks* code fences, each at most *max_lines* long."""
    lines = text.split("\n")
    result = []
    block_count = 0
    in_code = False
    code_buf = []
    opener_line = ""

    for line in lines:
        if not in_code and re.match(r"^```[a-z]*\s*$", line):
            # Opening fence
            in_code = True
            opener_line = line
            code_buf = []
        elif in_code and line.strip() == "```":
            # Closing fence — decide whether to keep this block
            in_code = False
            block_count += 1
            if block_count <= max_blocks:
                result.append(opener_line)
                if len(code_buf) > max_lines:
                    result.extend(code_buf[:max_lines])
                    result.append("# ...")
                else:
                    result.extend(code_buf)
                result.append("```")
            # else: silently drop the block, keep surrounding text
        elif in_code:
            code_buf.append(line)
        else:
            result.append(line)

    # If file ended inside an unclosed fence, flush it
    if in_code:
        block_count += 1
        if block_count <= max_blocks:
            result.append(opener_line)
            result.extend(code_buf[:max_lines])
            result.append("```")

    return "\n".join(result)


# Sections where code blocks are allowed
_CODE_ALLOWED_SECTIONS = {"How It Works", "Results & Insights"}


def _enforce_code_section_restriction(text: str) -> str:
    """Remove fenced code blocks that appear outside allowed sections.

    Allowed sections: "How It Works" and "Results & Insights".
    All other sections (The Big Picture, The Core Idea, Limitations & Future,
    Key Takeaways) have code blocks silently stripped.
    """
    lines = text.split("\n")
    result = []
    current_section = ""
    in_code = False
    code_buf = []
    opener_line = ""

    for line in lines:
        # Track which ## section we're in
        heading_match = re.match(r"^## (.+)", line)
        if heading_match and not in_code:
            current_section = heading_match.group(1).strip()

        if not in_code and re.match(r"^```[a-z]*\s*$", line):
            # Opening fence — buffer it until we see the closing fence
            in_code = True
            opener_line = line
            code_buf = []
        elif in_code and line.strip() == "```":
            # Closing fence — keep block only if in an allowed section
            in_code = False
            if current_section in _CODE_ALLOWED_SECTIONS:
                result.append(opener_line)
                result.extend(code_buf)
                result.append("```")
            # else: silently drop
        elif in_code:
            code_buf.append(line)
        else:
            result.append(line)

    # If file ended inside an unclosed fence, flush if allowed
    if in_code and current_section in _CODE_ALLOWED_SECTIONS:
        result.append(opener_line)
        result.extend(code_buf)
        result.append("```")

    return "\n".join(result)


def _validate_refinement(original: str, refined: str) -> tuple[bool, list[str]]:
    """Programmatic checks that refinement didn't damage the summary.

    Returns (is_valid, list_of_issues).
    """
    issues: list[str] = []

    # 1. Diagram marker count: refined >= original
    orig_diagrams = len(re.findall(r"\[DIAGRAM:\s*.+?\]", original))
    ref_diagrams = len(re.findall(r"\[DIAGRAM:\s*.+?\]", refined))
    if ref_diagrams < orig_diagrams:
        issues.append(f"Lost diagram markers ({ref_diagrams} < {orig_diagrams})")

    # 1b. Table marker count: refined >= original
    orig_tables = len(re.findall(r"\[TABLE:\s*\d+\]", original))
    ref_tables = len(re.findall(r"\[TABLE:\s*\d+\]", refined))
    if ref_tables < orig_tables:
        issues.append(f"Lost table markers ({ref_tables} < {orig_tables})")

    # 2. Section heading count: refined >= original
    orig_headings = len(re.findall(r"^## ", original, re.MULTILINE))
    ref_headings = len(re.findall(r"^## ", refined, re.MULTILINE))
    if ref_headings < orig_headings:
        issues.append(f"Lost section headings ({ref_headings} < {orig_headings})")

    # 3. Length: refined >= 70% of original
    if len(refined) < len(original) * 0.7:
        issues.append(f"Too short ({len(refined)} chars < 70% of {len(original)})")

    # 4. No placeholder text leaked
    for pattern in ("MATH_INLINE_", "MATH_BLOCK_", "CODE_BLOCK_", "DIAGRAM_"):
        if pattern in refined:
            issues.append(f"Leaked placeholder: {pattern}")

    return (len(issues) == 0, issues)


def validate_final_summary(
    summary: str,
    num_tables: int = 0,
) -> tuple[str, list[str]]:
    """Final QC pass: fix invalid markers and detect issues before HTML rendering.

    Unlike _validate_refinement() which returns bool, this FIXES what it can
    and returns (cleaned_summary, list_of_warnings).
    """
    warnings: list[str] = []

    # 1. Strip invalid [TABLE: N] markers (N > num_tables or N < 1)
    def _check_table_ref(m: re.Match) -> str:
        n = int(m.group(1))
        if n < 1 or n > num_tables:
            warnings.append(f"Removed invalid [TABLE: {n}] (only {num_tables} tables)")
            return ""
        return m.group(0)
    summary = re.sub(r"\[TABLE:\s*(\d+)\]", _check_table_ref, summary)

    # 2. Warn if [TABLE: 1] appears after [TABLE: 2]
    positions = [
        (m.start(), int(m.group(1)))
        for m in re.finditer(r"\[TABLE:\s*(\d+)\]", summary)
    ]
    for i in range(len(positions) - 1):
        if positions[i][1] > positions[i + 1][1]:
            warnings.append(
                f"Table markers out of order: [TABLE: {positions[i][1]}] "
                f"before [TABLE: {positions[i + 1][1]}]"
            )

    # 3. Strip orphan raw markdown tables
    summary = _strip_raw_tables(summary)

    # 4. LaTeX delimiter integrity — odd $ count means unmatched math
    text_no_display = re.sub(r"\$\$.*?\$\$", "", summary, flags=re.DOTALL)
    single_dollars = re.findall(r"(?<!\$)\$(?!\$)", text_no_display)
    if len(single_dollars) % 2 != 0:
        warnings.append(f"Odd number of $ delimiters ({len(single_dollars)})")

    # 5. Unclosed code fences
    fences = re.findall(r"^```", summary, re.MULTILINE)
    if len(fences) % 2 != 0:
        warnings.append(f"Unclosed code fence ({len(fences)} ``` markers)")

    return summary, warnings


def refine_summary_with_code(
    summary: str,
    code_snippets: list[dict],
    iterations: int = 1,
) -> str:
    """Use an LLM call to place the most relevant code snippets inline in the summary.

    Args:
        summary: The current Markdown summary (with [DIAGRAM: ...] markers).
        code_snippets: List of {"title": str, "code": str} from the notebook.
        iterations: Number of refinement passes (default 1, set 0 to skip).

    Returns:
        Refined summary with code blocks inserted, or original on failure.
    """
    if not code_snippets or iterations <= 0:
        return summary

    from llm_client import llm_call

    # Build snippet reference for the prompt
    snippet_block = ""
    for i, s in enumerate(code_snippets, 1):
        snippet_block += f"\n--- Snippet {i}: {s['title']} ---\n```python\n{s['code']}\n```\n"

    for _ in range(iterations):
        pre_iteration = summary  # snapshot before this iteration

        prompt = f"""You are editing a technical blog-post summary of a research paper.

TASK: Insert 1–2 of the most relevant code snippets from the notebook into the summary as fenced Python code blocks (```python ... ```). Place each snippet RIGHT AFTER the paragraph that explains the concept it implements. Keep total additions minimal — the article should stay under a 15-minute read.

RULES:
1. Preserve ALL existing [DIAGRAM: ...] markers exactly as they are — do not move, remove, or modify them.
2. Preserve ALL existing [TABLE: ...] markers exactly as they are — do not move, remove, or modify them.
3. Preserve ALL LaTeX math ($...$ and $$...$$) exactly as they are.
4. Do NOT add new sections or change section headings (## lines).
5. Do NOT add commentary like "Here is the code" — just insert the code block silently after the relevant paragraph.
6. SECTION RESTRICTION: Code snippets may ONLY be placed in "## How It Works" or "## Results & Insights" sections. NEVER place code in "## The Big Picture", "## The Core Idea", "## Limitations & Future", or "## Key Takeaways". Readers must understand the concept visually before seeing code.
7. Keep each snippet to 8-10 lines MAX. Rewrite as simplified PSEUDO-CODE — not verbatim from the notebook. Strip imports, type hints, docstrings, boilerplate. Focus on the algorithmic logic. Add "# ..." to indicate omitted parts.
8. Pick ONLY snippets that implement the paper's CORE ALGORITHM or KEY EQUATION:
   - Loss functions (compute_loss, objective functions)
   - The paper's main formula implemented in code
   - Novel algorithmic steps unique to this paper
   SKIP these — they are infrastructure, not the paper's contribution:
   - Model architecture classes (Transformer, Embedding, PositionalEncoding)
   - Data structures (Buffer, Dataset, Tokenizer)
   - Training loops, evaluation loops, data generation
   - Generic utilities (generate_completions, train_agent)
9. NEVER wrap explanatory prose in a code fence. Only actual Python code goes in ```python ... ``` blocks. Do NOT use ```php-template, ```output, ```text or any other fake lang tag — write prose as plain markdown paragraphs.
10. NEVER write bare variable names outside of LaTeX delimiters. Every variable must be in $...$. WRONG: "zz is updated". RIGHT: "$z$ is updated". Doubled text like "zz" or "yy" means the variable is undelimited — forbidden.
11. NEVER wrap $...$ or $$...$$ in backticks. Write $x$ directly, NOT `$x$`. Backtick-wrapped math breaks rendering.
12. NEVER follow a display equation ($$...$$) with a variable-by-variable interpretation block like "Here, $X$ is..., $Y$ is...". Move on to the next idea after the equation.
13. Return ONLY the full refined summary — no explanations before or after.

AVAILABLE CODE SNIPPETS:
{snippet_block}

CURRENT SUMMARY:
{summary}

Return the refined summary now:"""

        try:
            resp = llm_call(prompt, max_tokens=16384, temperature=0.2)
            refined = resp.text.strip()
            valid, issues = _validate_refinement(pre_iteration, refined)
            if valid:
                summary = refined
            else:
                # Revert to pre-iteration summary and stop loop
                summary = pre_iteration
                break
        except Exception:
            # LLM failure — return whatever we have
            break

    # Strip bogus prose-wrapped fences before capping — this prevents
    # _cap_code_blocks from truncating explanatory text that the LLM
    # accidentally wrapped in a php-template or similar fake code fence.
    summary = _strip_prose_code_fences(summary)
    summary = _enforce_code_section_restriction(summary)
    return _cap_code_blocks(summary, max_blocks=2, max_lines=10)


# ─────────────────────────────────────────────────────────────────────────────
# Substack export — clean semantic HTML for paste
# ─────────────────────────────────────────────────────────────────────────────

def _render_body_substack(body: str, img_b64_list: list[tuple[str, str]],
                          diagram_counter: list[int],
                          important_tables: list[dict] | None = None) -> str:
    """Convert section body Markdown to clean semantic HTML for Substack.

    Differences from _render_body():
    - Math rendered as PNG images via matplotlib (Substack does not render LaTeX)
    - Code blocks as plain <pre><code> (no Carbon chrome)
    - No custom CSS classes
    - Diagrams as plain <figure><img>
    """
    text = body.strip()
    if not text:
        return ""

    # Strip post-equation interpretation blocks before the protect/restore cycle.
    text = _strip_post_equation_blocks(text)

    text = _strip_backtick_wrapped_math(text)

    # Protect math, diagrams, and code blocks from markdown2 mangling.
    # Math must be protected first — underscores in $x_y$ become <em> otherwise.
    text, math_blocks  = _protect_display_math(text)
    text, math_inlines = _protect_inline_math(text)
    text, code_blocks  = _protect_code_blocks(text)
    text = _dedent_markdown_lines(text)
    text, diag_markers = _protect_diagrams(text)
    text, table_markers = _protect_tables(text)
    text = _strip_raw_tables(text)

    html = markdown2.markdown(text, extras=[
        "cuddled-lists",
        "code-friendly",
        "tables",
    ])

    # Restore table markers
    html = _restore_table_markers(html, table_markers, important_tables)

    # Restore code blocks as plain <pre><code>
    for i, (lang, code) in enumerate(code_blocks):
        placeholder = f"<!--CODE_BLOCK_{i}-->"
        display_lang = lang if lang in _KNOWN_LANGS else "python"
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        replacement = f'<pre><code class="language-{display_lang}">{escaped}</code></pre>'
        html = html.replace(f"<p>{placeholder}</p>", replacement)
        html = html.replace(placeholder, replacement)

    # Restore diagrams as plain <figure><img>
    for i in range(len(diag_markers)):
        placeholder = f"<!--DIAGRAM_{i}-->"
        idx = diagram_counter[0]
        if idx < len(img_b64_list):
            b64, caption = img_b64_list[idx]
            replacement = (
                f'<figure>'
                f'<img src="data:image/webp;base64,{b64}" alt="{caption}" />'
                f'</figure>'
            )
        else:
            replacement = ""
        html = html.replace(f"<p>{placeholder}</p>", replacement)
        html = html.replace(placeholder, replacement)
        diagram_counter[0] += 1

    # Restore math as rendered PNG images (Substack does NOT render LaTeX)
    from latex_renderer import latex_to_inline_img, latex_to_block_img

    for i, inline in enumerate(math_inlines):
        placeholder = f"<!--MATH_INLINE_{i}-->"
        escaped = f"&lt;!--MATH_INLINE_{i}--&gt;"
        img_html = latex_to_inline_img(inline)
        html = html.replace(f"<code>{placeholder}</code>", img_html)
        html = html.replace(f"<code>{escaped}</code>", img_html)
        html = html.replace(escaped, img_html)
        html = html.replace(placeholder, img_html)
    for i, block in enumerate(math_blocks):
        placeholder = f"<!--MATH_BLOCK_{i}-->"
        escaped = f"&lt;!--MATH_BLOCK_{i}--&gt;"
        img_html = latex_to_block_img(block)
        html = html.replace(f"<p>{placeholder}</p>", img_html)
        html = html.replace(f"<p>{escaped}</p>", img_html)
        html = html.replace(escaped, img_html)
        html = html.replace(placeholder, img_html)

    return html


def build_substack_html(
    summary: str,
    diagram_paths: list[str],
    diagram_captions: list[str],
    paper_title: str = "Research Paper",
    important_tables: list[dict] | None = None,
) -> str:
    """Build clean, semantic-only HTML optimized for Substack paste.

    No <html>/<head>/<body> wrapper, no CSS, no JS, no KaTeX script.
    Math rendered as PNG images via matplotlib (Substack does not render LaTeX).
    Images as base64 <figure><img> (Substack auto-hosts on publish).
    """
    # Build base64 image list — compressed WebP
    img_b64_list: list[tuple[str, str]] = []
    for i, path in enumerate(diagram_paths):
        if os.path.exists(path):
            b64 = _compress_img_to_b64(path)
            cap = diagram_captions[i] if i < len(diagram_captions) else f"Diagram {i+1}"
            img_b64_list.append((b64, cap))

    sections = _markdown_to_html_sections(summary)
    diagram_counter = [0]

    parts = [f"<h1>{paper_title}</h1>"]
    for sec in sections:
        parts.append(f"<h2>{sec['heading']}</h2>")
        body_html = _render_body_substack(sec["body"], img_b64_list, diagram_counter, important_tables)
        parts.append(body_html)

    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Main orchestration
# ─────────────────────────────────────────────────────────────────────────────

def build_final_html(
    summary: str,
    diagram_paths: list[str],
    diagram_captions: list[str],
    notebook_result: dict,
    paper_title: str = "Research Paper",
    authors: list[str] | None = None,
    year: str = "",
    paper_url: str = "",
    citation_count: int | None = None,
    important_tables: list[dict] | None = None,
    table_chart_paths: list[str | None] | None = None,
) -> str:
    """
    Produces a complete, self-contained HTML digest.

    Diagrams are placed inline where [DIAGRAM: ...] markers appear in the
    summary, in order. No LLM call needed for placement.
    """
    # 1. Build base64 image list (in order, matching diagram_paths) — compressed WebP
    img_b64_list: list[tuple[str, str]] = []
    for i, path in enumerate(diagram_paths):
        if os.path.exists(path):
            b64 = _compress_img_to_b64(path)
            cap = diagram_captions[i] if i < len(diagram_captions) else f"Diagram {i+1}"
            img_b64_list.append((b64, cap))

    # 2. Parse summary into sections
    sections = _markdown_to_html_sections(summary)

    # 3. Notebook CTA
    nb_ipynb = notebook_result.get("ipynb_path")
    nb_hosted = notebook_result.get("hosted_url",
                    "https://paper-to-notebook-production.up.railway.app")

    if nb_ipynb:
        nb_filename = os.path.basename(nb_ipynb)
        nb_cta_html = f"""
        <div class="notebook-cta">
          <div class="nb-icon">📒</div>
          <div class="nb-text">
            <strong>Runnable Notebook Generated</strong>
            <span>Full PyTorch implementation of this paper, ready to run in Colab</span>
          </div>
          <div class="nb-actions">
            <a href="/view-notebook/{{SESSION_ID}}" target="_blank" class="btn-secondary">👁 View Notebook</a>
            <a href="#" onclick="openInColab(); return false;" class="btn-colab">
              <img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Colab" style="height:20px;vertical-align:middle;margin-right:6px;">
              Open in Colab
            </a>
            <a href="/download/{{SESSION_ID}}/{nb_filename}" download class="btn-primary">⬇ Download .ipynb</a>
          </div>
        </div>"""
    else:
        nb_cta_html = f"""
        <div class="notebook-cta">
          <div class="nb-icon">🚀</div>
          <div class="nb-text">
            <strong>Convert to Runnable Notebook</strong>
            <span>Upload this PDF to paper-to-notebook to get a full PyTorch Colab notebook</span>
          </div>
          <div class="nb-actions">
            <a href="{nb_hosted}" target="_blank" class="btn-primary">Open paper-to-notebook →</a>
          </div>
        </div>"""

    # 4. Build sections HTML — diagram_counter tracks which image we're on
    diagram_counter = [0]
    sections_html = ""

    for sec in sections:
        anchor = sec["anchor"]
        heading = sec["heading"]
        body_html = _render_body(sec["body"], img_b64_list, diagram_counter,
                                  important_tables=important_tables,
                                  table_chart_paths=table_chart_paths)

        sections_html += f"""
        <section id="{anchor}" class="paper-section">
          <h2>{heading}</h2>
          {body_html}
        </section>\n"""

    # 5. Notebook CTA
    sections_html += f"""
        <section class="paper-section">
          <h2>Runnable Code</h2>
          {nb_cta_html}
        </section>"""

    # 6. Export bar — inline at the very end of the article
    sections_html += """
        <section class="paper-section export-section">
          <h2>Export</h2>
          <div class="export-bar">
            <button onclick="exportDownloadMd()">Download .md</button>
            <button onclick="exportDownloadHtml()">Download HTML</button>
            <button class="substack-btn" onclick="exportCopySubstack()">Copy for Substack</button>
            <span class="export-toast" id="exportToast"></span>
          </div>
        </section>"""

    # 7. Table of contents
    toc_html = "\n".join(
        f'<li><a href="#{s["anchor"]}">{s["heading"]}</a></li>'
        for s in sections
    )

    # 8. Calculate reading time
    word_count = len(summary.split())
    reading_time_min = max(1, round(word_count / 200))

    # 8b. Build author/year/link metadata line
    meta_parts = []
    if authors:
        names = ", ".join(authors)
        meta_parts.append(f'<span class="paper-authors">{names}</span>')
    if citation_count is not None:
        meta_parts.append(f'<span class="paper-citations">{citation_count:,} citations</span>')
    if year:
        meta_parts.append(f'<span class="paper-year">{year}</span>')
    if paper_url:
        meta_parts.append(f'<a href="{paper_url}" target="_blank" class="paper-link">View paper</a>')
    paper_meta_html = ' <span class="meta-sep">&middot;</span> '.join(meta_parts) if meta_parts else ""

    # 9. Assemble full HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{paper_title} — PaperDigest</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
  <style>
    :root {{
      --bg: #faf9f7;
      --surface: #f3f2ef;
      --surface2: #eae8e4;
      --border: #ddd9d3;
      --accent: #2563eb;
      --accent2: #c2410c;
      --accent-dim: rgba(37,99,235,0.06);
      --accent-border: rgba(37,99,235,0.2);
      --text: #1a1a1a;
      --muted: #6b7280;
      --serif: 'Instrument Serif', Georgia, serif;
      --sans: 'DM Sans', system-ui, sans-serif;
      --mono: 'DM Mono', 'Fira Code', monospace;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--sans);
      font-size: 17px;
      line-height: 1.75;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 260px 1fr;
      min-height: 100vh;
      max-width: 1400px;
      margin: 0 auto;
    }}
    .sidebar {{
      position: sticky;
      top: 0;
      height: 100vh;
      overflow-y: auto;
      border-right: 1px solid var(--border);
      padding: 40px 24px;
      background: var(--bg);
      font-family: var(--sans);
    }}
    .sidebar-brand {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 32px;
    }}
    .logo-chip {{
      background: var(--accent);
      color: #fff;
      font-family: var(--mono);
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.08em;
      padding: 4px 8px;
      border-radius: 4px;
    }}
    .sidebar-brand span {{
      font-family: var(--mono);
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.1em;
    }}
    .toc-label {{
      font-size: 10px;
      font-family: var(--mono);
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 12px;
    }}
    .sidebar ul {{ list-style: none; }}
    .sidebar ul li a {{
      display: block;
      padding: 7px 12px;
      color: var(--muted);
      text-decoration: none;
      font-size: 13px;
      border-radius: 6px;
      transition: all 0.15s;
    }}
    .sidebar ul li a:hover {{
      color: var(--text);
      background: var(--surface2);
    }}
    .main {{ padding: 60px 80px; max-width: 860px; }}
    .paper-header {{
      margin-bottom: 56px;
      padding-bottom: 40px;
      border-bottom: 1px solid var(--border);
    }}
    .paper-badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: var(--accent-dim);
      border: 1px solid var(--accent-border);
      border-radius: 20px;
      padding: 4px 14px;
      font-size: 12px;
      font-family: var(--mono);
      color: var(--accent);
      margin-bottom: 20px;
    }}
    .paper-badge::before {{
      content: '';
      width: 6px; height: 6px;
      background: var(--accent);
      border-radius: 50%;
    }}
    h1 {{
      font-family: var(--serif);
      font-size: clamp(28px, 4vw, 44px);
      font-weight: 400;
      font-style: italic;
      line-height: 1.2;
      color: var(--text);
      margin-bottom: 16px;
    }}
    .paper-meta-line {{
      font-size: 14px;
      color: var(--muted);
      font-family: var(--sans);
      margin-bottom: 12px;
      line-height: 1.6;
    }}
    .paper-meta-line:empty {{ display: none; }}
    .paper-authors {{ color: var(--text); font-weight: 500; }}
    .paper-citations {{ color: var(--muted); font-size: 14px; }}
    .paper-year {{ color: var(--muted); }}
    .paper-link {{
      color: var(--accent);
      text-decoration: none;
      font-weight: 500;
    }}
    .paper-link:hover {{ text-decoration: underline; }}
    .meta-sep {{ color: var(--border); margin: 0 2px; }}
    .paper-meta {{
      font-size: 13px;
      color: var(--muted);
      font-family: var(--mono);
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .reading-time {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(74,234,220,0.06);
      border: 1px solid rgba(74,234,220,0.15);
      color: var(--accent);
      border-radius: 6px;
      padding: 3px 10px;
      font-size: 12px;
      font-family: var(--mono);
    }}
    .paper-section {{
      margin-bottom: 48px;
      padding-top: 40px;
      border-top: 1px solid rgba(0,0,0,0.06);
    }}
    .paper-section:first-of-type {{ border-top: none; padding-top: 0; }}
    .paper-section h2 {{
      font-family: var(--sans);
      font-size: 18px;
      font-weight: 600;
      color: var(--text);
      margin-bottom: 20px;
    }}
    .paper-section h3 {{
      font-family: var(--sans);
      font-size: 16px;
      font-weight: 600;
      color: var(--text);
      margin: 24px 0 12px 0;
    }}
    .paper-section h4 {{
      font-family: var(--sans);
      font-size: 15px;
      font-weight: 600;
      color: var(--text);
      margin: 20px 0 10px 0;
    }}
    .paper-section p {{
      color: #1f2937;
      margin-bottom: 14px;
      font-size: 17px;
      line-height: 1.8;
    }}
    .paper-section ul {{
      padding-left: 24px;
      list-style: disc;
      margin-bottom: 16px;
    }}
    .paper-section ul li {{
      padding: 4px 0;
      color: #1f2937;
    }}
    .paper-section ol {{
      padding-left: 24px;
      list-style: decimal;
      margin-bottom: 16px;
    }}
    .paper-section ol li {{
      padding: 4px 0;
      color: #1f2937;
    }}
    .paper-section strong {{ color: var(--text); font-weight: 600; }}
    .paper-section em {{ color: #374151; font-style: italic; }}
    .paper-section code {{
      background: rgba(194,65,12,0.06);
      border: 1px solid rgba(194,65,12,0.12);
      border-radius: 4px;
      padding: 1px 6px;
      font-family: var(--mono);
      font-size: 13px;
      color: #c2410c;
    }}
    .math-block {{
      overflow-x: auto;
      margin: 24px 0;
      padding: 20px 24px;
      background: #f8f7f5;
      border: 1px solid var(--border);
      border-radius: 8px;
      text-align: center;
    }}
    blockquote {{
      border-left: 3px solid var(--border);
      background: transparent;
      padding: 16px 20px;
      margin: 20px 0;
      border-radius: 0;
    }}
    blockquote p {{
      color: #6b7280 !important;
      font-style: italic;
      margin-bottom: 4px !important;
    }}
    .code-window {{
      margin: 20px 0;
      border-radius: 12px;
      overflow: hidden;
      background: #1e1e1e;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }}
    .code-chrome {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 16px;
      background: #2d2d2d;
    }}
    .code-dots {{
      display: flex;
      gap: 6px;
    }}
    .code-dots span {{
      width: 12px; height: 12px;
      border-radius: 50%;
    }}
    .code-dots span:nth-child(1) {{ background: #ff5f57; }}
    .code-dots span:nth-child(2) {{ background: #febc2e; }}
    .code-dots span:nth-child(3) {{ background: #28c840; }}
    .code-lang {{
      font-family: var(--mono);
      font-size: 12px;
      color: #999;
      margin-left: auto;
    }}
    pre {{
      background: #1e1e1e !important;
      border: none;
      border-radius: 0;
      padding: 20px 24px;
      overflow-x: auto;
      margin: 0;
    }}
    pre code {{
      background: transparent !important;
      border: none !important;
      padding: 0 !important;
      font-size: 12.5px !important;
      line-height: 1.65 !important;
      color: #d4d4d4 !important;
    }}
    .paper-diagram {{
      margin: 32px 0;
      border: 1px solid var(--border);
      border-radius: 16px;
      overflow: hidden;
      background: #ffffff;
      box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }}
    .paper-diagram img {{ width: 100%; display: block; }}
    .paper-diagram figcaption {{
      padding: 12px 20px;
      font-size: 13px;
      font-family: var(--sans);
      font-weight: 500;
      color: var(--text);
      border-top: 1px solid var(--border);
      background: var(--surface);
    }}
    .paper-table {{
      margin: 24px 0; border: 1px solid var(--border);
      border-radius: 10px; overflow: hidden;
    }}
    .table-caption {{
      padding: 10px 16px; font: 600 14px var(--sans);
      background: var(--surface); border-bottom: 1px solid var(--border);
    }}
    .table-scroll {{ overflow-x: auto; padding: 0 4px; }}
    .paper-table table {{
      width: 100%; border-collapse: collapse; font-size: 14px;
    }}
    .paper-table th {{
      background: var(--surface); font-weight: 600; text-align: left;
      padding: 8px 12px; border-bottom: 2px solid var(--border);
    }}
    .paper-table td {{
      padding: 8px 12px; border-bottom: 1px solid var(--border);
    }}
    .paper-table tr:nth-child(even) td {{ background: rgba(0,0,0,.02); }}
    .notebook-cta {{
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 20px;
      background: linear-gradient(135deg, #eff6ff 0%, #f0fdf4 100%);
      border: 1px solid #bfdbfe;
      border-radius: 16px;
      padding: 24px 28px;
      margin: 28px 0;
    }}
    .nb-icon {{ font-size: 36px; flex-shrink: 0; }}
    .nb-text {{ flex: 1; min-width: 200px; }}
    .nb-text strong {{ display: block; font-size: 15px; color: var(--text); margin-bottom: 4px; }}
    .nb-text span {{ font-size: 13px; color: var(--muted); }}
    .nb-actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .btn-primary {{
      background: var(--accent);
      color: #fff;
      font-family: var(--sans);
      font-size: 13px;
      font-weight: 600;
      padding: 10px 20px;
      border-radius: 8px;
      text-decoration: none;
      white-space: nowrap;
      transition: opacity 0.15s;
    }}
    .btn-primary:hover {{ opacity: 0.85; }}
    .btn-secondary {{
      background: var(--surface2);
      color: var(--text);
      border: 1px solid var(--border);
      font-size: 13px;
      padding: 10px 20px;
      border-radius: 8px;
      text-decoration: none;
      white-space: nowrap;
      transition: border-color 0.15s;
    }}
    .btn-secondary:hover {{ border-color: var(--accent); }}
    .btn-colab {{
      background: #f9ab00;
      color: #1a1a1a;
      font-family: var(--sans);
      font-size: 13px;
      font-weight: 600;
      padding: 10px 20px;
      border: none;
      border-radius: 8px;
      text-decoration: none;
      white-space: nowrap;
      display: inline-flex;
      align-items: center;
      cursor: pointer;
      transition: opacity 0.15s;
    }}
    .btn-colab:hover {{ opacity: 0.85; }}
    .reading-progress {{
      position: fixed;
      top: 0; left: 0;
      height: 3px;
      background: var(--accent);
      width: 0%;
      z-index: 1000;
      transition: width 0.1s linear;
    }}
    .export-section {{
      padding-bottom: 60px;
    }}
    .export-bar {{
      display: flex;
      align-items: center;
      gap: 10px;
      position: relative;
    }}
    .export-bar button {{
      background: var(--surface);
      color: var(--text);
      border: 1px solid var(--border);
      font-family: var(--mono);
      font-size: 12px;
      padding: 10px 18px;
      border-radius: 8px;
      cursor: pointer;
      white-space: nowrap;
      transition: all 0.15s;
    }}
    .export-bar button:hover {{
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
    }}
    .export-bar button.substack-btn {{ background: #FF6719; color: #fff; border-color: #FF6719; }}
    .export-bar button.substack-btn:hover {{ background: #e85d16; border-color: #e85d16; }}
    .export-bar .export-toast {{
      background: var(--text);
      color: #fff;
      font-family: var(--mono);
      font-size: 11px;
      padding: 6px 12px;
      border-radius: 6px;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.2s;
    }}
    .export-bar .export-toast.show {{ opacity: 1; }}
    @media (max-width: 900px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .sidebar {{ display: none; }}
      .main {{ padding: 40px 24px; }}
      .notebook-cta {{ flex-direction: column; align-items: flex-start; }}
      .export-bar {{ flex-wrap: wrap; }}
    }}
  </style>
</head>
<body data-session="{{SESSION_ID}}">
  <div class="reading-progress" id="readingProgress"></div>
  <div class="layout">
    <aside class="sidebar">
      <div class="sidebar-brand">
        <div class="logo-chip">PD</div>
        <span>PaperDigest</span>
      </div>
      <div class="toc-label">Contents</div>
      <ul>{toc_html}</ul>
    </aside>

    <main class="main">
      <header class="paper-header">
        <div class="paper-badge">PaperDigest</div>
        <h1>{paper_title}</h1>
        <div class="paper-meta-line">{paper_meta_html}</div>
        <div class="paper-meta">
          <span class="reading-time" id="readingTime">~{reading_time_min} min read</span>
        </div>
      </header>

      {sections_html}
    </main>
  </div>

  <script>
    hljs.highlightAll();

    // Highlight active TOC link on scroll
    const sections = document.querySelectorAll('.paper-section[id]');
    const links    = document.querySelectorAll('.sidebar a');

    const observer = new IntersectionObserver(entries => {{
      entries.forEach(e => {{
        if (e.isIntersecting) {{
          links.forEach(l => {{ l.style.color = ''; l.style.borderLeftColor = ''; }});
          const active = document.querySelector(`.sidebar a[href="#${{e.target.id}}"]`);
          if (active) {{
            active.style.color = 'var(--accent)';
            active.style.borderLeftColor = 'var(--accent)';
          }}
        }}
      }});
    }}, {{ rootMargin: '-20% 0px -60% 0px' }});

    sections.forEach(s => observer.observe(s));

    // Reading progress bar + dynamic reading time
    const totalMin = {reading_time_min};
    window.addEventListener('scroll', function() {{
      const scrollTop = window.scrollY;
      const docHeight = document.documentElement.scrollHeight - window.innerHeight;
      const pct = docHeight > 0 ? (scrollTop / docHeight) * 100 : 0;
      document.getElementById('readingProgress').style.width = Math.min(pct, 100) + '%';
      const rtEl = document.getElementById('readingTime');
      if (pct >= 95) {{
        rtEl.textContent = 'Finished reading';
      }} else {{
        const left = Math.max(1, Math.ceil(totalMin * (1 - pct / 100)));
        rtEl.textContent = '~' + left + ' min left';
      }}
    }});

    // Render LaTeX with KaTeX
    document.addEventListener("DOMContentLoaded", function() {{
      if (typeof renderMathInElement !== "undefined") {{
        renderMathInElement(document.body, {{
          delimiters: [
            {{left: "$$", right: "$$", display: true}},
            {{left: "$", right: "$", display: false}},
            {{left: "\\\\(", right: "\\\\)", display: false}},
            {{left: "\\\\[", right: "\\\\]", display: true}},
          ],
          throwOnError: false,
        }});
      }} else {{
        console.warn("KaTeX auto-render not loaded — math will display as raw LaTeX");
      }}
    }});
  </script>

  <script>
    const _sid = document.body.dataset.session;

    function _showToast(msg, duration) {{
      const t = document.getElementById('exportToast');
      t.textContent = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), duration || 2000);
    }}

    function openInColab() {{
      const nbUrl = window.location.origin + '/download/' + _sid + '/paper_notebook.ipynb';
      const host = window.location.hostname;
      const isLocal = (host === 'localhost' || host === '127.0.0.1' || host === '0.0.0.0');
      if (!isLocal) {{
        // Deployed server — Colab can fetch the notebook directly
        const colabUrl = 'https://colab.research.google.com/url/' + encodeURIComponent(nbUrl);
        window.open(colabUrl, '_blank');
      }} else {{
        // Localhost — Colab can't reach us, so download + open Colab upload
        window.open('https://colab.research.google.com/', '_blank');
        const a = document.createElement('a');
        a.href = nbUrl;
        a.download = 'paper_notebook.ipynb';
        document.body.appendChild(a);
        a.click();
        a.remove();
        _showToast('Notebook downloaded! In Colab → File → Upload notebook', 6000);
      }}
    }}

    function exportDownloadMd() {{
      const a = document.createElement('a');
      a.href = '/markdown/' + _sid;
      a.download = 'digest.md';
      document.body.appendChild(a);
      a.click();
      a.remove();
    }}

    function exportDownloadHtml() {{
      const html = document.documentElement.outerHTML;
      const blob = new Blob([html], {{ type: 'text/html' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'digest.html';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }}

    async function exportCopySubstack() {{
      try {{
        const resp = await fetch('/substack-html/' + _sid);
        if (!resp.ok) throw new Error('Failed to fetch Substack HTML');
        const html = await resp.text();
        const blob = new Blob([html], {{ type: 'text/html' }});
        await navigator.clipboard.write([
          new ClipboardItem({{ 'text/html': blob }})
        ]);
        _showToast('Copied! Paste into Substack editor');
      }} catch (e) {{
        _showToast('Copy failed: ' + e.message);
      }}
    }}
  </script>
</body>
</html>"""

    return html


# ─────────────────────────────────────────────────────────────────────────────
# Title extractor
# ─────────────────────────────────────────────────────────────────────────────

def extract_title(paper_markdown: str) -> str:
    """Pull the paper title from the first # heading, or fall back to first title-like lines."""
    # First: try # heading
    for line in paper_markdown.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("##"):
            return stripped[2:].strip()

    # Fallback: first non-empty lines that look like a title
    title_parts = []
    for line in paper_markdown.split("\n"):
        stripped = line.strip()
        if not stripped:
            if title_parts:
                break  # blank line after title lines = done
            continue
        # Skip metadata-like lines
        if any(stripped.startswith(c) for c in ["[", ">", "|", "http", "!"]):
            break
        if len(stripped) > 200:  # too long for a title
            break
        title_parts.append(stripped)
        if len(title_parts) >= 2:  # max 2 lines for title
            break

    return " ".join(title_parts) if title_parts else "Research Paper"


def extract_paper_metadata(paper_markdown: str) -> dict:
    """Extract authors, year, and arxiv URL from the paper markdown header.

    Regex-based — no LLM call. Parses the lines between the title and the
    first section heading / abstract. Returns {"authors": [...], "year": str, "paper_url": str}.
    """
    lines = paper_markdown.split("\n")
    authors: list[str] = []
    year = ""
    paper_url = ""

    # ── Find the header region: after title, before first heading/abstract ──
    title_end = 0
    for i, line in enumerate(lines[:20]):  # titles are always in first 20 lines
        s = line.strip()
        if s.startswith("# ") and not s.startswith("##"):
            title_end = i + 1
            break

    # If no # heading, title is the first non-empty text block
    if title_end == 0:
        in_title = False
        for i, line in enumerate(lines):
            s = line.strip()
            if not s:
                if in_title:
                    title_end = i
                    break
                continue
            # Skip arxiv/copyright preamble lines
            if s.startswith("arXiv:") or "permission" in s.lower() or "copyright" in s.lower():
                continue
            in_title = True
        if title_end == 0 and in_title:
            title_end = i + 1

    # Header ends at first ## heading, or "Abstract" (with or without ##)
    header_end = min(len(lines), title_end + 30)  # cap search at 30 lines after title
    for i in range(title_end, header_end):
        s = lines[i].strip()
        if s.startswith("## "):
            header_end = i
            break
        if s.lower() in ("abstract", "# abstract"):
            header_end = i
            break

    header_lines = [lines[i].strip() for i in range(title_end, header_end)]

    # ── Extract arxiv URL / ID from entire pre-header + header region ──
    search_end = max(header_end + 5, min(len(lines), 100))
    for i in range(min(len(lines), search_end)):
        s = lines[i].strip()
        url_match = re.search(r'(https?://arxiv\.org/(?:abs|pdf)/[\w.]+)', s)
        if url_match:
            paper_url = url_match.group(1)
            break
        arxiv_match = re.search(r'arXiv\s*:\s*(\d{4}\.\d{4,5})', s, re.IGNORECASE)
        if arxiv_match:
            paper_url = f"https://arxiv.org/abs/{arxiv_match.group(1)}"
            break

    # ── Extract year ──
    # Pass 1: look for year in header region
    for line in lines[:header_end]:
        year_match = re.search(r'\b(20[12]\d)\b', line)
        if year_match:
            year = year_match.group(1)
            break

    # Pass 2: if not found in header, search first 80 lines for conference+year
    # or arXiv IDs (e.g. "CVPR 2023", "NeurIPS 2024", "arXiv:2301.08243")
    if not year:
        _conf_re = re.compile(
            r'(?:CVPR|ICCV|ECCV|NeurIPS|ICML|ICLR|AAAI|IJCAI|ACL|EMNLP|'
            r'NAACL|SIGIR|KDD|WWW|ICRA|IROS|CoRL)\s*(20[12]\d)', re.IGNORECASE
        )
        _arxiv_id_re = re.compile(r'arXiv[:\s]*(\d{2})(\d{2})\.\d{4,5}')
        for line in lines[:80]:
            cm = _conf_re.search(line)
            if cm:
                year = cm.group(1)
                break
            am = _arxiv_id_re.search(line)
            if am:
                year = f"20{am.group(1)}"
                break

    # ── Extract authors ──
    _email_re = re.compile(r'[\w.+-]+@[\w.-]+\.\w+')
    _affil_keywords = {"university", "institute", "lab", "research", "department",
                       "school", "college", "center", "centre", "meta ai",
                       "google", "microsoft", "amazon", "facebook", "deepmind",
                       "openai", "samsung", "nvidia", "mila", "mit", "stanford",
                       "berkeley", "carnegie"}

    def _is_name(s: str) -> bool:
        """Check if a string looks like a person name (2-4 words, capitalized)."""
        words = s.split()
        if not (1 <= len(words) <= 5):
            return False
        # Names shouldn't contain parentheses, underscores, equals, digits
        if re.search(r'[()_=\d{}\[\]]', s):
            return False
        lower_ok = {"de", "von", "van", "di", "el", "al", "la", "del", "da"}
        return all(
            w[0].isupper() or w.lower() in lower_ok
            for w in words if w
        )

    def _split_author_line(line: str) -> list[str]:
        """Extract author names from a line, handling LaTeX superscripts as separators."""
        # Use LaTeX superscripts ($^{1,2}$) as name separators first
        if '$^' in line:
            parts = re.split(r'\$\^?\{?[^}$]*\}?\$', line)
            names = []
            for part in parts:
                part = re.sub(r'[*†‡§¶∗]+', '', part).strip().strip(',').strip()
                if part and _is_name(part):
                    names.append(part)
            if names:
                return names

        # Fallback: strip LaTeX, split on commas / multiple spaces / "and"
        cleaned = re.sub(r'\$\^?\{?[^}$]*\}?\$', '', line)
        cleaned = re.sub(r'[*†‡§¶∗]+', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        if not cleaned or len(cleaned) < 3:
            return []
        if sum(1 for c in cleaned if c.isalpha()) < 5:
            return []

        parts = re.split(r'\s{2,}|,\s*(?=[A-Z])|\band\b', cleaned)
        return [p.strip().strip(',').strip() for p in parts if p.strip() and _is_name(p.strip())]

    def _is_author_line(line: str) -> bool:
        """Check if a line should be skipped (email, affiliation, etc.)."""
        if not line:
            return False
        lower = line.lower()
        if _email_re.search(line):
            return False
        if any(kw in lower for kw in _affil_keywords):
            return False
        if line.startswith(("[", ">", "!", "http", "---", "**Figure")):
            return False
        if re.match(r'^\$\^\d', line):  # "$^1$Meta AI (FAIR)" — affiliation
            return False
        return True

    # Pass 1: find author lines in the header
    for i, line in enumerate(header_lines):
        if not _is_author_line(line):
            continue

        names = _split_author_line(line)
        if names:
            authors.extend(names)
            # Check if next non-empty lines are also author lines (multi-line block)
            for j in range(i + 1, len(header_lines)):
                next_line = header_lines[j]
                if not next_line:
                    break
                if not _is_author_line(next_line):
                    break
                more_names = _split_author_line(next_line)
                if more_names:
                    authors.extend(more_names)
                else:
                    break
            break

    if len(authors) > 8:
        authors = authors[:5]

    return {"authors": authors, "year": year, "paper_url": paper_url}