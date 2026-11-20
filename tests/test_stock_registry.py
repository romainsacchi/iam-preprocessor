from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from iam_preprocessor.exceptions import DataValidationError
from iam_preprocessor.research.remind.registry import (
    load_remind_asset_registry,
    load_remind_region_crosswalk,
    registry_provenance,
    remind_stock_variable_names,
)
from iam_preprocessor.stock_config import validate_stock_config


def test_asset_registry_contains_named_hierarchy_mappings():
    registry, _ = load_remind_asset_registry()
    assets = registry["assets"]
    assert {row["sector"] for row in assets.values()} == {
        "carbon_management",
        "gases",
        "heat",
        "hydrogen",
        "liquids",
        "power",
        "storage",
        "transport",
    }
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


def test_remind_example_uses_the_reviewed_variable_names():
    path = Path(__file__).resolve().parents[1] / "examples" / "stock-mapping-remind.yaml"
    config = yaml.safe_load(path.read_text())
    assert len(config["assets"]) == 53
    assert (config["reference_year"], config["end_year"]) == (2005, 2100)
    config.update(model="REMIND", scenario="test")
    for asset in config["assets"]:
        assert "region" not in asset
        asset["region"] = "test region"
    validate_stock_config(config, source=path)

    catalogue, _ = load_remind_asset_registry()
    for asset in config["assets"]:
        entry = catalogue["assets"][asset["id"]]
        stock, additions, lifetime = remind_stock_variable_names(entry)
        assert entry["hierarchy"] == "leaf"
        assert asset["stock"] == {"variable": stock, "unit": entry["stock_unit"]}
        assert asset["inflow"] == {"variable": additions, "unit": entry["inflow_unit"]}
        if lifetime is None:
            assert asset["lifetime"]["mean"] == entry["service_life"]
        else:
            assert asset["lifetime"]["source"] == {"variable": lifetime, "unit": "years"}


def test_crosswalk_validator_rejects_overlapping_country(monkeypatch):
    from iam_preprocessor.research.remind import registry as module

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
