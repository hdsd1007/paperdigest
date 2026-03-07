"""Automated Substack publishing via the unofficial python-substack API.

Uploads diagrams to Substack's CDN, converts math to Unicode, and creates
a draft (or published) post from the digest summary markdown.

Requires: pip install python-substack
Config:   SUBSTACK_COOKIE and SUBSTACK_URL in .env
"""

import logging
import os
import re
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
    log.addHandler(_h)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def is_configured() -> bool:
    """Check if Substack credentials are present in environment."""
    return bool(os.getenv("SUBSTACK_COOKIE")) and bool(os.getenv("SUBSTACK_URL"))


def _get_api():
    """Create an authenticated Substack API client.

    Returns a substack.Api instance. Raises SubstackAuthError on failure.
    """
    try:
        from substack import Api
    except ImportError:
        raise SubstackAuthError(
            "python-substack not installed. Run: pip install python-substack"
        )

    cookie = os.getenv("SUBSTACK_COOKIE", "")
    pub_url = os.getenv("SUBSTACK_URL", "")
    if not cookie or not pub_url:
        raise SubstackAuthError(
            "SUBSTACK_COOKIE and SUBSTACK_URL must be set in .env"
        )

    # The library expects "key=value" cookie format.
    # If user provided just the value (no "="), prepend the cookie name.
    cookie = cookie.strip()
    if "=" not in cookie:
        cookie = f"substack.sid={cookie}"

    log.info("Substack auth: pub_url=%s, cookie_prefix=%s...", pub_url, cookie[:30])

    # Validate publication URL format
    if "substack.com" not in pub_url:
        raise SubstackAuthError(
            f"SUBSTACK_URL must be like https://yourname.substack.com, got: {pub_url}"
        )

    try:
        log.info("Creating Substack API client...")
        api = Api(
            cookies_string=cookie,
            publication_url=pub_url,
        )
        log.info("API client created, fetching user ID...")
        user_id = api.get_user_id()
        log.info("Authenticated as user_id=%s", user_id)
        return api
    except Exception as exc:
        log.exception("Substack authentication failed")
        raise SubstackAuthError(
            f"Substack authentication failed (cookie may have expired): {exc}"
        )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SubstackAuthError(Exception):
    pass


class SubstackPublishError(Exception):
    pass


# ---------------------------------------------------------------------------
# Markdown preprocessing helpers
# ---------------------------------------------------------------------------

def _strip_post_equation_blocks(text: str) -> str:
    """Remove variable-interpretation paragraphs that follow display math."""
    lines = text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        result.append(lines[i])
        if "$$" in lines[i]:
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                first_line = lines[j].strip()
                openers = (
                    "here,", "where ", "in this equation",
                    "in the above", "in this formula",
                    "in the equation", "here $", "where $",
                )
                if any(first_line.lower().startswith(op) for op in openers):
                    para_lines = []
                    k = j
                    while k < len(lines) and lines[k].strip() != "" and not lines[k].strip().startswith("#"):
                        para_lines.append(lines[k])
                        k += 1
                    para = " ".join(para_lines)
                    inline_count = len(re.findall(r"(?<!\$)\$(?!\$).+?(?<!\$)\$(?!\$)", para))
                    if inline_count >= 3:
                        i = k
                        continue
        i += 1
    return "\n".join(result)


def _strip_backtick_wrapped_math(text: str) -> str:
    """Strip backticks wrapping $...$ or $$...$$ math expressions."""
    text = re.sub(r'`(\$\$.+?\$\$)`', r'\1', text)
    text = re.sub(r'`(\$(?!\$).+?\$)`', r'\1', text)
    return text


def _strip_raw_tables(text: str) -> str:
    """Remove raw markdown pipe-tables (duplicates of [TABLE: N] markers)."""
    lines = text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("|"):
            block_start = i
            while i < len(lines) and lines[i].strip().startswith("|"):
                i += 1
            block = lines[block_start:i]
            has_sep = any(re.match(r"^\|[\s\-:|]+\|$", ln.strip()) for ln in block)
            # Strip standard tables (with separator) AND partial tables (2+ pipe lines)
            if (has_sep and len(block) >= 3) or len(block) >= 2:
                result.append("")
            else:
                # Single pipe line — strip if it looks like a table row (3+ pipes)
                line = block[0].strip()
                if line.count("|") >= 3:
                    result.append("")
                else:
                    result.extend(block)
        else:
            result.append(lines[i])
            i += 1
    return "\n".join(result)


