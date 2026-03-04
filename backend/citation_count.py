"""
citation_count.py
-----------------
Fetch citation count for a paper from Semantic Scholar (free, no API key).
"""

import json
import re
import urllib.request
import urllib.parse

_TIMEOUT = 10  # seconds


def fetch_citation_count(paper_url: str = "", title: str = "") -> int | None:
    """Return the citation count for a paper, or None on any failure.

    Tries arXiv ID lookup first (exact match), then falls back to title search.
    """
    try:
        # Try arXiv ID first
        arxiv_id = _extract_arxiv_id(paper_url)
        if arxiv_id:
            count = _query_by_arxiv_id(arxiv_id)
            if count is not None:
                print(f"[citation_count] Found {count} citations via arXiv ID {arxiv_id}")
                return count
            print(f"[citation_count] arXiv ID {arxiv_id} found but Semantic Scholar returned no count")

        # Fall back to title search
        if title and title != "Research Paper":
            count = _query_by_title(title)
            if count is not None:
                print(f"[citation_count] Found {count} citations via title search")
                return count
            print(f"[citation_count] Title search returned no results for: {title[:80]}")
        elif not arxiv_id:
            print("[citation_count] No arXiv ID and no usable title — cannot fetch citations")
    except Exception as exc:
        print(f"[citation_count] Failed: {type(exc).__name__}: {exc}")
    return None


def _extract_arxiv_id(url: str) -> str | None:
    """Extract arXiv ID from a URL or plain 'arXiv:XXXX.XXXXX' string."""
    if not url:
        return None
    # Pattern 1: URL like https://arxiv.org/abs/2301.08243 or /pdf/2301.08243
    m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)", url)
    if m:
        return m.group(1)
    # Pattern 2: plain "arXiv:2301.08243" (case-insensitive, tolerant of whitespace)
    m = re.search(r"arxiv\s*:\s*(\d{4}\.\d{4,5}(?:v\d+)?)", url, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _query_by_arxiv_id(arxiv_id: str) -> int | None:
    url = f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}?fields=citationCount"
    data = _fetch_json(url)
    if data and "citationCount" in data:
        return data["citationCount"]
    return None


def _query_by_title(title: str) -> int | None:
    encoded = urllib.parse.quote(title)
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={encoded}&limit=1&fields=citationCount"
    data = _fetch_json(url)
    if data and data.get("data"):
        first = data["data"][0]
        if "citationCount" in first:
            return first["citationCount"]
    return None


def _fetch_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PaperDigest/1.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        print(f"[citation_count] HTTP request failed: {type(exc).__name__}: {exc}")
        return None
