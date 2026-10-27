"""Annual cohort accounting using explicit lifetime survival matrices.

Observed initial cohorts are surviving stock, not historical inflows. Their
future survival is conditional on being present at the reference year.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import gamma

import numpy as np

from .exceptions import DataValidationError


@dataclass
class CohortResult:
    """End-year stocks; flows at index zero are undefined (initial condition)."""

    years: np.ndarray
    cohorts: np.ndarray
    stock: np.ndarray
    inflow: np.ndarray
    natural_exit: np.ndarray
    additional_exit: np.ndarray
    balance: np.ndarray
    natural_exit_by_cohort: np.ndarray | None = None
    additional_exit_by_cohort: np.ndarray | None = None


EXIT_POLICIES = {"error", "proportional", "oldest_first", "hazard_weighted", "observed"}


def _allocate_additional_exit(amount, survivors, policy, *, hazard=None, observed=None):
    """Allocate an additional exit without retiring the current year's entries."""
    tolerance = 1e-10 * max(1.0, float(survivors.sum()))
    if amount <= tolerance:
        return np.zeros_like(survivors)
    if amount > survivors.sum() + tolerance:
        raise DataValidationError("Additional exits exceed the naturally surviving opening stock.")
    if policy == "error":
        raise DataValidationError(
            f"Stock and inflow targets require {amount:g} additional exits; "
            "select an explicit allocation policy or revise the inputs."
        )
    if policy == "observed":
        if observed is None:
            raise DataValidationError("Observed exit allocation requires cohort observations.")
        allocated = np.asarray(observed, dtype=float)
        if (
            allocated.shape != survivors.shape
            or not np.isfinite(allocated).all()
            or (allocated < 0).any()
            or (allocated > survivors + tolerance).any()
            or not np.isclose(allocated.sum(), amount, rtol=1e-9, atol=tolerance)
        ):
            raise DataValidationError("Observed cohort exits do not match the required exits.")
        return allocated
    if policy == "oldest_first":
        allocated = np.zeros_like(survivors)
        remaining = amount
        for index in np.flatnonzero(survivors > 0):
            allocated[index] = min(survivors[index], remaining)
            remaining -= allocated[index]
            if remaining <= tolerance:
                break
        return allocated
    weights = survivors.copy()
    if policy == "hazard_weighted":
        if hazard is None:
            raise DataValidationError("Hazard-weighted exits require cohort hazards.")
        weights *= np.asarray(hazard, dtype=float)
        if weights.sum() <= tolerance:
            raise DataValidationError(
                "Hazard-weighted exits are undefined when all hazards are zero."
            )
    if policy != "proportional" and policy != "hazard_weighted":
        raise DataValidationError(f"Unknown additional-exit policy: {policy}")
    return amount * weights / weights.sum()


def survival_matrix(years, lifetimes, *, distribution, shape=None, conditional_year=None):
    """Build a survival matrix with end-year entry and cohort lifetimes.

    End-year entry makes the first-year surviving fraction one. It is a
    declared annual timing convention, not an estimate of commissioning dates.

    For observed initial stock, ``conditional_year`` conditions pre-existing
    cohorts on survival to that year. Their valid pre-reference lower triangle
    is one and must not be interpreted as historical survival. Weibull
    conditioning in log space avoids dividing two underflowed probabilities
    for rare old survivors. Fixed lifetimes remain unchanged: observations
    beyond that age are invalid.
    Weibull means are converted to scale; shape is an independent assumption.
    REMIND energy-conversion lifetimes are maximum lifetimes ``tau``, with
    survival ``max(0, 1 - (age / tau) ** 4)`` and mean ``4 * tau / 5``.
    """
    lifetimes = np.asarray(lifetimes, dtype=float)
    if (
        lifetimes.shape != (len(years),)
        or not np.isfinite(lifetimes).all()
        or (lifetimes <= 0).any()
    ):
        raise DataValidationError(
            "Lifetime parameters must be finite, positive and cohort-specific."
        )
    dates = np.asarray(years)
    if distribution == "weibull" and (shape is None or not np.isfinite(shape) or shape <= 0):
        raise DataValidationError("Weibull shape must be finite and positive.")
    if distribution not in {"fixed", "weibull", "remind"}:
        raise DataValidationError("Lifetime distribution must be fixed, weibull or remind.")
    if distribution == "remind":
        if shape is not None:
            raise DataValidationError("REMIND maximum lifetimes do not use a shape parameter.")
        age = np.maximum(0, dates[:, None] - dates[None, :])
        sf = np.maximum(0, 1 - (age / lifetimes[None, :]) ** 4)
        sf *= dates[:, None] >= dates[None, :]
    elif distribution == "fixed":
        if shape is not None:
            raise DataValidationError("Fixed lifetimes do not use a shape parameter.")
        age = np.maximum(0, dates[:, None] - dates[None, :])
        sf = (age < lifetimes[None, :]) * (dates[:, None] >= dates[None, :])
        sf = sf.astype(float)
    else:
        scale = lifetimes / gamma(1 + 1 / shape)
        age = np.maximum(0, dates[:, None] - dates[None, :])
        sf = np.exp(-((age / scale[None, :]) ** shape))
        sf *= dates[:, None] >= dates[None, :]
    if conditional_year is not None:
        if conditional_year not in years:
            raise DataValidationError("Conditional survival year must be in the model years.")
        if distribution == "weibull":
            initial = dates <= conditional_year
            ages = np.maximum(0, dates[:, None] - dates[None, initial])
            reference_ages = conditional_year - dates[initial]
            scale = lifetimes[initial] / gamma(1 + 1 / shape)
            hazard = np.maximum(0, (ages / scale) ** shape - (reference_ages / scale) ** shape)
            sf[:, initial] = np.exp(-hazard) * (dates[:, None] >= dates[None, initial])
        elif distribution == "remind":
            initial = dates <= conditional_year
            ages = np.maximum(0, dates[:, None] - dates[None, initial])
            reference_ages = conditional_year - dates[initial]
            raw = np.maximum(0, 1 - (ages / lifetimes[None, initial]) ** 4)
            reference = np.maximum(0, 1 - (reference_ages / lifetimes[initial]) ** 4)
            conditional = np.divide(
                raw,
                reference[None, :],
                out=np.zeros_like(raw),
                where=reference[None, :] > 0,
            )
            before_reference = dates <= conditional_year
            conditional[before_reference, :] = np.where(
                reference[None, :] > 0,
                1,
                raw[before_reference, :],
            )
            sf[:, initial] = conditional * (dates[:, None] >= dates[None, initial])
    return sf


def reconstruct(*, years, reference_year, initial, survival, targets, mode, exit_policy):
    """Evolve an initialized stock using a configured survival matrix.

    ``targets`` means closing stocks in stock mode and annual entries in inflow
    mode. Proportional additional exits are an explicit stock-mode assumption.
    No negative inflow is silently clipped, and no balancing imports are inferred.
    """
    years = np.asarray(years, dtype=int)
    initial = np.asarray(initial, dtype=float)
    survival = np.asarray(survival, dtype=float)
    targets = np.asarray(targets, dtype=float)
    if len(years) < 2 or not np.all(np.diff(years) == 1) or reference_year not in years:
        raise DataValidationError(
            "Cohort years must be consecutive and include the reference year."
        )
    ref = int(np.flatnonzero(years == reference_year)[0])
    n = len(years)
    if initial.shape != (n,) or targets.shape != (n - ref,) or survival.shape != (n, n):
        raise DataValidationError("Inconsistent cohort, stock or survival dimensions.")
    if any(not np.isfinite(a).all() or (a < 0).any() for a in (initial, targets, survival)):
        raise DataValidationError("Cohort model inputs must be finite and nonnegative.")
    if initial[ref + 1 :].any() or (survival > 1).any():
        raise DataValidationError(
            "Initial cohorts cannot be in the future; survival cannot exceed one."
        )
    if not np.allclose(np.diag(survival), 1) or np.any(np.triu(survival, 1)):
        raise DataValidationError("Expected end-year entry survival matrix.")
    if np.any(np.diff(survival, axis=0)[np.tril_indices(n - 1)] > 1e-12):
        raise DataValidationError("Cohort survival cannot increase with age.")
    if np.any((initial > 0) & (survival[ref] <= 0)):
        raise DataValidationError(
            "Initial stock contains cohorts impossible under the lifetime law."
        )
    if mode not in {"stock", "inflow"} or exit_policy not in EXIT_POLICIES - {"observed"}:
        raise DataValidationError("Unknown reconstruction mode or exit policy.")
    stock = np.zeros((n - ref, n))
    stock[0] = initial
    inflow, natural, additional, balance = [np.full(n - ref, np.nan) for _ in range(4)]
    natural_by_cohort = np.full_like(stock, np.nan)
    additional_by_cohort = np.full_like(stock, np.nan)
    if mode == "stock" and not np.isclose(initial.sum(), targets[0], rtol=1e-10, atol=1e-12):
        raise DataValidationError("Initial stock does not match the reference target.")
    for i in range(ref + 1, n):
        j = i - ref
        ratio = np.divide(survival[i], survival[i - 1], out=np.zeros(n), where=survival[i - 1] > 0)
        survivors = stock[j - 1] * ratio
        natural_by_cohort[j] = stock[j - 1] - survivors
        natural[j] = natural_by_cohort[j].sum()
        additional[j] = 0.0
        additional_by_cohort[j] = 0.0
        if mode == "inflow":
            inflow[j] = targets[j]
        else:
            change = targets[j] - survivors.sum()
            if change < 0:
                allocated = _allocate_additional_exit(
                    -change,
                    survivors,
                    exit_policy,
                    hazard=1 - ratio,
                )
                additional_by_cohort[j] = allocated
                additional[j] = allocated.sum()
                survivors -= allocated
                inflow[j] = 0.0
            else:
                inflow[j] = change
        survivors[i] = inflow[j]
        stock[j] = survivors
        balance[j] = stock[j - 1].sum() + inflow[j] - natural[j] - additional[j] - stock[j].sum()
    if not np.allclose(balance[1:], 0, rtol=0, atol=1e-10 * max(1, stock.max())):
        raise DataValidationError("Cohort stock balance did not close.")
    return CohortResult(
        years[ref:],
        years,
        stock,
        inflow,
        natural,
        additional,
        balance,
        natural_by_cohort,
        additional_by_cohort,
    )


