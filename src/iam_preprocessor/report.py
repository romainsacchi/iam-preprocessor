"""Machine-readable processing reports."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .exceptions import IamPreprocessorError


@dataclass
class ProcessingReport:
    """Reproducibility metadata for one processed input file."""

    model: str
    input_path: str
    output_path: str | None = None
    input_sha256: str | None = None
    output_sha256: str | None = None
    input_rows: int = 0
    output_rows: int = 0
    derived_variables: list[str] = field(default_factory=list)
    skipped_variables: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    assumptions: dict[str, Any] = field(default_factory=dict)
    encrypted_output_path: str | None = None
    encrypted_output_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)

    def write(self, path: str | Path, *, overwrite: bool = False) -> Path:
        """Write this report atomically as indented JSON."""

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and not overwrite:
            raise IamPreprocessorError(
                f"Report already exists: {destination}. Use overwrite=True to replace it."
            )
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        os.close(handle)
        temporary = Path(temporary_name)
        try:
            temporary.write_text(
                json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination
