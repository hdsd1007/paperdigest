"""
figure_extractor.py
-------------------
Extracts original figures from a research paper PDF using PyMuPDF.
Figures are saved for archival purposes.
"""

import re
from pathlib import Path


def extract_figures(pdf_path: str, min_dim: int = 200) -> list[dict]:
    """Extract images from a PDF using PyMuPDF.

    Args:
        pdf_path: Path to the PDF file.
        min_dim: Minimum width/height in pixels to keep an image.

    Returns:
        List of dicts with keys: index, page, image_bytes, width, height, caption.
        Returns [] if fitz is unavailable or the PDF has no extractable images.
    """
    try:
        import fitz
    except ImportError:
        print("[figure_extractor] PyMuPDF (fitz) not installed — skipping figure extraction")
        return []

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        print(f"[figure_extractor] Failed to open PDF: {exc}")
        return []

    figures = []
    seen_xrefs = set()

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_text = page.get_text("text")

        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            try:
                base_image = doc.extract_image(xref)
            except Exception:
                continue

            if not base_image or "image" not in base_image:
                continue

            width = base_image.get("width", 0)
            height = base_image.get("height", 0)
            image_bytes = base_image["image"]

            if width < min_dim or height < min_dim:
                continue

            # Try to find a caption near this image on the same page
            caption = _find_caption(page_text, len(figures))

            figures.append({
                "index": len(figures),
                "page": page_num + 1,
                "image_bytes": image_bytes,
                "width": width,
                "height": height,
                "caption": caption,
                "ext": base_image.get("ext", "png"),
            })

    doc.close()
    print(f"[figure_extractor] Extracted {len(figures)} figure(s) from PDF")
    return figures


def _find_caption(page_text: str, figure_index: int) -> str:
    """Scan page text for Figure N / Fig. N captions."""
    patterns = [
        rf"(?:Figure|Fig\.?)\s+{figure_index + 1}\s*[:.]\s*(.+)",
        rf"(?:Figure|Fig\.?)\s+{figure_index + 1}\s*(.+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, page_text, re.IGNORECASE)
        if m:
            caption = m.group(1).strip()
            # Limit caption length
            if len(caption) > 200:
                caption = caption[:200] + "..."
            return caption
    return ""


def save_figures(figures: list[dict], output_dir: str) -> list[str]:
    """Save extracted figure images to disk.

    Returns list of saved file paths.
    """
    fig_dir = Path(output_dir) / "original_figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    paths = []
    for fig in figures:
        ext = fig.get("ext", "png")
        filename = f"figure_{fig['index']}.{ext}"
        path = fig_dir / filename
        path.write_bytes(fig["image_bytes"])
        paths.append(str(path))

    return paths
