"""Validated, versioned REMIND asset and country-region registries."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .exceptions import DataValidationError
from .io import sha256_file

DATA = Path(__file__).parent / "data"


def _load(name):
    path = DATA / name
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise DataValidationError(f"Unsupported or malformed registry: {path}")
    return value, path


def load_remind_asset_registry():
    registry, path = _load("remind_stock_mappings.yaml")
    assets = registry.get("assets")
    if not isinstance(assets, dict) or not assets:
        raise DataValidationError("REMIND asset registry is empty.")
    aliases = set()
    for asset_id, asset in assets.items():
        if asset.get("sector") not in {"power", "transport"} or asset.get("hierarchy") != "leaf":
            raise DataValidationError(f"Invalid REMIND asset mapping: {asset_id}")
        names = [asset_id, *asset.get("aliases", [])]
        if aliases.intersection(names):
            raise DataValidationError(f"Duplicate REMIND asset id or alias: {asset_id}")
        aliases.update(names)
    return registry, path


def load_remind_region_crosswalk():
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
