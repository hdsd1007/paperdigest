"""
pdf_parser.py
-------------
Converts a research-paper PDF into clean Markdown using Gemini.
"""

import re
import pathlib
from llm_client import llm_call

OCR_PROMPT = """You are a research paper OCR assistant.

Your job is to convert the attached PDF into clean, structured Markdown.

Rules:
- Preserve ALL text: abstract, introduction, related work, methodology,
  experiments, results, conclusion, references.
- Format section headers as ## Section Name.
- Preserve equations in LaTeX fences: $...$ for inline, $$...$$ for block.
- Preserve tables as Markdown tables.
- For figures / images inside the PDF, replace them with:
  [FIGURE: <one-sentence description of what the figure shows>]
- Do NOT truncate. Output the entire paper.
- Do NOT add commentary. Output only the Markdown transcript."""


def parse_pdf_to_markdown(pdf_path: str) -> str:
    pdf_bytes = pathlib.Path(pdf_path).read_bytes()
    result = llm_call(
        prompt=OCR_PROMPT,
        max_tokens=32768,
        temperature=0.0,
        pdf_bytes=pdf_bytes,
    )
    return result.text


def extract_abstract(paper_markdown: str) -> str:
    """Extract abstract from parsed markdown (pure regex, no LLM call).

    Strategy 1: text under '## Abstract' heading.
    Strategy 2: text between '# Title' and first '## ' heading.
    Returns empty string if not found.
    """
    # Strategy 1: explicit ## Abstract section
    m = re.search(
        r"##\s*Abstract\s*\n(.*?)(?=\n##\s|\Z)",
        paper_markdown,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        abstract = m.group(1).strip()
        if len(abstract) > 50:
            return abstract

    # Strategy 2: text between # Title and first ## heading
    lines = paper_markdown.split("\n")
    title_end = None
    for i, line in enumerate(lines):
        if line.strip().startswith("# ") and not line.strip().startswith("##"):
            title_end = i + 1
            break

    if title_end is not None:
        text_lines = []
        for line in lines[title_end:]:
            if line.strip().startswith("## "):
                break
            text_lines.append(line)
        text = "\n".join(text_lines).strip()
        # Filter out metadata lines (authors, emails, affiliations)
        # Keep only the substantive paragraph
        paragraphs = re.split(r"\n\s*\n", text)
        for para in paragraphs:
            para = para.strip()
            if len(para) > 100 and not re.match(r"^[\w.]+@", para):
                return para

    return ""
