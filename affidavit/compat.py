"""Small shared helpers.

PyMuPDF renamed its import from `fitz` to `pymupdf`. We prefer the new name
and fall back to the old one so the pipeline runs on either.
"""

from __future__ import annotations

import importlib
from types import ModuleType


def load_pymupdf() -> ModuleType | None:
    for name in ("pymupdf", "fitz"):
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    return None


PYMUPDF = load_pymupdf()
HAS_PYMUPDF = PYMUPDF is not None
