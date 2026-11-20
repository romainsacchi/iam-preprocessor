"""FLODyM lifetime models and dynamic stock solvers for annual cohorts."""

from __future__ import annotations

from math import gamma
from typing import ClassVar

import numpy as np

from .exceptions import DataValidationError, IamPreprocessorError

try:
    from flodym import (
        Dimension,
        DimensionSet,
        FixedLifetime,
        FlodymArray,
        InflowDrivenDSM,
        LifetimeModel,
        StockArray,
        StockDrivenDSM,
        TabulatedLifetime,
        WeibullLifetime,
    )
except ImportError as exc:
    if exc.name != "flodym":
        raise
    raise IamPreprocessorError(
        "Install iam-preprocessor[stocks] to use the required FLODyM revision."
    ) from exc


class RemindLifetime(LifetimeModel):
    """REMIND capacity survival with a maximum lifetime for each cohort."""

    maximum: np.ndarray
    _prm_names: ClassVar[list[str]] = ["maximum"]
    _prm_names_to_scale: ClassVar[list[str]] = ["maximum"]

    def _survival_by_cohort(self, ages, cohort):
        return np.maximum(0, 1 - (ages / self._scaled_prms["maximum"][cohort]) ** 4)


def _time_dimensions(years):
    return DimensionSet(dim_list=[Dimension(name="time", letter="t", items=years.tolist())])


def lifetime_survival(years, lifetimes, distribution, shape):
    """Return absolute survival at the requested calendar years."""
    # FLODyM needs at least three time points to infer period bounds.
    # An annual grid keeps the end-of-year ages exact even for skipped years.
    annual = np.arange(years.min(), max(years.max(), years.min() + 2) + 1)
    positions = years - annual[0]
    parameters = np.full(len(annual), lifetimes[0])
    parameters[positions] = lifetimes
    dims = _time_dimensions(annual)
    if distribution == "fixed":
        law = FixedLifetime(dims=dims, mean=parameters, inflow_at="end")
    elif distribution == "weibull":
        law = WeibullLifetime(
            dims=dims,
            weibull_scale=parameters / gamma(1 + 1 / shape),
            weibull_shape=shape,
            inflow_at="end",
        )
    else:
        law = RemindLifetime(dims=dims, maximum=parameters, inflow_at="end")
    return law.cumulative_survival[np.ix_(positions, positions)]


def solve_from_survival(years, ref, opening, survival, targets, mode, exit_policy, removal_share):
    """Project known additions or solve a stock path with the supplied survival.

    Proportional, oldest-first and hazard-scaled exits use FLODyM's stock-driven policies.
    Unresolved negative additions return control to the caller.
    """
    count = len(years)
    table = np.eye(max(3, count))
    table[:count, :count] = survival
    calendar = np.arange(years[0], years[0] + len(table))
    dims = _time_dimensions(calendar)
    cohort = Dimension(name="cohort", letter="c", items=calendar.tolist(), dtype=int)
    removal = None
    if removal_share is not None:
        removal = np.zeros(len(table))
        removal[ref + 1 : count] = removal_share
    law = TabulatedLifetime(
        dims=dims,
        cumulative_survival_table=table,
        inflow_at="end",
        removal_share_by_year=removal,
    )
    future = slice(ref + 1, count)
    driving_values = np.zeros(len(table))
    driving_values[future] = targets[1:]
    driving_array = StockArray(dims=dims, values=driving_values)
    if mode == "stock":
        behavior = {
            "proportional": "remove_flat",
            "oldest_first": "remove_oldest",
            "remove_by_hazard": "remove_by_hazard",
        }
        model = StockDrivenDSM(
            dims=dims,
            cohort_dim=cohort,
            lifetime_model=law,
            stock=driving_array,
            negative_inflow_behavior=behavior.get(exit_policy, "allow_negative"),
        )
    else:
        model = InflowDrivenDSM(
            dims=dims, cohort_dim=cohort, lifetime_model=law, inflow=driving_array
        )
    initial = FlodymArray(
        dims=DimensionSet(dim_list=[cohort]), values=np.pad(opening, (0, len(table) - count))
    )
    model.set_initial_stock(initial, initial_year=int(years[ref]))
    try:
        model.compute()
    except (ValueError, RuntimeError) as exc:
        if exit_policy != "remove_by_hazard":
            raise
        raise DataValidationError(f"FLODyM hazard scaling failed: {exc}") from exc
    return None if (model.inflow.values[future] < 0).any() else model


def retire_by_hazard(years, opening, survival, closing_target):
    """Use a one-year stock-driven solve to retire already installed cohorts."""
    model = solve_from_survival(
        years,
        len(years) - 2,
        opening,
        survival,
        [opening.sum(), closing_target],
        "stock",
        "remove_by_hazard",
        None,
    )
    if model is None or model.inflow.values[len(years) - 1] > 1e-10 * max(1, closing_target):
        raise DataValidationError(
            "FLODyM hazard scaling could not meet the remaining stock target."
        )
    return model.get_stock_by_cohort().values[len(years) - 1, : len(years)]
