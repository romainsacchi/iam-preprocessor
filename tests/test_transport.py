from __future__ import annotations

import pandas as pd
import pytest

from iam_preprocessor.exceptions import DataValidationError
from iam_preprocessor.transport import (
    derive_bev_truck_variables,
    derive_transport_energy_services,
)


def test_energy_to_service_conversion_and_units(sec_config):
    frame = pd.DataFrame(
        [
            {
                "Model": "IMAGE 3.4",
                "Scenario": "test",
                "Region": "R1",
                "Variable": "Final Energy|Transportation|Passenger|Bus|Electricity",
                "Unit": "EJ/yr",
                "2050": 1.0,
            },
            {
                "Model": "IMAGE 3.4",
                "Scenario": "test",
                "Region": "R1",
                "Variable": "Final Energy|Transportation|Freight|Train|Electricity",
                "Unit": "EJ/yr",
                "2050": 1.0,
            },
        ]
    )
    result, summary = derive_transport_energy_services(frame, sec_config)
    passenger = result.loc[
        result["Variable"].eq("Energy Service|Transportation|Passenger|Bus|Electricity")
    ].iloc[0]
    freight = result.loc[
        result["Variable"].eq("Energy Service|Transportation|Freight|Train|Electricity")
    ].iloc[0]
    assert passenger["2050"] == pytest.approx(1000 / 0.6)
    assert passenger["Unit"] == "billion pkm/yr"
    assert freight["2050"] == pytest.approx(1000 / 0.3)
    assert freight["Unit"] == "billion tkm/yr"
    assert len(summary.derived_variables) == 2


def test_pj_is_normalized_before_service_conversion(sec_config):
    frame = pd.DataFrame(
        [
            {
                "Model": "IMAGE 3.4",
                "Scenario": "test",
                "Region": "R1",
                "Variable": "Final Energy|Transportation|Freight|Train|Electricity",
                "Unit": "PJ/yr",
                "2050": 1.0,
            }
        ]
    )
    result, _ = derive_transport_energy_services(frame, sec_config)
    energy = result.loc[result["Variable"].str.startswith("Final Energy")].iloc[0]
    service = result.loc[result["Variable"].str.startswith("Energy Service")].iloc[0]
    assert energy["2050"] == pytest.approx(0.001)
    assert energy["Unit"] == "EJ/yr"
    assert service["2050"] == pytest.approx(1 / 0.3)


def test_bev_residual_and_world_aggregation(image_frame, sec_config):
    result, summary = derive_bev_truck_variables(image_frame, sec_config)
    medium_energy = result.loc[
        result["Variable"].eq(
            "Final Energy|Transportation|Freight|Medium Truck|Battery Electric|Electricity"
        )
    ]
    regional = medium_energy.loc[medium_energy["Region"].eq("R1")].iloc[0]
    world = medium_energy.loc[medium_energy["Region"].eq("World")].iloc[0]
    assert regional["2020"] == pytest.approx(0.2)
    assert regional["2050"] == pytest.approx(1.2)
    assert world["2050"] == pytest.approx(1.2)

    medium_service = result.loc[
        result["Variable"].eq("Energy Service|Transportation|Freight|Medium Truck|Battery Electric")
        & result["Region"].eq("R1")
    ].iloc[0]
    heavy_service = result.loc[
        result["Variable"].eq("Energy Service|Transportation|Freight|Heavy Truck|Battery Electric")
        & result["Region"].eq("R1")
    ].iloc[0]
    assert medium_service["2050"] == pytest.approx(1200)
    assert heavy_service["2050"] == pytest.approx(600)
    assert len(summary.derived_variables) == 4


def test_negative_bev_residual_warns_or_fails(image_frame, sec_config):
    mask = image_frame["Variable"].eq(
        "Final Energy|Transportation|Freight|Medium Truck|Electricity"
    ) & image_frame["Region"].eq("R1")
    image_frame.loc[mask, ["2020", "2050"]] = 0.05

    result, summary = derive_bev_truck_variables(image_frame, sec_config)
    residual = result.loc[
        result["Variable"].eq(
            "Final Energy|Transportation|Freight|Medium Truck|Battery Electric|Electricity"
        )
        & result["Region"].eq("R1"),
        ["2020", "2050"],
    ]
    assert (residual.to_numpy() == 0).all()
    assert any("negative Medium Truck" in warning for warning in summary.warnings)

    with pytest.raises(DataValidationError, match="Negative Medium Truck"):
        derive_bev_truck_variables(image_frame, sec_config, strict=True)
