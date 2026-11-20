"""Reproduce the inventory audit of the REMIND stock-mapping study."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ...exceptions import DataValidationError
from ...io import read_frame, scenario_identity, validate_frame, write_csv_atomic, year_columns
from .registry import (
    REMIND_STOCK_NAMES,
    is_remind_model,
    load_remind_asset_registry,
    remind_stock_variable_names,
)
from .stock_config import AGGREGATE_REGIONS

CAPACITY_PREFIX = REMIND_STOCK_NAMES["capacity_prefix"]
TRANSPORT_PREFIX = REMIND_STOCK_NAMES["transport_prefix"]


def _pair(variable):
    """Find the corresponding additions variable for a stock variable."""
    if variable.startswith(CAPACITY_PREFIX):
        return "capacity", REMIND_STOCK_NAMES["capacity_additions_prefix"] + variable.removeprefix(
            CAPACITY_PREFIX
        )
    if variable.startswith(TRANSPORT_PREFIX):
        return "transport", REMIND_STOCK_NAMES[
            "transport_additions_prefix"
        ] + variable.removeprefix(TRANSPORT_PREFIX)
    return None


def _sector(variable):
    """Read the sector name from a REMIND stock variable."""
    if variable.startswith(TRANSPORT_PREFIX):
        return "transport"
    root = variable.removeprefix(CAPACITY_PREFIX).split("|", 1)[0]
    return root.lower().replace(" ", "_")


def _classification(variable, mapped, excluded, mapped_variables):
    """Describe how the research workflow treats this source variable."""
    if variable in mapped:
        asset_id, asset = mapped[variable]
        hierarchy = asset["hierarchy"]
        status = "mapped" if hierarchy == "leaf" else "mapped_aggregate_fallback"
        reason = (
            "reconstructed when the complete child layer is unavailable"
            if hierarchy == "aggregate"
            else "registered non-overlapping reconstruction asset"
        )
        return asset_id, hierarchy, status, reason
    if variable in excluded:
        item = excluded[variable]
        return None, None, item["status"], item["reason"]
    descendants = [
        candidate for candidate in mapped_variables if candidate.startswith(variable + "|")
    ]
    ancestors = [
        candidate for candidate in mapped_variables if variable.startswith(candidate + "|")
    ]
    if descendants:
        return None, None, "reporting_aggregate", "overlaps registered descendant assets"
    if ancestors:
        return None, None, "below_selected_layer", "more detailed than the registered asset layer"
    if variable.startswith(TRANSPORT_PREFIX) and set(variable.split("|")).intersection(
        REMIND_STOCK_NAMES["transport_powertrain_totals"]
    ):
        return (
            None,
            None,
            "reporting_aggregate",
            "cross-cutting powertrain total overlaps registered vehicle-class assets",
        )
    return None, None, "unmapped", "no reviewed stock-vintage mapping"


def build_remind_stock_inventory(frame, *, regions=None, end_year=None):
    """Return one auditable row per REMIND Cap/New Cap or Stock/Sales pair."""
    validate_frame(frame)
    model, _ = scenario_identity(frame)
    if not is_remind_model(model):
        raise DataValidationError(f"The REMIND preset cannot be used with model {model!r}.")
    labels = year_columns(frame)
    end_year = min(int(labels[-1]), 2100) if end_year is None else end_year
    if not int(labels[0]) <= end_year <= int(labels[-1]):
        raise DataValidationError("Inventory end year is outside the IAM time horizon.")
    labels = [label for label in labels if int(label) <= end_year]
    available_regions = set(frame["Region"])
    selected_regions = (
        sorted(available_regions - AGGREGATE_REGIONS)
        if regions is None
        else list(dict.fromkeys(regions))
    )
    missing = set(selected_regions) - available_regions
    if missing:
        raise DataValidationError(f"Regions are absent from the scenario: {sorted(missing)}")

    registry, _ = load_remind_asset_registry()
    mapped = {
        remind_stock_variable_names(asset)[0]: (asset_id, asset)
        for asset_id, asset in registry["assets"].items()
    }
    excluded = registry.get("excluded_capacity_variables", {})
    variables = set(frame["Variable"])
    rows = []
    stock_variables = sorted(
        variable
        for variable in variables
        if variable.startswith((CAPACITY_PREFIX, TRANSPORT_PREFIX))
    )
    for stock_variable in stock_variables:
        kind, inflow_variable = _pair(stock_variable)
        asset_id, hierarchy, status, reason = _classification(
            stock_variable, mapped, excluded, mapped
        )
        asset = mapped.get(stock_variable, (None, None))[1]
        lifetime_variable = None
        if asset:
            _, inflow_variable, lifetime_variable = remind_stock_variable_names(asset)
        lifetime_available = lifetime_variable is None or lifetime_variable in variables
        inflow_available = inflow_variable in variables
        if status == "unmapped" and not inflow_available:
            status = "missing_inflow"
            reason = "stock-like reporting variable has no matching annual addition series"
        if asset and (not inflow_available or not lifetime_available):
            status = "missing_selector"
            reason = "registered mapping is incomplete in this scenario file"
        stock_rows = frame.loc[
            frame["Region"].isin(selected_regions) & frame["Variable"].eq(stock_variable)
        ]
        inflow_rows = frame.loc[
            frame["Region"].isin(selected_regions) & frame["Variable"].eq(inflow_variable)
        ]
        stock_regions = set(stock_rows["Region"])
        inflow_regions = set(inflow_rows["Region"])
        complete_regions = stock_regions & inflow_regions
        combined = pd.concat([stock_rows, inflow_rows], ignore_index=True)
        values = (
            combined[labels].apply(pd.to_numeric, errors="raise").to_numpy(float)
            if not combined.empty
            else np.empty((0, len(labels)))
        )
        active_by_year = (
            np.any(np.abs(values) > 1e-12, axis=0) if values.size else np.zeros(len(labels), bool)
        )
        nonzero_years = [
            int(label) for label, active in zip(labels, active_by_year, strict=True) if active
        ]
        active_regions = 0
        for region in complete_regions:
            region_rows = combined.loc[combined["Region"].eq(region), labels]
            if np.any(np.abs(region_rows.to_numpy(float)) > 1e-12):
                active_regions += 1
        stock_units = sorted(set(stock_rows["Unit"]))
        inflow_units = sorted(set(inflow_rows["Unit"]))
        maximum_stock = (
            float(np.max(np.abs(stock_rows[labels].to_numpy(float))))
            if not stock_rows.empty
            else 0.0
        )
        rows.append(
            {
                "kind": kind,
                "sector": asset["sector"] if asset else _sector(stock_variable),
                "asset": asset_id,
                "hierarchy": hierarchy,
                "status": status,
                "reason": reason,
                "stock_variable": stock_variable,
                "stock_unit": " | ".join(stock_units),
                "inflow_variable": inflow_variable,
                "inflow_unit": " | ".join(inflow_units),
                "lifetime_variable": lifetime_variable,
                "lifetime_available": lifetime_available,
                "inflow_available": inflow_available,
                "regions_requested": len(selected_regions),
                "regions_complete": len(complete_regions),
                "regions_active": active_regions,
                "first_nonzero_year": min(nonzero_years) if nonzero_years else None,
                "last_nonzero_year": max(nonzero_years) if nonzero_years else None,
                "maximum_stock": maximum_stock,
            }
        )
    return pd.DataFrame(rows)


def write_remind_stock_inventory(
    source, destination, *, regions=None, end_year=None, overwrite=False
):
    """Write the REMIND stock-pair audit as a semicolon-delimited CSV."""
    inventory = build_remind_stock_inventory(read_frame(source), regions=regions, end_year=end_year)
    return write_csv_atomic(inventory, Path(destination), overwrite=overwrite), inventory