def _strip_garbled_citations(text: str) -> str:
    """Remove garbled citation/reference fragments that leaked through preprocessing."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            bracket_count = stripped.count("[") + stripped.count("]")
            slash_count = stripped.count("/")
            special_ratio = (bracket_count + slash_count) / max(len(stripped), 1)
            if special_ratio > 0.15 and bracket_count >= 4:
                cleaned.append("")
            else:
                cleaned.append(line)
        else:
            cleaned.append(line)
    return "\n".join(cleaned)


def _strip_dense_math_paragraphs(text: str) -> str:
    """Remove paragraphs overwhelmingly made of inline-math definitions.

    Paragraphs with 5+ inline $...$ expressions and high math density are
    almost always variable-interpretation blocks that become garbled after
    math conversion (e.g., 'where $X$ is the..., $Y$ denotes...').
    """
    paragraphs = re.split(r"\n\n+", text)
    cleaned = []
    for para in paragraphs:
        stripped = para.strip()
        if not stripped:
            cleaned.append(para)
            continue
        # Skip headings, list items, diagram/table markers
        if stripped.startswith("#") or stripped.startswith("-") or stripped.startswith("["):
            cleaned.append(para)
            continue
        inline_count = len(re.findall(r"(?<!\$)\$(?!\$).+?(?<!\$)\$(?!\$)", stripped))
        word_count = len(stripped.split())
        if inline_count >= 5 and word_count > 0:
            math_density = inline_count / word_count
            if math_density > 0.15:
                continue  # drop this paragraph
        cleaned.append(para)
    return "\n\n".join(cleaned)


def _render_and_upload_math(latex_inner: str, api) -> str | None:
    """Render LaTeX to PNG, upload to Substack CDN, return URL or None."""
    try:
        from latex_renderer import render_latex_to_png_file
        png_path = render_latex_to_png_file(latex_inner)

        # Retry with aggressive simplification if first attempt fails
        if not png_path:
            simplified = latex_inner
            simplified = re.sub(r"\\(underbrace|overbrace|overset|underset|stackrel)\{[^}]*\}\{([^}]*)\}", r"\2", simplified)
            simplified = re.sub(r"\\begin\{[^}]*\}|\\end\{[^}]*\}", "", simplified)
            simplified = re.sub(r"\\[a-z]+space", " ", simplified)
            simplified = simplified.replace(r"\|", "|")
            if simplified != latex_inner:
                png_path = render_latex_to_png_file(simplified)

        if not png_path:
            return None
        try:
            time.sleep(0.3)
            url = _upload_image(api, png_path)
            return url
        finally:
            try:
                os.unlink(png_path)
            except OSError:
                pass
    except Exception as exc:
        log.warning("Math render+upload failed: %s", exc)
        return None


def _best_effort_latex_cleanup(latex: str) -> str:
    """Best-effort cleanup of LaTeX for readable plain text."""
    from unicode_math import _GREEK, _SUBSCRIPTS, _SUPERSCRIPTS

    text = latex
    # \frac{a}{b} -> (a)/(b)
    text = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1)/(\2)", text)
    # Strip formatting commands
    for cmd in [r"\left", r"\right", r"\displaystyle", r"\bigl", r"\bigr"]:
        text = text.replace(cmd, "")
    # \text{...} / \mathrm{...} etc -> content
    text = re.sub(r"\\(?:text|mathrm|mathbf|mathit|operatorname|boldsymbol|bm)\{([^}]*)\}", r"\1", text)
    # Diacriticals: \hat{X} -> X̂, \bar{X} -> X̄, \tilde{X} -> X̃
    # Use ([^}]*) to handle multi-char content like \hat{xy}
    text = re.sub(r"\\hat\{([^}]*)\}", r"\1\u0302", text)
    text = re.sub(r"\\bar\{([^}]*)\}", r"\1\u0304", text)
    text = re.sub(r"\\tilde\{([^}]*)\}", r"\1\u0303", text)
    text = re.sub(r"\\vec\{([^}]*)\}", r"\1\u20D7", text)
    text = re.sub(r"\\dot\{([^}]*)\}", r"\1\u0307", text)
    text = re.sub(r"\\ddot\{([^}]*)\}", r"\1\u0308", text)
    # No-brace forms: \hat x -> x̂
    text = re.sub(r"\\hat\s+([A-Za-z])", r"\1\u0302", text)
    text = re.sub(r"\\bar\s+([A-Za-z])", r"\1\u0304", text)
    text = re.sub(r"\\tilde\s+([A-Za-z])", r"\1\u0303", text)
    # Greek letters (use the full unicode_math mapping)
    for cmd in sorted(_GREEK.keys(), key=len, reverse=True):
        text = text.replace(cmd, _GREEK[cmd])
    # Common operator/symbol commands
    _ops = {
        r"\sum": "∑", r"\prod": "∏", r"\log": "log", r"\exp": "exp",
        r"\min": "min", r"\max": "max", r"\sin": "sin", r"\cos": "cos",
        r"\cdot": "·", r"\times": "×", r"\in": "∈", r"\to": "→",
        r"\leq": "≤", r"\geq": "≥", r"\neq": "≠", r"\approx": "≈",
        r"\infty": "∞", r"\partial": "∂", r"\nabla": "∇",
        r"\forall": "∀", r"\exists": "∃", r"\sim": "∼",
        r"\rightarrow": "→", r"\leftarrow": "←", r"\Rightarrow": "⇒",
        r"\ldots": "…", r"\cdots": "⋯", r"\dots": "…",
        r"\pm": "±", r"\mp": "∓",
    }
    for cmd, repl in _ops.items():
        text = text.replace(cmd, repl)
    # Subscripts: _{...} or _X -> Unicode subscript where possible
    def _sub_replace(m):
        content = m.group(1)
        return "".join(_SUBSCRIPTS.get(ch, ch) for ch in content)
    text = re.sub(r"_\{([^}]*)\}", _sub_replace, text)
    text = re.sub(r"_([A-Za-z0-9])", _sub_replace, text)
    # Superscripts: ^{...} or ^X -> Unicode superscript where possible
    def _sup_replace(m):
        content = m.group(1)
        return "".join(_SUPERSCRIPTS.get(ch, ch) for ch in content)
    text = re.sub(r"\^\{([^}]*)\}", _sup_replace, text)
    text = re.sub(r"\^([A-Za-z0-9])", _sup_replace, text)
    # Handle \| (norm notation) -> ‖
    text = text.replace(r"\|", "‖")
    # Strip remaining backslash commands
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _convert_display_math(text: str, api=None) -> str:
    """Convert $$...$$ display math to Unicode bold, CDN image, or text fallback."""
    from unicode_math import latex_to_unicode

    def _replace(m):
        raw = m.group(0)
        unicode_text = latex_to_unicode(raw)
        if unicode_text is not None:
            return f"\n\n**{unicode_text}**\n\n"

        # Complex math — try rendering as PNG and uploading to CDN
        inner = raw.strip().strip("$").strip()
        if api is not None:
            url = _render_and_upload_math(inner, api)
            if url:
                return f"\n\n![equation]({url})\n\n"

        # Final fallback: best-effort text cleanup
        clean = _best_effort_latex_cleanup(inner)
        return f"\n\n**{clean}**\n\n"

    return re.sub(r"\$\$(.*?)\$\$", _replace, text, flags=re.DOTALL)


def _convert_inline_math(text: str, api=None) -> str:
    """Convert $...$ inline math to Unicode, CDN image, or text fallback."""
    from unicode_math import latex_to_unicode

    def _replace(m):
        raw = m.group(0)
        unicode_text = latex_to_unicode(raw)
        if unicode_text is not None:
            return unicode_text
        # Try rendering as PNG and uploading to CDN
        inner = raw.strip().strip("$").strip()
        if api is not None:
            url = _render_and_upload_math(inner, api)
            if url:
                return f"![{_best_effort_latex_cleanup(inner)}]({url})"
        clean = _best_effort_latex_cleanup(inner)
        return clean

    return re.sub(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", _replace, text)


def _protect_code_blocks_substack(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Extract fenced code blocks and replace with placeholders.

    Must run BEFORE math conversion so $...$ inside code blocks aren't processed.
    """
    blocks = []

    def _replace(m):
        lang = m.group(1) or ""
        code = m.group(2)
        blocks.append((lang, code))
        return f"\n\n<!--SUBSTACK_CODE_{len(blocks)-1}-->\n\n"

    text = re.sub(r"```([\w-]*)\n(.*?)```", _replace, text, flags=re.DOTALL)
    return text, blocks


