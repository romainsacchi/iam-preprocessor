"""TIAM-UCL preprocessing and derived H-DRI hydrogen demand."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from .crypto import encrypt_file
from .exceptions import DataValidationError
from .filtering import filter_variables
from .io import discover_inputs, read_frame, sha256_file, write_csv_atomic, year_columns
from .report import ProcessingReport

TIAM_H_DRI_PRODUCTION = "Production|Steel|Secondary|DRH2 and EAF"
TIAM_H_DRI_PRODUCTION_PRODUCT = f"{TIAM_H_DRI_PRODUCTION}|Steel"
TIAM_H_DRI_HYDROGEN = "Final Energy|Production|Steel|Secondary|DRH2 and EAF|Hydrogen"

# The premise H2-DRI/EAF inventory consumes 1.061992 kg of H2-DRI pig iron per
# kg of finished steel. Producing that pig iron consumes 0.06264 kg H2/kg.
TIAM_DEFAULT_H_DRI_HYDROGEN_KG_PER_TONNE_STEEL = 66.52317888
TIAM_H2_LHV_GJ_PER_TONNE = 120.0
TIAM_TOLERANCE = 1e-9


def _validate_world_closure(values: pd.DataFrame, identity: tuple[object, ...]) -> None:
    """Require an explicit World row to equal the sum of regional rows."""

    if "World" not in values.index or len(values.index) == 1:
        return
    regional = values.drop(index="World").sum(axis=0)
    if not np.allclose(
        values.loc["World"].to_numpy(),
        regional.to_numpy(),
        rtol=0,
        atol=TIAM_TOLERANCE,
    ):
        raise DataValidationError(
            "TIAM-UCL H-DRI production does not preserve World versus regional "
            f"totals for model/scenario {identity}."
        )


def derive_tiam_h_dri_hydrogen(
    data: pd.DataFrame,
    *,
    hydrogen_kg_per_tonne_steel: float = TIAM_DEFAULT_H_DRI_HYDROGEN_KG_PER_TONNE_STEEL,
) -> tuple[pd.DataFrame, list[str]]:
    """Derive regional H-DRI hydrogen final energy from reported steel output.

    TIAM-UCL reports finished H-DRI/EAF steel production in Mt/year but omits
    the associated hydrogen input from its exported final-energy coordinates.
    The derived series uses an explicit kg-H2/t-steel intensity and the same
    120 GJ/t lower heating value used by premise hydrogen logistics.
    """

    if not math.isfinite(hydrogen_kg_per_tonne_steel) or hydrogen_kg_per_tonne_steel <= 0:
        raise DataValidationError(
            "TIAM-UCL H-DRI hydrogen intensity must be a positive finite value."
        )

    frame = data.copy()
    warnings: list[str] = []
    present_variables = set(frame["Variable"].dropna().astype(str))
    source_candidates = (
        TIAM_H_DRI_PRODUCTION,
        TIAM_H_DRI_PRODUCTION_PRODUCT,
    )
    present_sources = [variable for variable in source_candidates if variable in present_variables]
    if not present_sources:
        warnings.append(
            "Skipped TIAM-UCL H-DRI hydrogen derivation because no H-DRI/EAF "
            "production variable is present."
        )
        return frame, warnings

    years = year_columns(frame)
    grouping = ["Model", "Scenario"]
    derived_rows: list[pd.DataFrame] = []
    frame = frame.loc[~frame["Variable"].eq(TIAM_H_DRI_HYDROGEN)].copy()

    # 1 Mt steel × kg H2/t steel × 120 GJ/t H2 = intensity × 0.12 PJ H2.
    pj_per_mt_steel = hydrogen_kg_per_tonne_steel * TIAM_H2_LHV_GJ_PER_TONNE / 1_000

    for identity, scenario in frame.groupby(grouping, sort=False, dropna=False):
        scenario_sources = [
            variable
            for variable in source_candidates
            if variable in set(scenario["Variable"].dropna().astype(str))
        ]
        if not scenario_sources:
            continue

        source_variable = scenario_sources[0]
        source_rows = scenario.loc[scenario["Variable"].eq(source_variable)].copy()
        duplicate_source_regions = source_rows.loc[
            source_rows["Region"].duplicated(keep=False), "Region"
        ].astype(str)
        if not duplicate_source_regions.empty:
            raise DataValidationError(
                "TIAM-UCL H-DRI production is non-unique for model/scenario "
                f"{identity}, regions {sorted(set(duplicate_source_regions))[:5]}."
            )
        invalid_units = sorted(
            set(source_rows.loc[~source_rows["Unit"].eq("Mt/yr"), "Unit"].astype(str))
        )
        if invalid_units:
            raise DataValidationError(
                "TIAM-UCL H-DRI hydrogen derivation requires production in Mt/yr; "
                f"found {invalid_units} for model/scenario {identity}."
            )

        production = source_rows.set_index("Region")[years].apply(pd.to_numeric, errors="coerce")
        if production.isna().any().any():
            invalid_regions = production.index[production.isna().any(axis=1)].tolist()
            raise DataValidationError(
                "TIAM-UCL H-DRI production contains non-numeric year values for "
                f"model/scenario {identity}, regions {invalid_regions[:5]}."
            )
        materially_negative = production < -TIAM_TOLERANCE
        if materially_negative.any().any():
            bad_region, bad_year = materially_negative.stack().idxmax()
            raise DataValidationError(
                "TIAM-UCL H-DRI production must be non-negative; found "
                f"{production.loc[bad_region, bad_year]} for model/scenario "
                f"{identity}, region {bad_region}, year {bad_year}."
            )
        production = production.clip(lower=0)
        _validate_world_closure(production, identity)

        for alias in scenario_sources[1:]:
            alias_rows = scenario.loc[scenario["Variable"].eq(alias)]
            invalid_alias_units = sorted(
                set(alias_rows.loc[~alias_rows["Unit"].eq("Mt/yr"), "Unit"].astype(str))
            )
            if invalid_alias_units:
                raise DataValidationError(
                    "TIAM-UCL H-DRI production aliases must use Mt/yr; "
                    f"found {invalid_alias_units} for model/scenario {identity}, "
                    f"variable {alias!r}."
                )
            if set(alias_rows["Region"].astype(str)) != set(production.index.astype(str)):
                raise DataValidationError(
                    "TIAM-UCL H-DRI production aliases cover different regions for "
                    f"model/scenario {identity}: {source_variable!r} and {alias!r}."
                )
            alias_values = alias_rows.set_index("Region")[years].apply(
                pd.to_numeric, errors="coerce"
            )
            alias_values = alias_values.reindex(index=production.index)
            if not np.allclose(
                alias_values.to_numpy(),
                production.to_numpy(),
                rtol=0,
                atol=TIAM_TOLERANCE,
                equal_nan=False,
            ):
                raise DataValidationError(
                    "TIAM-UCL H-DRI production aliases disagree for "
                    f"model/scenario {identity}: {source_variable!r} and {alias!r}."
                )

        rows = source_rows.set_index("Region").loc[production.index].copy()
        rows["Variable"] = TIAM_H_DRI_HYDROGEN
        rows["Unit"] = "PJ/yr"
        rows.loc[:, years] = production.mul(pj_per_mt_steel).to_numpy()
        derived_rows.append(rows.reset_index())

    if derived_rows:
        frame = pd.concat([frame, *derived_rows], ignore_index=True)

    return frame, warnings


def prepare_tiam_ucl(
    inputs: Sequence[str | Path],
    output_dir: str | Path,
    *,
    h_dri_hydrogen_kg_per_tonne_steel: float = (TIAM_DEFAULT_H_DRI_HYDROGEN_KG_PER_TONNE_STEEL),
    filter_output: bool = True,
    encrypt_to: str | Path | None = None,
    key_file: str | Path | None = None,
    overwrite: bool = False,
) -> list[ProcessingReport]:
    """Prepare TIAM-UCL files and derive H-DRI hydrogen final energy."""

    destinations = Path(output_dir)
    reports: list[ProcessingReport] = []
    for source in discover_inputs(inputs, suffixes=(".csv", ".xlsx", ".xls")):
        frame = read_frame(
            source,
            allow_duplicate_identities=True,
        )
        report = ProcessingReport(
            model="tiam-ucl",
            input_path=str(source),
            input_sha256=sha256_file(source),
            input_rows=len(frame),
        )
        identity_keys = ["Model", "Scenario", "Region", "Variable"]
        duplicate_identities = frame.loc[frame.duplicated(identity_keys, keep=False), identity_keys]
        if not duplicate_identities.empty:
            report.warnings.append(
                "Preserved "
                f"{len(duplicate_identities)} rows across "
                f"{len(duplicate_identities.drop_duplicates())} non-unique IAM "
                "identities because TIAM-UCL exports distinct technology-efficiency "
                "variants under shared public variable names."
            )
        frame, warnings = derive_tiam_h_dri_hydrogen(
            frame,
            hydrogen_kg_per_tonne_steel=h_dri_hydrogen_kg_per_tonne_steel,
        )
        report.warnings.extend(warnings)
        if TIAM_H_DRI_HYDROGEN in set(frame["Variable"].astype(str)):
            uses_default_intensity = math.isclose(
                h_dri_hydrogen_kg_per_tonne_steel,
                TIAM_DEFAULT_H_DRI_HYDROGEN_KG_PER_TONNE_STEEL,
                rel_tol=0,
                abs_tol=1e-12,
            )
            report.derived_variables.append(TIAM_H_DRI_HYDROGEN)
            report.assumptions["tiam_ucl_h_dri_hydrogen"] = {
                "method": (
                    "Multiply reported regional H-DRI/EAF finished-steel production "
                    "by an explicit hydrogen intensity and convert the result to PJ/yr "
                    "using the hydrogen lower heating value."
                ),
                "hydrogen_kg_per_tonne_steel": h_dri_hydrogen_kg_per_tonne_steel,
                "hydrogen_lhv_gj_per_tonne": TIAM_H2_LHV_GJ_PER_TONNE,
                "hydrogen_pj_per_mt_steel": (
                    h_dri_hydrogen_kg_per_tonne_steel * TIAM_H2_LHV_GJ_PER_TONNE / 1_000
                ),
                "intensity_source": (
                    "premise H2-DRI/EAF inventory"
                    if uses_default_intensity
                    else "user-supplied override"
                ),
                "default_inventory_basis": {
                    "h_dri_pig_iron_kg_per_kg_steel": 1.061992,
                    "hydrogen_kg_per_kg_h_dri_pig_iron": 0.06264,
                },
                "interpretation": (
                    "Derived proxy; not an original TIAM-UCL reported final-energy "
                    "coordinate. The default is aligned with the premise H2-DRI/EAF "
                    "inventory."
                ),
                "references": [
                    "https://doi.org/10.1039/D5EE01356A",
                    "https://doi.org/10.3390/en13030758",
                ],
            }
        else:
            report.skipped_variables.append(TIAM_H_DRI_HYDROGEN)

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
