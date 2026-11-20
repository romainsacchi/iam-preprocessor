"""Versioned asset and regional crosswalks for the REMIND research runs."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from ...exceptions import DataValidationError
from ...io import sha256_file
from ...variable_maps import variable_map

DATA = Path(__file__).parent / "data"
REMIND_STOCK_NAMES = variable_map("stock_variables.yaml", package=__package__)
ASSET_SECTORS = {
    "carbon_management",
    "gases",
    "heat",
    "hydrogen",
    "liquids",
    "power",
    "storage",
    "transport",
}


def _load(name):
    """Read a versioned REMIND research YAML file and return its path."""
    path = DATA / name
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise DataValidationError(f"Unsupported or malformed registry: {path}")
    return value, path


def is_remind_model(model):
    """Match the model family while preserving the scenario table's original label."""
    return bool(re.match(r"^remind(?=$|[0-9\s._-])", model.strip(), re.IGNORECASE))


def remind_stock_variable_names(asset):
    """Resolve a REMIND registry entry to stock, addition and lifetime row names."""
    names = REMIND_STOCK_NAMES
    if asset["sector"] == "transport":
        return (
            names["transport_prefix"] + asset["variable_suffix"],
            names["transport_additions_prefix"] + asset["variable_suffix"],
            None,
        )
    if "stock_variable" in asset:
        return asset["stock_variable"], asset["inflow_variable"], asset["lifetime_variable"]
    return (
        names["power_stock"].format(suffix=asset["stock_suffix"]),
        names["power_additions"].format(suffix=asset["inflow_suffix"]),
        names["power_lifetime"].format(suffix=asset["lifetime_suffix"]),
    )


def load_remind_asset_registry():
    """Read and check the REMIND asset mappings used in the research examples."""
    registry, path = _load("remind_stock_mappings.yaml")
    assets = registry.get("assets")
    if not isinstance(assets, dict) or not assets:
        raise DataValidationError("REMIND asset registry is empty.")
    aliases = set()
    for asset_id, asset in assets.items():
        hierarchy = asset.get("hierarchy")
        if asset.get("sector") not in ASSET_SECTORS or hierarchy not in {"leaf", "aggregate"}:
            raise DataValidationError(f"Invalid REMIND asset mapping: {asset_id}")
        if not isinstance(asset.get("aliases"), list) or not all(
            isinstance(alias, str) and alias for alias in asset["aliases"]
        ):
            raise DataValidationError(f"Invalid aliases for REMIND asset: {asset_id}")
        required = {"stock_unit", "inflow_unit", "capacity_basis"}
        if not required.issubset(asset) or not all(
            isinstance(asset[field], str) and asset[field] for field in required
        ):
            raise DataValidationError(f"Incomplete REMIND asset mapping: {asset_id}")
        if asset["sector"] == "transport":
            if not isinstance(asset.get("variable_suffix"), str) or not isinstance(
                asset.get("service_life"), (int, float)
            ):
                raise DataValidationError(f"Incomplete transport mapping: {asset_id}")
        else:
            exact = {"stock_variable", "inflow_variable", "lifetime_variable"}
            legacy = {"stock_suffix", "inflow_suffix", "lifetime_suffix"}
            if not (exact.issubset(asset) ^ legacy.issubset(asset)):
                raise DataValidationError(f"Incomplete capacity mapping: {asset_id}")
        if hierarchy == "aggregate" and not asset.get("children"):
            raise DataValidationError(f"Aggregate REMIND asset has no children: {asset_id}")
        if hierarchy == "leaf" and asset.get("children"):
            raise DataValidationError(f"Leaf REMIND asset has children: {asset_id}")
        names = [asset_id, *asset.get("aliases", [])]
        if aliases.intersection(names):
            raise DataValidationError(f"Duplicate REMIND asset id or alias: {asset_id}")
        aliases.update(names)
    for asset_id, asset in assets.items():
        parent = asset.get("parent")
        if parent is not None:
            if parent not in assets or asset_id not in assets[parent].get("children", []):
                raise DataValidationError(f"Invalid parent for REMIND asset: {asset_id}")
            if assets[parent].get("sector") != asset.get("sector"):
                raise DataValidationError(f"Cross-sector parent for REMIND asset: {asset_id}")
        for child in asset.get("children", []):
            if child not in assets or assets[child].get("parent") != asset_id:
                raise DataValidationError(f"Invalid child for REMIND asset: {asset_id}/{child}")
    excluded = registry.get("excluded_capacity_variables", {})
    if not isinstance(excluded, dict):
        raise DataValidationError("REMIND capacity exclusions must be a mapping.")
    mapped_capacity = {
        remind_stock_variable_names(asset)[0]
        for asset in assets.values()
        if asset["sector"] != "transport"
    }
    for variable, metadata in excluded.items():
        if variable in mapped_capacity or not variable.startswith(
            REMIND_STOCK_NAMES["capacity_prefix"]
        ):
            raise DataValidationError(f"Invalid REMIND capacity exclusion: {variable}")
        if not isinstance(metadata, dict) or metadata.get("status") not in {
            "ambiguous_lifetime",
            "missing_lifetime",
            "reporting_aggregate",
        }:
            raise DataValidationError(f"Invalid REMIND capacity exclusion: {variable}")
        if not isinstance(metadata.get("reason"), str) or not metadata["reason"]:
            raise DataValidationError(f"Missing REMIND capacity exclusion reason: {variable}")
    return registry, path


def load_remind_region_crosswalk():
    """Read and check the REMIND region names used to match outside evidence."""
    crosswalk, path = _load("remind_regions.yaml")
    regions = crosswalk.get("regions")
    if not isinstance(regions, dict) or not regions:
        raise DataValidationError("REMIND region crosswalk is empty.")
    owners = {}
    for region, metadata in regions.items():
        countries = metadata.get("countries")
        if not countries or len(countries) != len(set(countries)):
            raise DataValidationError(f"Missing or duplicate countries for REMIND region {region}.")
        for country in countries:
            if not isinstance(country, str) or not re.fullmatch(r"[A-Z]{3}", country):
                raise DataValidationError(f"Invalid ISO3 code in REMIND region {region}.")
            if country in owners:
                raise DataValidationError(
                    f"Country {country} overlaps REMIND regions {owners[country]} and {region}."
                )
            owners[country] = region
    return crosswalk, path


def registry_provenance():
    """Return the file details needed to identify the REMIND research mappings."""
    assets, asset_path = load_remind_asset_registry()
    regions, region_path = load_remind_region_crosswalk()
    return {
        "asset_mapping": {
            "schema_version": assets["schema_version"],
            "sha256": sha256_file(asset_path),
        },
        "region_crosswalk": {
            "schema_version": regions["schema_version"],
            "mapping": regions["mapping"],
            "sha256": sha256_file(region_path),
        },
    }


def load_evidence_registry():
    """Load the asset crosswalk used by the historical evidence campaign."""
    return variable_map("remind_stock_assets.yaml", package=__package__)["assets"]