def _clean_code_block_content(code: str) -> str:
    """Strip $...$ LaTeX delimiters and \\_ escaping from code block content.

    The LLM sometimes wraps Python variable names in $...$ and uses \\_
    for underscores inside code blocks.
    """
    # Strip $...$ wrapping around variable names
    code = re.sub(r'\$([^$\n]+?)\$', r'\1', code)
    # Replace \_ with plain underscore
    code = code.replace(r'\_', '_')
    # Strip remaining LaTeX escaping in code context
    code = code.replace(r'\{', '{').replace(r'\}', '}')
    return code


def _restore_code_blocks_substack(text: str, blocks: list[tuple[str, str]], api) -> str:
    """Restore protected code blocks as native fenced code blocks.

    Substack's from_markdown() natively supports fenced code blocks,
    creating proper codeBlock elements with language detection.
    """
    for i, (lang, code) in enumerate(blocks):
        placeholder = f"<!--SUBSTACK_CODE_{i}-->"
        clean_code = _clean_code_block_content(code)
        display_lang = lang or "python"
        replacement = f"\n\n```{display_lang}\n{clean_code}```\n\n"
        text = text.replace(placeholder, replacement)
    return text


def _replace_tables(text: str, important_tables: list[dict] | None) -> str:
    """Replace [TABLE: N] markers with the table markdown as a fenced code block."""
    if not important_tables:
        return re.sub(r"\[TABLE:\s*\d+\]", "", text)

    def _replace(m):
        full = m.group(0)
        num_match = re.search(r"\d+", full)
        if not num_match:
            return ""
        idx = int(num_match.group()) - 1  # 1-indexed
        if idx < 0 or idx >= len(important_tables):
            return ""
        tbl = important_tables[idx]
        caption = tbl.get("caption", f"Table {idx + 1}")
        md = tbl.get("markdown", "")
        if not md.strip():
            return ""
        # Render as a fenced code block with caption heading
        return f"\n\n**{caption}**\n\n```\n{md.strip()}\n```\n\n"

    return re.sub(r"\[TABLE:\s*\d+\]", _replace, text)


