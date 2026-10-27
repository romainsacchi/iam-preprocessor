import pandas as pd

from iam_preprocessor.remind_stock_inventory import (
    build_remind_stock_inventory,
    write_remind_stock_inventory,
)


def frame():
    rows = []

    def add(variable, unit, first=1, second=2):
        rows.append(
            {
                "Model": "REMIND",
                "Scenario": "test",
                "Region": "DEU",
                "Variable": variable,
                "Unit": unit,
                "2005": first,
                "2010": second,
            }
        )

    for stock in (
        "Cap|Electricity|Solar|+|PV",
        "Cap|Electricity",
        "Cap|Novel",
    ):
        add(stock, "GW")
        add("New " + stock, "GW/yr", 0.1, 0.2)
    add("Tech|Electricity|Solar|PV|Lifetime", "years", 30, 30)
    for suffix in (
        "Pass|Road|LDV|Four Wheelers",
        "Pass|Road|LDV|Four Wheelers|BEV",
        "Pass|Road|LDV|Four Wheelers|BEV|Small",
    ):
        add("Stock|Transport|" + suffix, "million veh")
        add("Sales|Transport|" + suffix, "million veh", 0.1, 0.2)
    return pd.DataFrame(rows)


def test_inventory_classifies_mapped_aggregate_detailed_and_unknown_pairs():
    inventory = build_remind_stock_inventory(frame(), regions=["DEU"])
    status = inventory.set_index("stock_variable")["status"].to_dict()
    assert status["Cap|Electricity|Solar|+|PV"] == "mapped"
    assert status["Cap|Electricity"] == "reporting_aggregate"
    assert status["Cap|Novel"] == "unmapped"
    assert status["Stock|Transport|Pass|Road|LDV|Four Wheelers"] == "mapped_aggregate_fallback"
    assert status["Stock|Transport|Pass|Road|LDV|Four Wheelers|BEV"] == "mapped"
    assert status["Stock|Transport|Pass|Road|LDV|Four Wheelers|BEV|Small"] == "below_selected_layer"
    assert inventory["regions_complete"].eq(1).all()


def test_writes_semicolon_inventory(tmp_path):
    source = tmp_path / "scenario.csv"
    frame().to_csv(source, index=False)
    destination = tmp_path / "inventory.csv"
    path, inventory = write_remind_stock_inventory(source, destination, regions=["DEU"])
    assert path == destination
    assert len(pd.read_csv(destination, sep=";")) == len(inventory)
