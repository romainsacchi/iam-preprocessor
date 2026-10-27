"""Build stock-vintage configurations from native REMIND variable contracts."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .exceptions import DataValidationError, IamPreprocessorError
from .io import read_frame, validate_frame, year_columns
from .stock_registry import load_remind_asset_registry, registry_provenance

AGGREGATE_REGIONS = {"World", "EUR", "EU27", "NEU"}


def _identity(frame):
    identity = frame[["Model", "Scenario"]].drop_duplicates().to_records(index=False).tolist()
    if len(identity) != 1 or identity[0][0] != "REMIND":
        raise DataValidationError("Expected one REMIND model/scenario in the input file.")
    return identity[0]


def _row(frame, region, variable, unit):
    selected = frame.loc[
        frame["Region"].eq(region) & frame["Variable"].eq(variable) & frame["Unit"].eq(unit)
    ]
    if len(selected) != 1:
        return None
    return selected.iloc[0]


def _value_at(row, reference_year, labels):
    values = pd.to_numeric(row[labels], errors="raise").to_numpy(float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise DataValidationError("Lifetime series must be finite and positive.")
    return float(np.interp(reference_year, list(map(int, labels)), values))


def _common_asset(
    asset_id, region, stock, inflow, lifetime, maximum_age, base_year, reference_year
):
    if base_year < reference_year:
        initial = {
            "kind": "warm_start",
            "base_kind": "equilibrium",
            "base_year": base_year,
            "maximum_age": maximum_age,
            "acknowledge_prior": True,
            "provenance": "Stationary historical-inflow legacy prior at the first IAM year, "
            "advanced to the reference year using IAM stocks and additions.",
        }
    else:
        initial = {
            "kind": "equilibrium",
            "maximum_age": maximum_age,
            "acknowledge_prior": True,
            "provenance": "Stationary historical-inflow prior at the first scenario year; "
            "no region-specific opening vintage observations were supplied.",
        }
    return {
        "id": asset_id,
        "region": region,
        "stock": stock,
        "inflow": inflow,
        "inflow_timing": {
            "kind": "sampled_annual",
            "provenance": "REMIND Cap/New Cap and Stock/Sales definition: each reported value "
            "is the annual value in that year; missing annual values are linearly interpolated.",
        },
        "lifetime": lifetime,
        "initial": initial,
        "mode": "stock_flow",
        "exit_policy": "error",
        "service_weighting": {
            "kind": "equal",
            "annual_age_decay": 0,
            "provenance": "Equal service per surviving unit; vintage stock composition only.",
        },
    }


def build_remind_stock_config(
    frame,
    *,
    regions=None,
    reference_year=None,
    end_year=None,
    include_power=True,
    include_transport=True,
):
    """Return a validated-shape configuration for individual REMIND regions.

    Missing asset families are skipped, allowing the same builder to work with
    REMIND exports that omit two- and three-wheel vehicle stocks. A requested
    region itself is never silently skipped.
    """
    validate_frame(frame)
    model, scenario = _identity(frame)
    labels = year_columns(frame)
    anchors = list(map(int, labels))
    reference_year = anchors[0] if reference_year is None else reference_year
    end_year = min(anchors[-1], 2100) if end_year is None else end_year
    if reference_year not in range(anchors[0], anchors[-1] + 1):
        raise DataValidationError("Reference year is outside the IAM time horizon.")
    if not reference_year < end_year <= min(anchors[-1], 2100):
        raise DataValidationError("End year must follow the reference year and not exceed 2100.")
    available = set(frame["Region"].unique())
    selected_regions = (
        sorted(available - AGGREGATE_REGIONS) if regions is None else list(dict.fromkeys(regions))
    )
    if not selected_regions:
        raise DataValidationError("No individual REMIND regions were selected.")
    missing_regions = set(selected_regions) - available
    if missing_regions:
        raise DataValidationError(
            f"Regions are absent from the scenario: {sorted(missing_regions)}"
        )
    if not include_power and not include_transport:
        raise DataValidationError("Select at least one power or transport asset family.")

    assets = []
    skipped = []
    mappings, _ = load_remind_asset_registry()
    power_assets = {
        key: value for key, value in mappings["assets"].items() if value["sector"] == "power"
    }
    transport_assets = {
        key: value for key, value in mappings["assets"].items() if value["sector"] == "transport"
    }
    for region in selected_regions:
        if include_power:
            for asset_id, mapping in power_assets.items():
                stock = {
                    "variable": f"Cap|Electricity|{mapping['stock_suffix']}",
                    "unit": mapping["stock_unit"],
                }
                inflow = {
                    "variable": f"New Cap|Electricity|{mapping['inflow_suffix']}",
                    "unit": mapping["inflow_unit"],
                }
                source = {
                    "variable": f"Tech|Electricity|{mapping['lifetime_suffix']}|Lifetime",
                    "unit": "years",
                }
                rows = (
                    _row(frame, region, stock["variable"], stock["unit"]),
                    _row(frame, region, inflow["variable"], inflow["unit"]),
                    _row(frame, region, source["variable"], source["unit"]),
                )
                if any(row is None for row in rows):
                    skipped.append(
                        {"asset": asset_id, "region": region, "reason": "missing selector"}
                    )
                    continue
                maximum = _value_at(rows[2], anchors[0], labels)
                maximum_age = math.ceil(maximum)
                if maximum_age > 150:
                    raise DataValidationError(
                        f"{asset_id}/{region}: opening maximum lifetime exceeds 150 years."
                    )
                lifetime = {
                    "distribution": "remind",
                    "initial_maximum": maximum,
                    "source": source,
                    "interpretation": "REMIND energy-conversion maximum lifetime tau; survival "
                    "is max(0, 1 - (age/tau)^4) and mean lifetime is 4*tau/5.",
                    "provenance": "Technical note: Lifetimes in REMIND (2026-03-23).",
                }
                assets.append(
                    _common_asset(
                        asset_id,
                        region,
                        stock,
                        inflow,
                        lifetime,
                        maximum_age,
                        anchors[0],
                        reference_year,
                    )
                )
        if include_transport:
            for asset_id, mapping in transport_assets.items():
                variable_suffix = mapping["variable_suffix"]
                service_life = mapping["service_life"]
                stock = {
                    "variable": f"Stock|Transport|{variable_suffix}",
                    "unit": mapping["stock_unit"],
                }
                inflow = {
                    "variable": f"Sales|Transport|{variable_suffix}",
                    "unit": mapping["inflow_unit"],
                }
                if any(
                    _row(frame, region, selector["variable"], selector["unit"]) is None
                    for selector in (stock, inflow)
                ):
                    skipped.append(
                        {"asset": asset_id, "region": region, "reason": "missing selector"}
                    )
                    continue
                lifetime = {
                    "distribution": "fixed",
                    "initial_mean": service_life,
                    "mean": service_life,
                    "interpretation": "REMIND transport serviceLife used as a deterministic "
                    "retirement age because no vehicle survival distribution was disclosed.",
                    "provenance": "REMIND transportPol5cen FVvehvar serviceLife values supplied "
                    "for this work. The accompanying interest rate is financial and is not used "
                    "as a physical survival parameter.",
                }
                assets.append(
                    _common_asset(
                        asset_id,
                        region,
                        stock,
                        inflow,
                        lifetime,
                        service_life,
                        anchors[0],
                        reference_year,
                    )
                )
    if not assets:
        raise DataValidationError("No complete stock/inflow/lifetime asset mappings were found.")
    config = {
        "schema_version": 2,
        "model": model,
        "scenario": scenario,
        "reference_year": reference_year,
        "end_year": end_year,
        "registries": registry_provenance(),
        "assets": assets,
    }
    return config, skipped


def write_remind_stock_config(
    source,
    destination,
    *,
    regions=None,
    reference_year=None,
    end_year=None,
    include_power=True,
    include_transport=True,
    overwrite=False,
):
    """Build and write a REMIND stock-vintage YAML configuration."""
    destination = Path(destination)
    if destination.exists() and not overwrite:
        raise IamPreprocessorError(
            f"Output already exists: {destination}. Use --overwrite to replace it."
        )
    config, skipped = build_remind_stock_config(
        read_frame(source),
        regions=regions,
        reference_year=reference_year,
        end_year=end_year,
        include_power=include_power,
        include_transport=include_transport,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return destination, config, skipped
