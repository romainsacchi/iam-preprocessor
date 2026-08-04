"""Variable filtering shared by all model pipelines."""

from __future__ import annotations

import pandas as pd

DEFAULT_PREFIXES = (
    "Distance",
    "Energy Service",
    "ES",
    "FE",
    "SE",
    "PE",
    "Final Energy",
    "Production",
    "Efficiency",
    "Emi|CO2",
    "Emissions|CO2",
    "Emissions|Kyoto Gases",
    "Emission Factor|CO2",
    "Carbon Capture",
    "Land Use",
    "Temperature",
    "AR6",
    "Secondary Energy",
    "Primary Energy",
    "Population",
    "Tech",
    "GDP",
    "MAGICC7 AR6|Raw Surface Temperature (GMST)|50.0th Percentile",
    "Carbon Management|Carbon Capture|Industrial Processes|Industry|+|Cement",
    "New",
    "Sales",
)


def filter_variables(
    data: pd.DataFrame,
    prefixes: tuple[str, ...] = DEFAULT_PREFIXES,
) -> pd.DataFrame:
    """Keep IAM rows whose variable begins with an approved prefix."""

    unique_prefixes = tuple(dict.fromkeys(prefixes))
    mask = data["Variable"].fillna("").astype(str).str.startswith(unique_prefixes)
    return data.loc[mask].copy().reset_index(drop=True)
