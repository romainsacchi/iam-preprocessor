from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

project = "iam-preprocessor"
author = "Romain Sacchi"
release = "0.1.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]
autodoc_typehints = "description"
napoleon_numpy_docstring = True
html_theme = "alabaster"
exclude_patterns = ["_build"]
