"""Variable filtering shared by all model pipelines."""

from __future__ import annotations

import pandas as pd

from .variable_maps import variable_map

DEFAULT_PREFIXES = (
    variable_map("vintage_output_variables.yaml")["prefix"],
    *variable_map("variable_filters.yaml")["prefixes"],
)


def filter_variables(
    data: pd.DataFrame,
    prefixes: tuple[str, ...] = DEFAULT_PREFIXES,
) -> pd.DataFrame:
    """Keep IAM rows whose variable begins with an approved prefix."""

    unique_prefixes = tuple(dict.fromkeys(prefixes))
    mask = data["Variable"].fillna("").astype(str).str.startswith(unique_prefixes)
    return data.loc[mask].copy().reset_index(drop=True)
