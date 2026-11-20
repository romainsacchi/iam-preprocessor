"""REMIND cement CCS splitting workflow."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from ...crypto import encrypt_file
from ...exceptions import DataValidationError
from ...filtering import filter_variables
from ...io import discover_inputs, read_frame, sha256_file, write_csv_atomic, year_columns
from ...report import ProcessingReport
from ...variable_maps import variable_map

ADAPTER = variable_map("variables.yaml", package=__package__)
CEMENT = ADAPTER["cement"]


def split_cement_ccs(data: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Split REMIND cement production and energy into CCS and non-CCS rows."""

    frame = data.copy()
    years = year_columns(frame)
    appended: list[pd.Series] = []
    warnings: list[str] = []
    groups = frame[["Model", "Scenario", "Region"]].drop_duplicates()

    for group in groups.itertuples(index=False):
        mask = (
            frame["Model"].eq(group.Model)
            & frame["Scenario"].eq(group.Scenario)
            & frame["Region"].eq(group.Region)
        )
        subset = frame.loc[mask]
        variables = subset["Variable"].astype(str)
        capture_rows = subset.loc[variables.str.startswith(CEMENT["capture_prefix"])]
        emission_rows = subset.loc[variables.str.startswith(CEMENT["emissions_prefix"])]
        if capture_rows.empty and emission_rows.empty:
            continue

        identity = f"{group.Model}/{group.Scenario}/{group.Region}"
        target_rows: dict[str, pd.DataFrame] = {
            variable: subset.loc[variables.eq(variable)] for variable in CEMENT["ccs_output"]
        }
        for variable, rows in target_rows.items():
            if len(rows) != 1:
                raise DataValidationError(
                    f"Expected exactly one {variable!r} row in {identity}; found {len(rows)}."
                )

        capture = (
            capture_rows[years].apply(pd.to_numeric, errors="raise").sum(axis=0).to_numpy(float)
        )
        emitted = (
            emission_rows[years].apply(pd.to_numeric, errors="raise").sum(axis=0).to_numpy(float)
        )
        # Use the captured fraction of total CO2 to split cement production and energy use.
        denominator = capture + emitted
        rate = np.divide(
            capture,
            denominator,
            out=np.zeros_like(capture, dtype=float),
            where=~np.isclose(denominator, 0),
        )
        if ((rate < 0) | (rate > 1)).any():
            warnings.append(f"Clipped out-of-range cement CCS rates in {identity}.")
            rate = np.clip(rate, 0, 1)

        for variable, rows in target_rows.items():
            original = rows.iloc[0].copy()
            values = pd.to_numeric(original[years], errors="raise").to_numpy(float)
            ccs = original.copy()
            ccs["Variable"] = CEMENT["ccs_output"][variable]
            ccs[years] = values * rate
            appended.append(ccs)
            frame.loc[rows.index, years] = values * (1 - rate)

    if appended:
        duplicate_targets = set(row["Variable"] for row in appended).intersection(
            set(data["Variable"].astype(str))
        )
        if duplicate_targets:
            raise DataValidationError(
                "Cement CCS variables already exist: " + ", ".join(sorted(duplicate_targets))
            )
        frame = pd.concat([frame, pd.DataFrame(appended)], ignore_index=True)
    return frame, warnings


def prepare_remind(
    inputs: Sequence[str | Path],
    output_dir: str | Path,
    *,
    filter_output: bool = True,
    encrypt_to: str | Path | None = None,
    key_file: str | Path | None = None,
    overwrite: bool = False,
) -> list[ProcessingReport]:
    """Prepare REMIND data, including cement CCS splitting and region cleanup."""

    destinations = Path(output_dir)
    reports: list[ProcessingReport] = []
    for source in discover_inputs(inputs, suffixes=(".csv", ".mif")):
        frame = read_frame(source)
        report = ProcessingReport(
            model="remind",
            input_path=str(source),
            input_sha256=sha256_file(source),
            input_rows=len(frame),
        )
        excluded = set(ADAPTER["regions"]["exclude"])
        for marker, regions in ADAPTER["regions"]["exclude_by_filename"].items():
            if marker in source.name:
                excluded.update(regions)
        removed = int(frame["Region"].isin(excluded).sum())
        frame = frame.loc[~frame["Region"].isin(excluded)].copy()
        if removed:
            report.warnings.append(
                f"Removed {removed} rows for excluded regions: {', '.join(sorted(excluded))}."
            )

        frame, warnings = split_cement_ccs(frame)
        report.warnings.extend(warnings)
        for variable in CEMENT["ccs_output"].values():
            if frame["Variable"].eq(variable).any():
                report.derived_variables.append(variable)

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
