"""
table_extractor.py
------------------
Extracts Markdown tables from parsed paper text, then uses an LLM call
to select the 1-2 most important tables for the digest.
"""

import json
import re

from llm_client import llm_call


def extract_tables(paper_markdown: str) -> list[dict]:
    """Find all Markdown tables in the paper text.

    Returns list of dicts: {markdown, context, row_count, col_count}.
    """
    lines = paper_markdown.split("\n")
    tables = []
    i = 0

    while i < len(lines):
        # Look for table header separator: |---|---|...|
        if re.match(r'^\s*\|[\s:]*-+[\s:]*\|', lines[i]):
            # Found a separator — backtrack to find the header row
            header_start = i - 1
            if header_start >= 0 and "|" in lines[header_start]:
                # Collect all contiguous table rows
                table_lines = [lines[header_start], lines[i]]
                j = i + 1
                while j < len(lines) and re.match(r'^\s*\|', lines[j]):
                    table_lines.append(lines[j])
                    j += 1

                table_md = "\n".join(table_lines)
                row_count = len(table_lines) - 2  # exclude header + separator
                col_count = lines[header_start].count("|") - 1

                # Capture context: preceding heading or paragraph
                context = _get_context(lines, header_start)

                tables.append({
                    "markdown": table_md,
                    "context": context,
                    "row_count": max(0, row_count),
                    "col_count": max(0, col_count),
                })

                i = j
                continue
        i += 1

    print(f"[table_extractor] Found {len(tables)} table(s) in paper markdown")
    return tables


def _get_context(lines: list[str], table_start: int) -> str:
    """Get the heading or paragraph immediately before a table."""
    for k in range(table_start - 1, max(table_start - 6, -1), -1):
        stripped = lines[k].strip()
        if not stripped:
            continue
        # Heading
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        # Non-empty text
        if len(stripped) > 10:
            return stripped[:200]
    return ""


def select_important_tables(
    tables: list[dict],
    max_tables: int = 2,
) -> list[dict]:
    """Use an LLM call to pick the 1-2 most important tables.

    Returns selected tables with an added "caption" field.
    Returns [] if no tables found or LLM fails.
    """
    if not tables:
        return []

    # Build numbered table list for prompt
    table_list = ""
    for i, t in enumerate(tables):
        context = t["context"] or "(no context)"
        # Truncate large tables for the prompt
        md_preview = t["markdown"][:500]
        if len(t["markdown"]) > 500:
            md_preview += "\n... (truncated)"
        table_list += f"\n--- Table {i} (context: {context}, {t['row_count']} rows, {t['col_count']} cols) ---\n{md_preview}\n"

    prompt = f"""You are selecting the most important tables from a research paper for a digest article.

TABLES FOUND IN PAPER:
{table_list}

TASK: Pick the 1-{max_tables} most important tables. Prefer:
- Main results/comparison tables (model vs baselines)
- Ablation study tables
- Key performance metrics

Skip: hyperparameter tables, dataset statistics (unless crucial), notation tables.

Return ONLY a JSON object:
{{
  "selected": [
    {{"index": 0, "caption": "Main results on benchmark X"}},
    {{"index": 3, "caption": "Ablation study results"}}
  ]
}}

Return ONLY the JSON — no markdown fences, no explanation."""

    for attempt in range(2):
        try:
            result = llm_call(prompt=prompt, max_tokens=512, temperature=0.0)
            raw = result.text.strip()

            if not raw:
                print(f"[table_extractor] LLM returned empty response (attempt {attempt+1})")
                prompt += "\n\nIMPORTANT: You must return a JSON object. Do not return an empty response."
                continue

            # Strip markdown fences
            fence_match = re.search(r'```(?:json)?\s*\n?(.*?)```', raw, re.DOTALL)
            if fence_match:
                raw = fence_match.group(1).strip()

            parsed = json.loads(raw)
            selections = parsed.get("selected", [])

            selected = []
            for sel in selections[:max_tables]:
                idx = sel.get("index", -1)
                caption = sel.get("caption", "")
                if 0 <= idx < len(tables):
                    table = dict(tables[idx])
                    table["caption"] = caption
                    selected.append(table)

            print(f"[table_extractor] Selected {len(selected)} important table(s)")
            return selected

        except Exception as exc:
            print(f"[table_extractor] LLM selection failed (attempt {attempt+1}): {exc}")
            if attempt == 0:
                prompt += "\n\nIMPORTANT: Your previous response was not valid JSON. Return ONLY a raw JSON object — no markdown fences, no explanation."

    # Fallback: pick the 2 largest tables by row count (likely results tables)
    if tables:
        ranked = sorted(tables, key=lambda t: t["row_count"], reverse=True)
        fallback = []
        for t in ranked[:max_tables]:
            table = dict(t)
            table["caption"] = t["context"] or "Key results"
            fallback.append(table)
        print(f"[table_extractor] Using fallback: {len(fallback)} largest table(s) by row count")
        return fallback

    return []