def _upload_image(api, local_path: str) -> str | None:
    """Upload a single image to Substack CDN. Returns URL or None on failure."""
    try:
        if not os.path.exists(local_path):
            log.warning("Image file does not exist: %s", local_path)
            return None
        file_size = os.path.getsize(local_path)
        if file_size == 0:
            log.warning("Image file is empty: %s", local_path)
            return None
        log.info("Uploading %s (%d bytes)...", Path(local_path).name, file_size)
        result = api.get_image(local_path)
        url = result.get("url") if isinstance(result, dict) else None
        if url:
            log.info("Uploaded %s -> %s", Path(local_path).name, url)
        else:
            log.warning("Upload returned no URL for %s: %r", Path(local_path).name, result)
        return url
    except Exception as exc:
        log.warning("Failed to upload %s: %s: %s", local_path, type(exc).__name__, exc)
        return None


def _replace_diagrams(
    text: str,
    diagram_dir: str,
    diagram_captions: list[str],
    api,
) -> tuple[str, int, int, list[dict]]:
    """Replace [DIAGRAM: desc] markers with uploaded CDN image references.

    Returns (processed_text, uploaded_count, failed_count, failed_details).
    """
    diagram_path = Path(diagram_dir)
    if diagram_path.exists():
        # Filter out table chart PNGs — they share the directory but aren't diagrams
        png_files = sorted(
            f for f in diagram_path.glob("*.png")
            if not f.name.startswith("table_chart_")
        )
    else:
        png_files = []

    markers = list(re.finditer(r"\[DIAGRAM:\s*(.+?)\]", text))
    if not markers:
        return text, 0, 0, []

    uploaded = 0
    failed = 0
    failed_details = []

    for i, m in enumerate(reversed(markers)):
        # Reverse order to preserve string indices
        idx = len(markers) - 1 - i
        desc = m.group(1).strip()
        caption = diagram_captions[idx] if idx < len(diagram_captions) else desc

        if idx < len(png_files):
            # Rate limit: small sleep between uploads
            if idx > 0:
                time.sleep(0.5)
            url = _upload_image(api, str(png_files[idx]))
            if url:
                # Sanitize caption for italic rendering (strip * that would break markdown)
                safe_caption = caption.replace("*", "")
                replacement = f"\n\n![{safe_caption}]({url})\n\n*{safe_caption}*\n\n"
                uploaded += 1
            else:
                replacement = f"\n\n*[Diagram not available: {caption}]*\n\n"
                failed += 1
                failed_details.append({
                    "diagram_index": idx + 1,
                    "caption": caption,
                    "file": png_files[idx].name,
                    "reason": "Upload failed (API returned no URL)",
                })
        else:
            replacement = f"\n\n*[Diagram not available: {caption}]*\n\n"
            failed += 1
            failed_details.append({
                "diagram_index": idx + 1,
                "caption": caption,
                "file": None,
                "reason": f"PNG file not found ({len(png_files)} files available)",
            })

        text = text[:m.start()] + replacement + text[m.end():]

    return text, uploaded, failed, failed_details


