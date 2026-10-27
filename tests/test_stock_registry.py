from copy import deepcopy

import pytest

from iam_preprocessor.exceptions import DataValidationError
from iam_preprocessor.stock_registry import (
    load_remind_asset_registry,
    load_remind_region_crosswalk,
    registry_provenance,
)


def test_asset_registry_contains_named_hierarchy_mappings():
    registry, _ = load_remind_asset_registry()
    assets = registry["assets"]
    assert {row["sector"] for row in assets.values()} == {"power", "storage", "transport"}
    assert {row["hierarchy"] for row in assets.values()} == {"leaf", "aggregate"}
    assert assets["pv"]["stock_suffix"] == "Solar|+|PV"
    assert assets["passenger-ldv-4w"]["service_life"] == 20
    assert assets["passenger-ldv-4w-bev"]["parent"] == "passenger-ldv-4w"
    assert assets["battery-pv"]["stock_variable"] == ("Cap|Electricity|Storage|Battery|For PV")
    assert registry_provenance()["asset_mapping"]["sha256"]


def test_eu21_country_crosswalk_keeps_uki_aggregate_explicit():
    crosswalk, _ = load_remind_region_crosswalk()
    assert crosswalk["regions"]["DEU"]["countries"] == ["DEU"]
    assert crosswalk["regions"]["FRA"]["countries"] == ["FRA"]
    assert crosswalk["regions"]["UKI"]["countries"] == ["GBR", "IRL"]


def test_crosswalk_validator_rejects_overlapping_country(monkeypatch):
    import iam_preprocessor.stock_registry as module

    original = module._load

    def bad(name):
        value, path = original(name)
        value = deepcopy(value)
        if name == "remind_regions.yaml":
            value["regions"]["FRA"]["countries"] = ["GBR"]
        return value, path

    monkeypatch.setattr(module, "_load", bad)
    with pytest.raises(DataValidationError, match="overlaps"):
        module.load_remind_region_crosswalk()
