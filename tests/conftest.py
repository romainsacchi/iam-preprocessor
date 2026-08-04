from __future__ import annotations

import pandas as pd
import pytest

from iam_preprocessor.config import SecConfig


@pytest.fixture
def sec_config() -> SecConfig:
    return SecConfig(
        transport_sec_mj_per_service_km={
            "Bus|Electricity": 0.6,
            "Train|Electricity": 0.3,
        },
        bev_truck_sec_mj_per_tkm={
            "Medium Truck": 1.0,
            "Heavy Truck": 2.0,
        },
    )


@pytest.fixture
def image_frame() -> pd.DataFrame:
    rows: list[dict] = []

    def add(variable: str, unit: str, values: tuple[float, float], region: str = "R1") -> None:
        rows.append(
            {
                "Model": "IMAGE 3.4",
                "Scenario": "test",
                "Region": region,
                "Variable": variable,
                "Unit": unit,
                "2020": values[0],
                "2050": values[1],
            }
        )

    for truck_class in ("Medium Truck", "Heavy Truck"):
        add(
            f"Final Energy|Transportation|Freight|{truck_class}|Electricity",
            "EJ/yr",
            (0.3, 1.3),
        )
        add(
            f"Final Energy|Transportation|Freight|{truck_class}|Electricity",
            "EJ/yr",
            (0.3, 1.3),
            region="World",
        )
        for distance in ("10km", "30km", "60km"):
            efficiency = 5.0 if distance == "10km" else 1.0
            add(
                f"Efficiency|Transportation|Freight|{truck_class}|"
                f"Plug-in electric vehicle {distance}|Electricity",
                "MJ/Tkm",
                (efficiency, efficiency),
            )
            activity = 10.0 if distance == "10km" else 0.0
            for fuel in ("Biofuel", "Oil"):
                add(
                    f"Energy Service|Transportation|Freight|{truck_class}|"
                    f"Plug-in electric vehicle {distance}|{fuel}",
                    "billion tkm/yr",
                    (activity, activity),
                )
    return pd.DataFrame(rows)
