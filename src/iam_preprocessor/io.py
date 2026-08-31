"""Input discovery, tabular validation, hashing, and atomic output."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

import pandas as pd

from .exceptions import DataValidationError, IamPreprocessorError

REQUIRED_COLUMNS = ("Model", "Scenario", "Region", "Variable", "Unit")
YEAR_PATTERN = re.compile(r"^\d{4}$")


def sha256_file(path: str | Path) -> str:
    """Return the hexadecimal SHA-256 digest of a file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_columns(data: pd.DataFrame) -> pd.DataFrame:
    """Remove accidental index columns and normalize year labels to strings."""

    frame = data.copy()
    unnamed = [column for column in frame.columns if str(column).startswith("Unnamed:")]
    if unnamed:
        frame = frame.drop(columns=unnamed)
    frame = frame.rename(
        columns={
            column: str(column).strip()
            for column in frame.columns
            if YEAR_PATTERN.match(str(column).strip())
        }
    )
    return frame


def year_columns(data: pd.DataFrame) -> list[str]:
    """Return sorted four-digit year columns."""

    return sorted(
        [str(column) for column in data.columns if YEAR_PATTERN.match(str(column))],
        key=int,
    )


def validate_frame(data: pd.DataFrame) -> None:
    """Validate the shared IAM tabular schema and row uniqueness."""

    missing = [column for column in REQUIRED_COLUMNS if column not in data.columns]
    if missing:
        raise DataValidationError("Missing required columns: " + ", ".join(missing))
    years = year_columns(data)
    if not years:
        raise DataValidationError("No four-digit year columns were found.")
    duplicate_columns = [column for column in data.columns if list(data.columns).count(column) > 1]
    if duplicate_columns:
        raise DataValidationError(
            "Duplicate columns are not supported: " + ", ".join(sorted(set(duplicate_columns)))
        )
    keys = ["Model", "Scenario", "Region", "Variable"]
    duplicates = data.duplicated(keys, keep=False)
    if duplicates.any():
        sample = data.loc[duplicates, keys].head(5).to_dict(orient="records")
        raise DataValidationError(f"Duplicate IAM rows for {keys}: {sample}")


def read_frame(path: str | Path, *, drop_exact_duplicates: bool = False) -> pd.DataFrame:
    """Read an IAM Excel or comma/semicolon-delimited CSV file.

    ``drop_exact_duplicates`` is reserved for source exports known to repeat
    byte-equivalent IAM rows. Conflicting rows with the same IAM identity are
    still rejected by :func:`validate_frame`.
    """

    source = Path(path)
    suffix = source.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(source)
    elif suffix == ".csv":
        with source.open("r", encoding="utf-8-sig", errors="replace") as stream:
            first_line = stream.readline()
        separator = ";" if first_line.count(";") > first_line.count(",") else ","
        frame = pd.read_csv(source, sep=separator)
    else:
        raise IamPreprocessorError(f"Unsupported input format: {source}")
    frame = normalize_columns(frame)
    duplicate_rows_removed = 0
    if drop_exact_duplicates:
        duplicate_rows_removed = int(frame.duplicated(keep="first").sum())
        if duplicate_rows_removed:
            frame = frame.drop_duplicates(keep="first").reset_index(drop=True)
    validate_frame(frame)
    frame.attrs["exact_duplicate_rows_removed"] = duplicate_rows_removed
    return frame


def discover_inputs(
    inputs: Sequence[str | Path],
    *,
    suffixes: Iterable[str],
) -> list[Path]:
    """Resolve files and non-recursive directories into a stable input list."""

    allowed = {suffix.lower() for suffix in suffixes}
    found: list[Path] = []
    for raw_path in inputs:
        path = Path(raw_path).expanduser().resolve()
        if path.is_dir():
            found.extend(
                candidate
                for candidate in path.iterdir()
                if candidate.is_file()
                and candidate.suffix.lower() in allowed
                and not any(token in candidate.stem for token in ("_filtered", "_allocated"))
            )
        elif path.is_file() and path.suffix.lower() in allowed:
            found.append(path)
        else:
            raise IamPreprocessorError(f"Input does not exist or has an unsupported suffix: {path}")
    unique = sorted(set(found), key=lambda candidate: str(candidate).lower())
    if not unique:
        raise IamPreprocessorError("No matching input files were found.")
    return unique


def write_csv_atomic(
    data: pd.DataFrame,
    destination: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Write a semicolon-delimited CSV atomically without an index column."""

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise IamPreprocessorError(f"Output already exists: {path}. Use --overwrite to replace it.")
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        data.to_csv(temporary, sep=";", index=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
