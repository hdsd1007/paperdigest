"""
notebook_gen.py
---------------
Generates a Jupyter notebook from the uploaded PDF using the local
paper-to-notebook vendor library.

Fallback: returns a link to the hosted app.
"""

import os
import sys
import pathlib
from dotenv import load_dotenv

load_dotenv()

P2N_URL = os.getenv("P2N_API_URL", "https://paper-to-notebook-production.up.railway.app")
VENDOR_DIR = pathlib.Path(__file__).parent.parent / "vendor" / "paper-to-notebook"

# ── Add vendor backend to sys.path at import time (thread-safe) ──────────
_VENDOR_BACKEND = VENDOR_DIR / "backend"
if _VENDOR_BACKEND.exists() and str(_VENDOR_BACKEND) not in sys.path:
    sys.path.insert(0, str(_VENDOR_BACKEND))


def generate_notebook(pdf_path: str, output_dir: str) -> dict:
    """Generate a notebook from a PDF. Falls back to hosted link on failure."""
    os.makedirs(output_dir, exist_ok=True)

    # Try local vendor
    result = _try_local(pdf_path, output_dir)
    if result:
        return result

    return {"ipynb_path": None, "colab_url": None, "hosted_url": P2N_URL, "strategy": "link"}


def _try_local(pdf_path: str, output_dir: str) -> dict | None:
    """Import run_pipeline from the vendor clone and generate locally."""
    if not _VENDOR_BACKEND.exists():
        print("[notebook_gen] vendor/paper-to-notebook/backend not found")
        return None

    try:
        from app import run_pipeline

        pdf_bytes = pathlib.Path(pdf_path).read_bytes()
        ipynb_bytes = run_pipeline(
            pdf_bytes=pdf_bytes,
            api_key=os.environ.get("GOOGLE_API_KEY"),
        )

        ipynb_path = os.path.join(output_dir, "paper_notebook.ipynb")
        with open(ipynb_path, "wb") as f:
            f.write(ipynb_bytes)

        return {
            "ipynb_path": ipynb_path,
            "colab_url": None,
            "hosted_url": P2N_URL,
            "strategy": "local",
        }

    except Exception as exc:
        print(f"[notebook_gen] Local generation failed: {exc}")
        return None