def reconstruct_stock_flow(
    *,
    years,
    reference_year,
    initial,
    survival,
    stock_targets,
    inflow_targets,
    exit_policy="error",
    observed_exits=None,
):
    """Preserve both stock and inflow series, inferring only explicit extra exits.

    The current year's additions enter at year end and cannot be retired in that
    same year. A target above natural survivors plus reported additions is
    therefore infeasible rather than repaired with an unreported balancing flow.
    """
    years = np.asarray(years, dtype=int)
    initial = np.asarray(initial, dtype=float)
    survival = np.asarray(survival, dtype=float)
    stock_targets = np.asarray(stock_targets, dtype=float)
    inflow_targets = np.asarray(inflow_targets, dtype=float)
    if reference_year not in years or len(years) < 2 or not np.all(np.diff(years) == 1):
        raise DataValidationError(
            "Cohort years must be consecutive and include the reference year."
        )
    ref = int(np.flatnonzero(years == reference_year)[0])
    rows, n = len(years) - ref, len(years)
    if (
        initial.shape != (n,)
        or survival.shape != (n, n)
        or stock_targets.shape != (rows,)
        or inflow_targets.shape != (rows,)
    ):
        raise DataValidationError("Inconsistent stock-flow reconstruction dimensions.")
    if any(
        not values.size or not np.isfinite(values).all() or (values < 0).any()
        for values in (initial, survival, stock_targets, inflow_targets)
    ):
        raise DataValidationError("Stock-flow inputs must be finite and nonnegative.")
    if exit_policy not in EXIT_POLICIES:
        raise DataValidationError(f"Unknown additional-exit policy: {exit_policy}")
    if not np.isclose(initial.sum(), stock_targets[0], rtol=1e-10, atol=1e-12):
        raise DataValidationError("Initial stock does not match the reference target.")
    if initial[ref + 1 :].any() or np.any((initial > 0) & (survival[ref] <= 0)):
        raise DataValidationError("Initial stock contains future or impossible cohorts.")
    stock = np.zeros((rows, n))
    stock[0] = initial
    inflow = np.full(rows, np.nan)
    natural = np.full(rows, np.nan)
    additional = np.full(rows, np.nan)
    balance = np.full(rows, np.nan)
    natural_by_cohort = np.full_like(stock, np.nan)
    additional_by_cohort = np.full_like(stock, np.nan)
    observations = None if observed_exits is None else np.asarray(observed_exits, dtype=float)
    if observations is not None and observations.shape != stock.shape:
        raise DataValidationError("Observed exit matrix has inconsistent dimensions.")
    for i in range(ref + 1, n):
        row = i - ref
        ratio = np.divide(survival[i], survival[i - 1], out=np.zeros(n), where=survival[i - 1] > 0)
        survivors = stock[row - 1] * ratio
        natural_by_cohort[row] = stock[row - 1] - survivors
        natural[row] = natural_by_cohort[row].sum()
        inflow[row] = inflow_targets[row]
        available = survivors.sum() + inflow[row]
        required_exit = available - stock_targets[row]
        tolerance = 1e-10 * max(1.0, available, stock_targets[row])
        if required_exit < -tolerance:
            raise DataValidationError(
                f"Stock target in {years[i]} exceeds natural survivors plus reported additions "
                f"by {-required_exit:g}; a closed stock-flow model cannot balance it."
            )
        required_exit = max(0.0, required_exit)
        allocated = _allocate_additional_exit(
            required_exit,
            survivors,
            exit_policy,
            hazard=1 - ratio,
            observed=None if observations is None else observations[row],
        )
        additional_by_cohort[row] = allocated
        additional[row] = allocated.sum()
        stock[row] = survivors - allocated
        stock[row, i] = inflow[row]
        balance[row] = (
            stock[row - 1].sum() + inflow[row] - natural[row] - additional[row] - stock[row].sum()
        )
    if not np.allclose(stock.sum(axis=1), stock_targets, rtol=1e-9, atol=1e-10):
        raise DataValidationError(
            "Strict stock-flow reconstruction did not preserve stock targets."
        )
    if not np.allclose(balance[1:], 0, rtol=0, atol=1e-10 * max(1, stock.max())):
        raise DataValidationError("Strict stock-flow reconstruction did not close.")
    return CohortResult(
        years[ref:],
        years,
        stock,
        inflow,
        natural,
        additional,
        balance,
        natural_by_cohort,
        additional_by_cohort,
    )
