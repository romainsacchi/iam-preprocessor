"""Transport energy-to-service and IMAGE BEV-truck derivations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ...exceptions import DataValidationError
from ...io import year_columns
from ...variable_maps import variable_map
from .config import BEV_CLASSES, SecConfig

VARIABLES = variable_map("variables.yaml", package=__package__)
FINAL_TRANSPORT_PREFIX = VARIABLES["transport_energy_prefix"]
ENERGY_SERVICE_PREFIX = VARIABLES["transport_service_prefix"]
SERVICE_UNITS = VARIABLES["service_units"]
BEV = VARIABLES["bev_trucks"]


@dataclass
class DerivationSummary:
    """Variables and warnings produced by a transformation step."""

    derived_variables: list[str] = field(default_factory=list)
    skipped_variables: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalize_final_energy_units(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize PJ/yr final-energy rows to EJ/yr.

    IMAGE 3.4 transport rows are already expressed in EJ/yr, but the notebook
    attempted to support PJ/yr inputs as well. This function makes that behavior
    explicit before any energy-to-service calculation.
    """

    frame = data.copy()
    years = year_columns(frame)
    final_mask = (
        frame["Variable"].fillna("").astype(str).str.startswith(VARIABLES["final_energy_prefix"])
    )
    pj_mask = final_mask & frame["Unit"].eq("PJ/yr")
    if pj_mask.any():
        frame.loc[pj_mask, years] = (
            frame.loc[pj_mask, years].apply(pd.to_numeric, errors="raise") / 1000
        )
        frame.loc[pj_mask, "Unit"] = "EJ/yr"

    transport_mask = frame["Variable"].fillna("").astype(str).str.startswith(FINAL_TRANSPORT_PREFIX)
    unsupported = sorted(frame.loc[transport_mask & ~frame["Unit"].eq("EJ/yr"), "Unit"].unique())
    if unsupported:
        raise DataValidationError(
            "Unsupported final-energy transport units: " + ", ".join(map(str, unsupported))
        )
    return frame


def _service_key(variable: str) -> tuple[str | None, str | None]:
    """Split a variable name into its service type and more specific label."""
    parts = variable.split("|")
    for segment in SERVICE_UNITS:
        if segment in parts:
            index = parts.index(segment)
            return segment, "|".join(parts[index + 1 :])
    return None, None


def derive_transport_energy_services(
    data: pd.DataFrame,
    sec_config: SecConfig,
) -> tuple[pd.DataFrame, DerivationSummary]:
    """Derive configured transport services from final energy.

    The correct conversion from EJ/yr and MJ/service-km to billion service-km
    per year is a factor of 1,000. Variables without an explicit SEC mapping are
    retained unchanged and reported as skipped instead of being silently dropped.
    """

    frame = normalize_final_energy_units(data)
    years = year_columns(frame)
    candidates = frame[
        frame["Variable"].fillna("").astype(str).str.startswith(FINAL_TRANSPORT_PREFIX)
    ]
    existing = {
        (row.Model, row.Scenario, row.Region, row.Variable)
        for row in frame[["Model", "Scenario", "Region", "Variable"]].itertuples(index=False)
    }
    rows: list[pd.Series] = []
    summary = DerivationSummary()

    for _, row in candidates.iterrows():
        variable = str(row["Variable"])
        category, key = _service_key(variable)
        if key not in sec_config.transport_sec_mj_per_service_km:
            summary.skipped_variables.append(variable)
            continue
        target = ENERGY_SERVICE_PREFIX + variable.removeprefix(FINAL_TRANSPORT_PREFIX)
        identity = (row["Model"], row["Scenario"], row["Region"], target)
        if identity in existing:
            summary.skipped_variables.append(target)
            continue
        sec = sec_config.transport_sec_mj_per_service_km[key]
        derived = row.copy()
        derived["Variable"] = target
        derived["Unit"] = SERVICE_UNITS[category]
        values = pd.to_numeric(row[years], errors="raise").astype(float)
        derived[years] = values * 1000 / sec
        rows.append(derived)
        existing.add(identity)
        summary.derived_variables.append(target)

    if rows:
        frame = pd.concat([frame, pd.DataFrame(rows)], ignore_index=True)
    summary.derived_variables = sorted(set(summary.derived_variables))
    summary.skipped_variables = sorted(set(summary.skipped_variables))
    return frame, summary


def _one_row(group: pd.DataFrame, variable: str, identity: str) -> pd.Series:
    """Return the only row for a variable within one scenario and region."""
    matches = group.loc[group["Variable"].eq(variable)]
    if len(matches) != 1:
        raise DataValidationError(
            f"Expected exactly one row for {variable!r} in {identity}; found {len(matches)}."
        )
    return matches.iloc[0]


def _plug_in_electricity(group, truck_class, year_labels, identity):
    """Estimate plug-in hybrid truck electricity use in EJ per year."""
    electricity = np.zeros(len(year_labels), dtype=float)
    for distance in BEV["plug_in_ranges"]:
        efficiency_variable = BEV["plug_in_efficiency"].format(truck=truck_class, distance=distance)
        efficiency = pd.to_numeric(
            _one_row(group, efficiency_variable, identity)[year_labels], errors="raise"
        ).to_numpy(dtype=float)
        activity = np.zeros(len(year_labels), dtype=float)
        for fuel in BEV["plug_in_fuels"]:
            service_variable = BEV["plug_in_service"].format(
                truck=truck_class, distance=distance, fuel=fuel
            )
            activity += pd.to_numeric(
                _one_row(group, service_variable, identity)[year_labels], errors="raise"
            ).to_numpy(dtype=float)
        electricity += activity * efficiency / 1000
    return electricity


def derive_bev_truck_variables(
    data: pd.DataFrame,
    sec_config: SecConfig,
    *,
    strict: bool = False,
) -> tuple[pd.DataFrame, DerivationSummary]:
    """Derive IMAGE medium/heavy BEV service from the truck-electricity residual.

    Reported truck electricity is reduced by electricity reconstructed from the
    10/30/60 km plug-in hybrid variants. The remaining final energy is divided by
    an explicit full-BEV SEC supplied by the caller. World values are sums of the
    derived regional rows because IMAGE lacks World PHEV efficiency rows.
    """

    sec_config.require_bev_trucks()
    frame = normalize_final_energy_units(data)
    years = year_columns(frame)
    summary = DerivationSummary()
    appended: list[pd.Series] = []
    negative_stats: dict[str, list[float]] = defaultdict(list)

    existing_variables = set(frame["Variable"].astype(str))
    for truck_class in BEV_CLASSES:
        service_target = BEV["service"].format(truck=truck_class)
        energy_target = BEV["electricity"].format(truck=truck_class)
        duplicates = existing_variables.intersection({service_target, energy_target})
        if duplicates:
            raise DataValidationError(
                "Derived BEV variables already exist: " + ", ".join(sorted(duplicates))
            )

        total_variable = BEV["total_electricity"].format(truck=truck_class)
        total_rows = frame.loc[frame["Variable"].eq(total_variable)]
        if total_rows.empty:
            raise DataValidationError(f"Required IMAGE variable is missing: {total_variable}")

        regional_totals: dict[tuple[str, str], dict[str, np.ndarray]] = defaultdict(
            lambda: {
                "service": np.zeros(len(years), dtype=float),
                "energy": np.zeros(len(years), dtype=float),
            }
        )

        for _, total_row in total_rows.loc[
            ~total_rows["Region"].eq(VARIABLES["global_region"])
        ].iterrows():
            model = str(total_row["Model"])
            scenario = str(total_row["Scenario"])
            region = str(total_row["Region"])
            identity = f"{model}/{scenario}/{region}"
            group = frame.loc[
                frame["Model"].eq(total_row["Model"])
                & frame["Scenario"].eq(total_row["Scenario"])
                & frame["Region"].eq(total_row["Region"])
            ]
            total = pd.to_numeric(total_row[years], errors="raise").to_numpy(dtype=float)
            plug_in = _plug_in_electricity(group, truck_class, years, identity)

            # Total truck electricity includes plug-in hybrids and battery-only trucks.
            residual = total - plug_in
            material_negative = residual < -sec_config.negative_residual_tolerance_ej
            if material_negative.any():
                negative_stats[truck_class].extend(residual[material_negative].tolist())
                if strict:
                    minimum = residual[material_negative].min()
                    raise DataValidationError(
                        f"Negative {truck_class} BEV electricity residual in {identity}; "
                        f"minimum {minimum:.6g} EJ."
                    )
            residual = np.maximum(residual, 0)
            service = residual * 1000 / sec_config.bev_truck_sec_mj_per_tkm[truck_class]

            energy_row = total_row.copy()
            energy_row["Variable"] = energy_target
            energy_row["Unit"] = "EJ/yr"
            energy_row[years] = residual
            appended.append(energy_row)

            service_row = total_row.copy()
            service_row["Variable"] = service_target
            service_row["Unit"] = SERVICE_UNITS[BEV["service_category"]]
            service_row[years] = service
            appended.append(service_row)

            aggregate = regional_totals[(model, scenario)]
            aggregate["energy"] += residual
            aggregate["service"] += service

        # Rebuild the global total from the corrected regional values.
        for (model, scenario), aggregate in regional_totals.items():
            world_template = total_rows.loc[
                total_rows["Model"].eq(model)
                & total_rows["Scenario"].eq(scenario)
                & total_rows["Region"].eq(VARIABLES["global_region"])
            ]
            if world_template.empty:
                continue
            template = world_template.iloc[0]
            for target, unit, values in (
                (energy_target, "EJ/yr", aggregate["energy"]),
                (service_target, SERVICE_UNITS[BEV["service_category"]], aggregate["service"]),
            ):
                world_row = template.copy()
                world_row["Variable"] = target
                world_row["Unit"] = unit
                world_row[years] = values
                appended.append(world_row)

        summary.derived_variables.extend([service_target, energy_target])

    for truck_class, negatives in sorted(negative_stats.items()):
        summary.warnings.append(
            f"Clipped {len(negatives)} material negative {truck_class} BEV residuals; "
            f"minimum {min(negatives):.6g} EJ."
        )
    if appended:
        frame = pd.concat([frame, pd.DataFrame(appended)], ignore_index=True)
    summary.derived_variables = sorted(set(summary.derived_variables))
    return frame, summary
