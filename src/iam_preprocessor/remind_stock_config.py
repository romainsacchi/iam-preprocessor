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


def _transport_selectors(mapping):
    suffix = mapping["variable_suffix"]
    return (
        {
            "variable": f"Stock|Transport|{suffix}",
            "unit": mapping["stock_unit"],
        },
        {
            "variable": f"Sales|Transport|{suffix}",
            "unit": mapping["inflow_unit"],
        },
    )


def _selectors_available(frame, region, selectors):
    return all(
        _row(frame, region, selector["variable"], selector["unit"]) is not None
        for selector in selectors
    )


def _capacity_selectors(mapping):
    if "stock_variable" in mapping:
        return (
            {"variable": mapping["stock_variable"], "unit": mapping["stock_unit"]},
            {"variable": mapping["inflow_variable"], "unit": mapping["inflow_unit"]},
            {"variable": mapping["lifetime_variable"], "unit": "years"},
        )
    return (
        {
            "variable": f"Cap|Electricity|{mapping['stock_suffix']}",
            "unit": mapping["stock_unit"],
        },
        {
            "variable": f"New Cap|Electricity|{mapping['inflow_suffix']}",
            "unit": mapping["inflow_unit"],
        },
        {
            "variable": f"Tech|Electricity|{mapping['lifetime_suffix']}|Lifetime",
            "unit": "years",
        },
    )


def _zero_only(rows, labels, end_year):
    selected = [label for label in labels if int(label) <= end_year]
    return all(
        np.allclose(
            pd.to_numeric(row[selected], errors="raise").to_numpy(float),
            0,
            rtol=0,
            atol=1e-12,
        )
        for row in rows
    )


def _children_match_parent(frame, region, parent, children, labels):
    """Return whether child Stock/Sales series partition their reporting parent."""
    for selector_index in (0, 1):
        parent_selector = _transport_selectors(parent)[selector_index]
        parent_row = _row(frame, region, parent_selector["variable"], parent_selector["unit"])
        if parent_row is None:
            continue
        child_rows = []
        for child in children:
            selector = _transport_selectors(child)[selector_index]
            row = _row(frame, region, selector["variable"], selector["unit"])
            if row is None:
                return False
            child_rows.append(pd.to_numeric(row[labels], errors="raise").to_numpy(float))
        parent_values = pd.to_numeric(parent_row[labels], errors="raise").to_numpy(float)
        if not np.allclose(np.sum(child_rows, axis=0), parent_values, rtol=1e-8, atol=1e-7):
            return False
    return True


def _select_transport_assets(frame, region, mappings, labels):
    """Choose a non-overlapping transport layer, with aggregate fallbacks."""
    selected = []
    skipped = []
    child_ids = {child for row in mappings.values() for child in row.get("children", [])}
    for asset_id, mapping in mappings.items():
        if asset_id in child_ids or mapping["hierarchy"] != "aggregate":
            continue
        children = [(child, mappings[child]) for child in mapping["children"]]
        complete_children = all(
            _selectors_available(frame, region, _transport_selectors(child))
            for _, child in children
        )
        parent_available = _selectors_available(frame, region, _transport_selectors(mapping))
        hierarchy_matches = complete_children and _children_match_parent(
            frame, region, mapping, [child for _, child in children], labels
        )
        if complete_children and (not parent_available or hierarchy_matches):
            selected.extend(children)
            skipped.append(
                {
                    "asset": asset_id,
                    "region": region,
                    "reason": "replaced by complete children",
                }
            )
        elif parent_available:
            selected.append((asset_id, mapping))
            reason = (
                "parent-child hierarchy mismatch"
                if complete_children
                else "aggregate fallback; incomplete children"
            )
            skipped.extend(
                {"asset": child_id, "region": region, "reason": reason} for child_id, _ in children
            )
        else:
            skipped.append({"asset": asset_id, "region": region, "reason": "missing selector"})
            skipped.extend(
                {"asset": child_id, "region": region, "reason": "missing selector"}
                for child_id, _ in children
            )
    for asset_id, mapping in mappings.items():
        if asset_id in child_ids or mapping["hierarchy"] == "aggregate":
            continue
        if _selectors_available(frame, region, _transport_selectors(mapping)):
            selected.append((asset_id, mapping))
        else:
            skipped.append({"asset": asset_id, "region": region, "reason": "missing selector"})
    return selected, skipped


def _common_asset(
    asset_id,
    region,
    stock,
    inflow,
    lifetime,
    maximum_age,
    base_year,
    reference_year,
    reconciliation,
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
    result = {
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
        "mode": "stock_flow" if reconciliation == "strict" else "joint",
        "exit_policy": "error" if reconciliation == "strict" else "proportional",
        "service_weighting": {
            "kind": "equal",
            "annual_age_decay": 0,
            "provenance": "Equal service per surviving unit; vintage stock composition only.",
        },
    }
    if reconciliation == "joint":
        result["annualisation"] = {
            "inflow_constraints": "penalized",
            "reference_weight": 0.01,
            "inflow_weight": 10,
            "provenance": "Diagnostic reconciliation: preserve IAM stock anchors and adjust "
            "annual additions minimally when stock, additions and survival are inconsistent.",
        }
    return result


def build_remind_stock_config(
    frame,
    *,
    regions=None,
    reference_year=None,
    end_year=None,
    include_power=True,
    include_transport=True,
    include_conversion=True,
    reconciliation="strict",
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
    if not any((include_power, include_transport, include_conversion)):
        raise DataValidationError("Select at least one stock asset family.")
    if reconciliation not in {"strict", "joint"}:
        raise DataValidationError("reconciliation must be strict or joint.")

    assets = []
    skipped = []
    mappings, _ = load_remind_asset_registry()
    capacity_assets = {
        key: value
        for key, value in mappings["assets"].items()
        if value["sector"] != "transport"
        and (
            (include_power and value["sector"] == "power")
            or (include_conversion and value["sector"] != "power")
        )
    }
    transport_assets = {
        key: value for key, value in mappings["assets"].items() if value["sector"] == "transport"
    }
    for region in selected_regions:
        for asset_id, mapping in capacity_assets.items():
            stock, inflow, source = _capacity_selectors(mapping)
            rows = (
                _row(frame, region, stock["variable"], stock["unit"]),
                _row(frame, region, inflow["variable"], inflow["unit"]),
                _row(frame, region, source["variable"], source["unit"]),
            )
            if any(row is None for row in rows):
                skipped.append({"asset": asset_id, "region": region, "reason": "missing selector"})
                continue
            if _zero_only(rows[:2], labels, end_year):
                skipped.append({"asset": asset_id, "region": region, "reason": "zero only"})
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
                    reconciliation,
                )
            )
        if include_transport:
            selected_transport, transport_skipped = _select_transport_assets(
                frame, region, transport_assets, labels
            )
            skipped.extend(transport_skipped)
            for asset_id, mapping in selected_transport:
                service_life = mapping["service_life"]
                stock, inflow = _transport_selectors(mapping)
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
                        reconciliation,
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
    include_conversion=True,
    reconciliation="strict",
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
        include_conversion=include_conversion,
        reconciliation=reconciliation,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return destination, config, skipped
