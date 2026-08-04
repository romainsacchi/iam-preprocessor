"""IMAGE preprocessing workflow."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .config import SecConfig
from .crypto import encrypt_file
from .filtering import filter_variables
from .io import discover_inputs, read_frame, sha256_file, write_csv_atomic
from .report import ProcessingReport
from .transport import derive_bev_truck_variables, derive_transport_energy_services


def prepare_image(
    inputs: Sequence[str | Path],
    output_dir: str | Path,
    sec_config: SecConfig,
    *,
    derive_bev: bool = True,
    strict: bool = False,
    filter_output: bool = True,
    encrypt_to: str | Path | None = None,
    key_file: str | Path | None = None,
    overwrite: bool = False,
) -> list[ProcessingReport]:
    """Prepare one or more IMAGE files for premise.

    Inputs are normalized, enriched with configured carrier services and optional
    BEV-truck residual variables, filtered, written as semicolon-delimited CSV,
    and optionally encrypted into a second directory.
    """

    destinations = Path(output_dir)
    reports: list[ProcessingReport] = []
    for source in discover_inputs(inputs, suffixes=(".xlsx", ".xls", ".csv")):
        frame = read_frame(source)
        report = ProcessingReport(
            model="image",
            input_path=str(source),
            input_sha256=sha256_file(source),
            input_rows=len(frame),
            assumptions=sec_config.as_public_dict(),
        )

        frame, service_summary = derive_transport_energy_services(frame, sec_config)
        report.derived_variables.extend(service_summary.derived_variables)
        report.skipped_variables.extend(service_summary.skipped_variables)
        report.warnings.extend(service_summary.warnings)

        if derive_bev:
            frame, bev_summary = derive_bev_truck_variables(frame, sec_config, strict=strict)
            report.derived_variables.extend(bev_summary.derived_variables)
            report.skipped_variables.extend(bev_summary.skipped_variables)
            report.warnings.extend(bev_summary.warnings)
        else:
            report.warnings.append("BEV-truck derivation was explicitly skipped.")

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
        report.derived_variables = sorted(set(report.derived_variables))
        report.skipped_variables = sorted(set(report.skipped_variables))

        if encrypt_to is not None:
            encrypted = Path(encrypt_to) / destination.name
            encrypt_file(
                destination,
                encrypted,
                key_file=key_file,
                overwrite=overwrite,
            )
            report.encrypted_output_path = str(encrypted)
            report.encrypted_output_sha256 = sha256_file(encrypted)

        report.write(destinations / f"{source.stem}_report.json", overwrite=overwrite)
        reports.append(report)
    return reports
