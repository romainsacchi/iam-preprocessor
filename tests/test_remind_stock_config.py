import pandas as pd
import pytest

from iam_preprocessor.exceptions import DataValidationError
from iam_preprocessor.remind_stock_config import build_remind_stock_config
from iam_preprocessor.stock_config import load_stock_config


def frame():
    rows = []

    def add(region, variable, unit, a, b):
        rows.append(
            {
                "Model": "REMIND",
                "Scenario": "SSP2-EU21-NPi2025",
                "Region": region,
                "Variable": variable,
                "Unit": unit,
                "2005": a,
                "2010": b,
            }
        )

    for region in ("DEU", "FRA", "World"):
        add(region, "Cap|Electricity|Solar|+|PV", "GW", 1, 2)
        add(region, "New Cap|Electricity|Solar|+|PV", "GW/yr", 0.1, 0.2)
        add(region, "Tech|Electricity|Solar|PV|Lifetime", "years", 30, 35)
        add(region, "Stock|Transport|Pass|Road|LDV|Four Wheelers", "million veh", 4, 5)
        add(region, "Sales|Transport|Pass|Road|LDV|Four Wheelers", "million veh", 0.4, 0.5)
    return pd.DataFrame(rows)


def frame_with_transport_children(*, mismatch=False):
    result = frame()
    rows = []
    shares = {
        "BEV": 0.1,
        "FCEV": 0.1,
        "Gases": 0.2,
        "Hybrid electric": 0.2,
        "Liquids": 0.4,
    }
    for region in ("DEU", "FRA", "World"):
        for fuel, share in shares.items():
            if mismatch and fuel == "BEV":
                share += 0.1
            rows.extend(
                [
                    {
                        "Model": "REMIND",
                        "Scenario": "SSP2-EU21-NPi2025",
                        "Region": region,
                        "Variable": "Stock|Transport|Pass|Road|LDV|Four Wheelers|" + fuel,
                        "Unit": "million veh",
                        "2005": 4 * share,
                        "2010": 5 * share,
                    },
                    {
                        "Model": "REMIND",
                        "Scenario": "SSP2-EU21-NPi2025",
                        "Region": region,
                        "Variable": "Sales|Transport|Pass|Road|LDV|Four Wheelers|" + fuel,
                        "Unit": "million veh",
                        "2005": 0.4 * share,
                        "2010": 0.5 * share,
                    },
                ]
            )
    return pd.concat([result, pd.DataFrame(rows)], ignore_index=True)


def test_builds_individual_region_power_and_transport_assets(tmp_path):
    config, skipped = build_remind_stock_config(frame(), regions=["DEU", "FRA"])
    assert config["reference_year"] == 2005
    assert config["end_year"] == 2010
    assert {(a["id"], a["region"]) for a in config["assets"]} == {
        ("pv", "DEU"),
        ("pv", "FRA"),
        ("passenger-ldv-4w", "DEU"),
        ("passenger-ldv-4w", "FRA"),
    }
    assert skipped
    power = next(a for a in config["assets"] if a["id"] == "pv")
    assert power["mode"] == "stock_flow"
    assert power["exit_policy"] == "error"
    assert power["inflow_timing"]["kind"] == "sampled_annual"
    assert power["lifetime"] == {
        "distribution": "remind",
        "initial_maximum": 30,
        "source": {
            "variable": "Tech|Electricity|Solar|PV|Lifetime",
            "unit": "years",
        },
        "interpretation": "REMIND energy-conversion maximum lifetime tau; survival is "
        "max(0, 1 - (age/tau)^4) and mean lifetime is 4*tau/5.",
        "provenance": "Technical note: Lifetimes in REMIND (2026-03-23).",
    }
    vehicle = next(a for a in config["assets"] if a["id"] == "passenger-ldv-4w")
    assert vehicle["stock"]["variable"].startswith("Stock|Transport|")
    assert vehicle["inflow"]["variable"].startswith("Sales|Transport|")
    assert vehicle["lifetime"]["distribution"] == "fixed"
    assert vehicle["lifetime"]["mean"] == 20
    path = tmp_path / "config.yaml"
    import yaml

    path.write_text(yaml.safe_dump(config))
    assert len(load_stock_config(path)["assets"]) == 4


def test_defaults_exclude_known_aggregate_regions():
    config, _ = build_remind_stock_config(frame())
    assert {asset["region"] for asset in config["assets"]} == {"DEU", "FRA"}


def test_missing_requested_region_fails():
    with pytest.raises(DataValidationError, match="absent"):
        build_remind_stock_config(frame(), regions=["UKI"])


def test_later_reference_year_uses_acknowledged_warm_start():
    config, _ = build_remind_stock_config(
        frame(), regions=["DEU"], reference_year=2006, end_year=2010
    )
    assert config["schema_version"] == 2
    initial = config["assets"][0]["initial"]
    assert initial == {
        "kind": "warm_start",
        "base_kind": "equilibrium",
        "base_year": 2005,
        "maximum_age": 30,
        "acknowledge_prior": True,
        "provenance": "Stationary historical-inflow legacy prior at the first IAM year, "
        "advanced to the reference year using IAM stocks and additions.",
    }


def test_joint_reconciliation_is_explicit_and_penalized():
    config, _ = build_remind_stock_config(frame(), regions=["DEU"], reconciliation="joint")
    asset = config["assets"][0]
    assert asset["mode"] == "joint"
    assert asset["exit_policy"] == "proportional"
    assert asset["annualisation"]["inflow_constraints"] == "penalized"
    with pytest.raises(DataValidationError, match="strict or joint"):
        build_remind_stock_config(frame(), reconciliation="automatic")


def test_complete_transport_children_replace_aggregate_without_double_counting():
    config, skipped = build_remind_stock_config(
        frame_with_transport_children(), regions=["DEU"], include_power=False
    )
    ids = {asset["id"] for asset in config["assets"]}
    assert ids == {
        "passenger-ldv-4w-bev",
        "passenger-ldv-4w-fcev",
        "passenger-ldv-4w-gases",
        "passenger-ldv-4w-hybrid",
        "passenger-ldv-4w-liquids",
    }
    assert {item["reason"] for item in skipped if item["asset"] == "passenger-ldv-4w"} == {
        "replaced by complete children"
    }


def test_transport_hierarchy_mismatch_uses_aggregate_fallback():
    config, skipped = build_remind_stock_config(
        frame_with_transport_children(mismatch=True),
        regions=["DEU"],
        include_power=False,
    )
    assert {asset["id"] for asset in config["assets"]} == {"passenger-ldv-4w"}
    assert "parent-child hierarchy mismatch" in {item["reason"] for item in skipped}