# ---------------------------------------------------------------------------
# Main preprocessing pipeline
# ---------------------------------------------------------------------------

def prepare_markdown_for_substack(
    summary_md: str,
    diagram_dir: str,
    diagram_captions: list[str],
    important_tables: list[dict] | None,
    api,
    notebook_url: str = "",
    authors: list[str] | None = None,
    year: str = "",
    paper_url: str = "",
    citation_count: int | None = None,
) -> tuple[str, int, int, list[dict]]:
    """Full preprocessing: summary markdown -> Substack-ready markdown.

    Returns (processed_markdown, images_uploaded, images_failed, failed_details).
    """
    # Prepend metadata line (authors, year, citations, link)
    meta_parts = []
    if authors:
        meta_parts.append(", ".join(authors))
    if year:
        meta_parts.append(year)
    if citation_count is not None:
        meta_parts.append(f"{citation_count:,} citations")
    if paper_url:
        meta_parts.append(f"[Paper]({paper_url})")
    meta_line = ""
    if meta_parts:
        meta_line = "*" + " · ".join(meta_parts) + "*\n\n"

    text = meta_line + summary_md

    # 1. Clean up LLM artifacts
    text = _strip_post_equation_blocks(text)
    text = _strip_dense_math_paragraphs(text)
    text = _strip_backtick_wrapped_math(text)

    # 2. PROTECT code blocks before math processing
    #    Prevents $...$ inside code blocks from being mangled by math conversion
    text, code_blocks = _protect_code_blocks_substack(text)

    # 3. Convert math to Unicode (display first to avoid $$ matching as $)
    #    Complex display math is rendered as PNG and uploaded to CDN
    text = _convert_display_math(text, api=api)
    text = _convert_inline_math(text, api=api)

    # 4. Restore code blocks as native fenced code blocks
    text = _restore_code_blocks_substack(text, code_blocks, api)

    # 5. Inline tables
    text = _replace_tables(text, important_tables)

    # 6. Upload diagrams and replace markers
    text, uploaded, failed, failed_details = _replace_diagrams(
        text, diagram_dir, diagram_captions, api
    )

    # 7. Strip any leftover raw pipe-tables
    text = _strip_raw_tables(text)

    # 8. Strip garbled citation fragments
    text = _strip_garbled_citations(text)

    # 9. Clean leftover LaTeX commands (safety net)
    text = re.sub(r"\\(text|mathrm|mathbf|mathit|mathcal|operatorname)\{([^}]*)\}", r"\2", text)

    # 10. Append notebook CTA if available
    if notebook_url:
        text += (
            "\n\n## Try the Code Yourself\n\n"
            "This digest was generated with a fully runnable Jupyter notebook.\n\n"
            f"[Open the notebook app]({notebook_url})\n"
        )

    return text, uploaded, failed, failed_details


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def publish_to_substack(
    summary_md: str,
    paper_title: str,
    diagram_dir: str,
    diagram_captions: list[str],
    important_tables: list[dict] | None = None,
    publish: bool = False,
    notebook_url: str = "",
    authors: list[str] | None = None,
    year: str = "",
    paper_url: str = "",
    citation_count: int | None = None,
) -> dict:
    """Create a Substack draft (or published post) from a digest.

    Returns dict with keys: status, url, draft_id, error, uploaded_images, failed_images
    """
    log.info("=== Starting Substack publish for: %s ===", paper_title)

    try:
        api = _get_api()
    except SubstackAuthError as exc:
        log.error("Auth failed: %s", exc)
        return {"status": "error", "error": str(exc)}

    try:
        user_id = api.get_user_id()
        log.info("User ID: %s", user_id)
    except Exception as exc:
        log.error("Failed to get user ID: %s", exc)
        return {"status": "error", "error": f"Failed to get user ID: {exc}"}

    # Preprocess markdown
    log.info("Preprocessing markdown (%d chars)...", len(summary_md))
    try:
        processed_md, uploaded, failed, failed_details = prepare_markdown_for_substack(
            summary_md, diagram_dir, diagram_captions, important_tables, api,
            notebook_url=notebook_url,
            authors=authors, year=year, paper_url=paper_url,
            citation_count=citation_count,
        )
        log.info("Preprocessing done: %d images uploaded, %d failed", uploaded, failed)
        if failed_details:
            for fd in failed_details:
                log.warning("  Failed: Diagram %d (%s) — %s",
                            fd["diagram_index"], fd.get("file", "N/A"), fd["reason"])
    except Exception as exc:
        log.exception("Preprocessing failed")
        return {"status": "error", "error": f"Preprocessing failed: {exc}"}

    # Build post
    try:
        from substack.post import Post

        # Build subtitle from metadata
        subtitle_parts = []
        if authors:
            subtitle_parts.append("By " + ", ".join(authors[:3]))
            if len(authors) > 3:
                subtitle_parts[-1] += " et al."
        if year:
            subtitle_parts.append(year)
        subtitle = " · ".join(subtitle_parts) if subtitle_parts else "AI-generated research digest"

        post = Post(
            title=paper_title,
            subtitle=subtitle,
            user_id=user_id,
            audience="everyone",
            write_comment_permissions="everyone",
        )
        post.from_markdown(processed_md, api=api)
    except Exception as exc:
        log.exception("Failed to build Substack post")
        return {"status": "error", "error": f"Failed to build post: {exc}"}

    # Create draft
    try:
        draft = api.post_draft(post.get_draft())
        draft_id = draft.get("id")
    except Exception as exc:
        log.exception("Failed to create draft")
        return {"status": "error", "error": f"Failed to create draft: {exc}"}

    # Optionally publish
    status = "draft"
    if publish and draft_id:
        try:
            api.prepublish_draft(draft_id)
            api.publish_draft(draft_id)
            status = "published"
        except Exception as exc:
            log.warning("Draft created but publishing failed: %s", exc)
            status = "draft"

    # Build URL
    pub_url = os.getenv("SUBSTACK_URL", "").rstrip("/")
    slug = draft.get("slug", "")
    if slug:
        post_url = f"{pub_url}/p/{slug}"
    elif draft_id:
        post_url = f"{pub_url}/publish/post/{draft_id}"
    else:
        post_url = pub_url

    return {
        "status": status,
        "url": post_url,
        "draft_id": str(draft_id) if draft_id else None,
        "uploaded_images": uploaded,
        "failed_images": failed,
        "failed_image_details": failed_details,
    }
