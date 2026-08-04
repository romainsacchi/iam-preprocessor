"""MESSAGE region cleanup workflow."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .crypto import encrypt_file
from .filtering import filter_variables
from .io import discover_inputs, read_frame, sha256_file, write_csv_atomic
from .report import ProcessingReport


def prepare_message(
    inputs: Sequence[str | Path],
    output_dir: str | Path,
    *,
    filter_output: bool = True,
    encrypt_to: str | Path | None = None,
    key_file: str | Path | None = None,
    overwrite: bool = False,
) -> list[ProcessingReport]:
    """Normalize MESSAGE regions and prepare filtered premise CSV files."""

    destinations = Path(output_dir)
    reports: list[ProcessingReport] = []
    for source in discover_inputs(inputs, suffixes=(".csv",)):
        frame = read_frame(source)
        report = ProcessingReport(
            model="message",
            input_path=str(source),
            input_sha256=sha256_file(source),
            input_rows=len(frame),
        )
        frame["Region"] = frame["Region"].astype(str).str.replace("R12_", "", regex=False)
        before = len(frame)
        frame = frame.loc[~frame["Region"].eq("GLB")].copy()
        removed = before - len(frame)
        if removed:
            report.warnings.append(f"Removed {removed} GLB rows.")

        if filter_output:
            frame = filter_variables(frame)
            suffix = "_filtered.csv"
        else:
            suffix = "_processed.csv"
        destination = destinations / f"{source.stem}{suffix}"
        write_csv_atomic(frame, destination, overwrite=overwrite)
        report.output_path = str(destination)
        report.output_sha256 = sha256_file(destination)
        report.output_rows = len(frame)

        if encrypt_to is not None:
            encrypted = Path(encrypt_to) / destination.name
            encrypt_file(destination, encrypted, key_file=key_file, overwrite=overwrite)
            report.encrypted_output_path = str(encrypted)
            report.encrypted_output_sha256 = sha256_file(encrypted)

        report.write(destinations / f"{source.stem}_report.json", overwrite=overwrite)
        reports.append(report)
    return reports
