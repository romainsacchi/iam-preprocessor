"""MESSAGE region cleanup workflow."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from .crypto import encrypt_file
from .exceptions import DataValidationError
from .filtering import filter_variables
from .io import discover_inputs, read_frame, sha256_file, write_csv_atomic, year_columns
from .report import ProcessingReport

MESSAGE_DRI_EAF = "Production|Iron and Steel|Steel|Primary|EAF|Sponge Iron"
MESSAGE_SPONGE_IRON_H2 = "Production|Iron and Steel|Sponge Iron|Hydrogen"
MESSAGE_SPONGE_IRON_GAS_CCS = "Production|Iron and Steel|Sponge Iron|Gas|w/ CCS"
MESSAGE_SPONGE_IRON_ROUTES = (
    "Production|Iron and Steel|Sponge Iron|Coal|w/o CCS",
    "Production|Iron and Steel|Sponge Iron|Gas|w/o CCS",
    MESSAGE_SPONGE_IRON_GAS_CCS,
    MESSAGE_SPONGE_IRON_H2,
)

MESSAGE_H_DRI_EAF = "Production|Industry|Iron and Steel|H-DRI/EAF"
MESSAGE_NG_DRI_EAF = "Production|Industry|Iron and Steel|NG-DRI/EAF"
MESSAGE_NG_DRI_EAF_CCS = "Production|Industry|Iron and Steel|NG-DRI/EAF + CCS"
MESSAGE_DERIVED_DRI_ROUTES = (
    MESSAGE_NG_DRI_EAF,
    MESSAGE_NG_DRI_EAF_CCS,
    MESSAGE_H_DRI_EAF,
)

MESSAGE_GLOBAL_REGIONS = ("World", "R12_GLB", "GLB")
MESSAGE_DRI_SPLIT_TOLERANCE = 1e-9


def _message_global_region(regions: pd.Index) -> str | None:
    """Return the preferred MESSAGE global aggregate present in ``regions``."""

    available = set(regions.astype(str))
    return next((region for region in MESSAGE_GLOBAL_REGIONS if region in available), None)


def split_message_dri_routes(data: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Derive mutually exclusive finished NG-DRI, NG-DRI+CCS, and H-DRI output.

    MESSAGE reports hydrogen and gas-with-CCS sponge iron separately, but only
    reports finished DRI/EAF steel as an aggregate across sponge-iron routes.
    For every model/scenario/year, the World finished-steel-to-sponge-iron
    conversion factor is applied to regional hydrogen and gas-with-CCS sponge
    iron. The existing non-CCS NG-DRI inventory is used as the residual proxy,
    including MESSAGE's coal-without-CCS sponge-iron remainder, so the three
    derived routes exactly reproduce the reported aggregate in every region
    and year.
    """

    frame = data.copy()
    warnings: list[str] = []
    source_variables = {MESSAGE_DRI_EAF, *MESSAGE_SPONGE_IRON_ROUTES}
    present_variables = set(frame["Variable"].dropna().astype(str))
    relevant_variables = source_variables | set(MESSAGE_DERIVED_DRI_ROUTES)

    if not present_variables.intersection(relevant_variables):
        return frame, warnings

    missing = sorted(source_variables - present_variables)
    if missing:
        warnings.append(
            "Skipped MESSAGE DRI route split because required source variables "
            f"are missing: {missing}."
        )
        return frame, warnings

    source_rows = frame[frame["Variable"].isin(source_variables)]
    invalid_units = sorted(set(source_rows.loc[~source_rows["Unit"].eq("Mt/yr"), "Unit"]))
    if invalid_units:
        raise DataValidationError(
            "MESSAGE DRI route splitting requires all production inputs in Mt/yr; "
            f"found {invalid_units}."
        )

    years = year_columns(frame)
    numeric = source_rows[years].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        invalid = source_rows.loc[numeric.isna().any(axis=1), ["Region", "Variable"]]
        raise DataValidationError(
            "MESSAGE DRI route splitting found non-numeric year values: "
            f"{invalid.head(5).to_dict(orient='records')}."
        )
    materially_negative_source = numeric < -MESSAGE_DRI_SPLIT_TOLERANCE
    if materially_negative_source.any().any():
        bad_index, bad_year = materially_negative_source.stack().idxmax()
        bad_row = source_rows.loc[bad_index]
        raise DataValidationError(
            "MESSAGE DRI route splitting requires non-negative production; "
            f"found {numeric.loc[bad_index, bad_year]} for "
            f"{bad_row['Variable']!r}, region {bad_row['Region']}, year {bad_year}."
        )

    # Recompute existing derived rows deterministically so the operation is idempotent.
    frame = frame.loc[~frame["Variable"].isin(MESSAGE_DERIVED_DRI_ROUTES)].copy()
    derived_rows: list[pd.DataFrame] = []
    grouping = ["Model", "Scenario"]

    for identity, scenario in frame.groupby(grouping, sort=False, dropna=False):
        scenario_sources = scenario[scenario["Variable"].isin(source_variables)]
        values_by_variable = {
            variable: scenario_sources.loc[scenario_sources["Variable"].eq(variable)]
            .set_index("Region")[years]
            .astype(float)
            for variable in source_variables
        }
        aggregate = values_by_variable[MESSAGE_DRI_EAF]
        regions = aggregate.index
        for variable, values in values_by_variable.items():
            extra_regions = values.index.difference(regions)
            if (
                len(extra_regions)
                and values.loc[extra_regions].abs().to_numpy().max() > MESSAGE_DRI_SPLIT_TOLERANCE
            ):
                raise DataValidationError(
                    f"MESSAGE DRI route source variable {variable!r} has positive "
                    "production in a region without aggregate DRI/EAF output for "
                    f"model/scenario {identity}: {extra_regions.tolist()}."
                )
            values_by_variable[variable] = values.reindex(regions, fill_value=0)

        total_sponge = sum(
            (values_by_variable[variable] for variable in MESSAGE_SPONGE_IRON_ROUTES),
            pd.DataFrame(0.0, index=regions, columns=years),
        )
        global_region = _message_global_region(regions)
        if global_region is None:
            global_finished = aggregate.sum(axis=0)
            global_sponge = total_sponge.sum(axis=0)
            warnings.append(
                "MESSAGE DRI route split found no explicit global row for "
                f"model/scenario {identity}; used regional sums."
            )
        else:
            global_finished = aggregate.loc[global_region]
            global_sponge = total_sponge.loc[global_region]

        invalid_denominator = (global_sponge <= 0) & (
            global_finished.abs() > MESSAGE_DRI_SPLIT_TOLERANCE
        )
        if invalid_denominator.any():
            invalid_years = [year for year in years if invalid_denominator.loc[year]]
            raise DataValidationError(
                "MESSAGE DRI route split has finished DRI/EAF production but no "
                f"sponge-iron production for model/scenario {identity}, years {invalid_years}."
            )

        conversion = global_finished.divide(global_sponge.where(global_sponge > 0)).fillna(0)
        h_dri = values_by_variable[MESSAGE_SPONGE_IRON_H2].mul(conversion, axis=1)
        ng_dri_ccs = values_by_variable[MESSAGE_SPONGE_IRON_GAS_CCS].mul(conversion, axis=1)
        ng_dri = aggregate - h_dri - ng_dri_ccs

        materially_negative = ng_dri < -MESSAGE_DRI_SPLIT_TOLERANCE
        if materially_negative.any().any():
            bad_region, bad_year = materially_negative.stack().idxmax()
            raise DataValidationError(
                "MESSAGE DRI route split produced a negative NG-DRI residual for "
                f"model/scenario {identity}, region {bad_region}, year {bad_year}: "
                f"{ng_dri.loc[bad_region, bad_year]}."
            )
        ng_dri = ng_dri.clip(lower=0)

        derived_values = (
            (MESSAGE_NG_DRI_EAF, ng_dri),
            (MESSAGE_NG_DRI_EAF_CCS, ng_dri_ccs),
            (MESSAGE_H_DRI_EAF, h_dri),
        )
        closure = sum(
            (values for _, values in derived_values),
            pd.DataFrame(0.0, index=regions, columns=years),
        )
        if not np.allclose(
            closure.to_numpy(),
            aggregate.to_numpy(),
            rtol=0,
            atol=MESSAGE_DRI_SPLIT_TOLERANCE,
        ):
            raise DataValidationError(
                "MESSAGE DRI route split does not reproduce aggregate DRI/EAF output "
                f"for model/scenario {identity}."
            )

        non_global_regions = regions.difference(MESSAGE_GLOBAL_REGIONS)
        if global_region is not None and len(non_global_regions):
            for variable, values in derived_values:
                if not np.allclose(
                    values.loc[global_region].to_numpy(),
                    values.loc[non_global_regions].sum(axis=0).to_numpy(),
                    rtol=0,
                    atol=MESSAGE_DRI_SPLIT_TOLERANCE,
                ):
                    raise DataValidationError(
                        f"MESSAGE derived route {variable!r} does not preserve "
                        "World versus regional totals for model/scenario "
                        f"{identity}."
                    )

        templates = scenario.loc[scenario["Variable"].eq(MESSAGE_DRI_EAF)].copy()
        templates = templates.set_index("Region").loc[regions]
        for variable, values in derived_values:
            rows = templates.copy()
            rows["Variable"] = variable
            rows.loc[:, years] = values.loc[rows.index, years].to_numpy()
            derived_rows.append(rows.reset_index())

    if derived_rows:
        frame = pd.concat([frame, *derived_rows], ignore_index=True)

    return frame, warnings


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
        frame = read_frame(source, drop_exact_duplicates=True)
        report = ProcessingReport(
            model="message",
            input_path=str(source),
            input_sha256=sha256_file(source),
            input_rows=len(frame) + frame.attrs.get("exact_duplicate_rows_removed", 0),
        )
        duplicate_rows_removed = frame.attrs.get("exact_duplicate_rows_removed", 0)
        if duplicate_rows_removed:
            report.warnings.append(f"Removed {duplicate_rows_removed} exact duplicate source rows.")
        frame, split_warnings = split_message_dri_routes(frame)
        report.warnings.extend(split_warnings)
        derived_variables = [
            variable
            for variable in MESSAGE_DERIVED_DRI_ROUTES
            if variable in set(frame["Variable"].astype(str))
        ]
        report.derived_variables.extend(derived_variables)
        if derived_variables:
            report.assumptions["message_dri_route_split"] = {
                "method": (
                    "Apply each scenario-year World finished DRI/EAF steel-to-total "
                    "sponge-iron conversion factor to regional hydrogen and gas-with-CCS "
                    "sponge iron; assign the remaining non-H2/non-CCS output to the "
                    "existing NG-DRI inventory proxy."
                ),
                "residual_proxy": (
                    "The NG-DRI residual includes MESSAGE coal-without-CCS sponge iron "
                    "because premise has no separate coal-DRI inventory category."
                ),
                "source_variables": sorted({MESSAGE_DRI_EAF, *MESSAGE_SPONGE_IRON_ROUTES}),
                "derived_variables": list(MESSAGE_DERIVED_DRI_ROUTES),
            }
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
