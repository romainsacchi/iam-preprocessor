"""Reconstruct the vintage composition of one stock asset.

The input layer has already selected and annualized IAM series.  This module
combines those series with a lifetime model and an opening stock composition.
It returns named arrays so callers do not need to interpret a long tuple.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .exceptions import DataValidationError
from .stock_model import (
    CohortResult,
    reconstruct,
    reconstruct_stock_flow,
    reconstruct_stock_path,
    survival_matrix,
)
from .stock_usage import age_factors
from .vintage_inputs import (
    annual_additions,
    interpolate_annual,
    read_iam_series,
    read_initial_cohorts,
)


@dataclass
class AssetReconstruction:
    """All reconstructed arrays and diagnostics for one configured asset."""

    cohorts: CohortResult
    stock_shares: np.ndarray
    service_shares: np.ndarray
    stock_targets: np.ndarray
    reported_additions: np.ndarray
    implied_exit: np.ndarray
    service_target: np.ndarray | None
    annualisation: dict | None
    evidence_basis: np.ndarray

    def as_legacy_tuple(self):
        """Return the tuple used by releases before the pipeline was split."""
        return (
            self.cohorts,
            self.stock_shares,
            self.service_shares,
            self.stock_targets,
            self.reported_additions,
            self.implied_exit,
            self.service_target,
            self.annualisation,
            self.evidence_basis,
        )


def reconstruct_asset(frame, asset, reference_year, end_year):
    """Reconstruct annual cohorts for one validated asset configuration.

    The steps are: read exact IAM rows, construct the opening stock, calculate
    cohort survival, reconcile stock and addition evidence, and derive stock and
    service shares.  Configuration validation is handled by ``stock_config``.
    """
    requested_end = end_year
    stock_series = read_iam_series(frame, asset["region"], asset["stock"])
    flow_series = read_iam_series(frame, asset["region"], asset["inflow"])
    if asset["mode"] == "joint":
        from .stock_annualisation import joint_horizon, reconstruct_joint

        end_year = joint_horizon(stock_series, reference_year, end_year, asset["inflow_timing"])

    observed, first = read_initial_cohorts(asset["initial"], reference_year)
    opening_year = asset["initial"].get("base_year", reference_year)
    years = np.arange(first, end_year + 1)
    service_years = np.arange(reference_year, end_year + 1)
    reference_position = reference_year - first
    opening_position = opening_year - first
    stock_targets = interpolate_annual(stock_series, service_years)
    if stock_targets[0] == 0 and observed is not None:
        raise DataValidationError(
            "Observed opening composition cannot initialize a zero regional stock."
        )

    # The reference stock is an initial condition, not the reference year's addition.
    reported_additions = np.r_[
        0.0,
        annual_additions(
            flow_series,
            service_years[1:],
            asset["inflow_timing"],
        ),
    ]

    lifetime = asset["lifetime"]
    parameter = "maximum" if lifetime["distribution"] == "remind" else "mean"
    initial_parameter = f"initial_{parameter}"
    lifetimes = np.full(len(years), float(lifetime[initial_parameter]))
    lifetimes[opening_position + 1 :] = (
        interpolate_annual(
            read_iam_series(frame, asset["region"], lifetime["source"]),
            years[opening_position + 1 :],
        )
        if "source" in lifetime
        else lifetime[parameter]
    )
    survival = survival_matrix(
        years.tolist(),
        lifetimes,
        distribution=lifetime["distribution"],
        shape=lifetime.get("shape"),
        conditional_year=opening_year if observed is not None else None,
    )

    initial = np.zeros(len(years))
    factors = np.ones(len(years))
    weighting = asset["service_weighting"]
    if observed is None:
        initial[: opening_position + 1] = survival[opening_position, : opening_position + 1]
    else:
        positions = observed["cohort"].to_numpy(int) - first
        initial[positions] = observed["amount"].to_numpy(float)
        if weighting["kind"] == "observed_factors":
            if "service_factor" not in observed:
                raise DataValidationError("Observation CSV is missing service_factor.")
            factors[:] = weighting["future_factor"]
            try:
                factors[positions] = observed["service_factor"].to_numpy(float)
            except (ValueError, TypeError) as exc:
                raise DataValidationError("Non-numeric observed service factors.") from exc
    if not np.isfinite(factors).all() or (factors < 0).any():
        raise DataValidationError("Service factors must be finite and nonnegative.")

    opening_stock = interpolate_annual(stock_series, [opening_year])[0]
    if opening_stock > 0:
        initial *= opening_stock / initial.sum()
    else:
        initial[:] = 0

    if opening_year < reference_year:
        warm_years = np.arange(opening_year, reference_year + 1)
        warm_targets = interpolate_annual(stock_series, warm_years)
        warm_additions = np.r_[
            0.0,
            annual_additions(flow_series, warm_years[1:], asset["inflow_timing"]),
        ]
        warm = reconstruct_stock_flow(
            years=years[: reference_position + 1],
            reference_year=opening_year,
            initial=initial[: reference_position + 1],
            survival=survival[: reference_position + 1, : reference_position + 1],
            stock_targets=warm_targets,
            inflow_targets=warm_additions,
            exit_policy=asset["exit_policy"],
        )
        initial[:] = 0
        initial[: reference_position + 1] = warm.stock[-1]

    annualisation = None
    if asset["mode"] == "stock_flow":
        result = reconstruct_stock_flow(
            years=years,
            reference_year=reference_year,
            initial=initial,
            survival=survival,
            stock_targets=stock_targets,
            inflow_targets=reported_additions,
            exit_policy=asset["exit_policy"],
        )
    elif asset["mode"] == "joint":
        baseline = reconstruct_stock_path(
            years, reference_position, initial, survival, stock_targets, "proportional"
        )
        result, annualisation = reconstruct_joint(
            baseline=baseline,
            survival=survival,
            stock_series=stock_series,
            flow_series=flow_series,
            timing=asset["inflow_timing"],
            reference_inflows=reported_additions,
            exit_policy=asset["exit_policy"],
            options={
                key: asset["annualisation"][key]
                for key in ("inflow_constraints", "reference_weight", "inflow_weight")
            },
        )
    else:
        result = reconstruct(
            years=years,
            reference_year=reference_year,
            initial=initial,
            survival=survival,
            targets=reported_additions if asset["mode"] == "inflow" else stock_targets,
            mode="inflow" if asset["mode"] == "inflow" else "stock",
            exit_policy=asset["exit_policy"],
        )

    ageing = np.maximum(
        0,
        service_years[:, None] - np.maximum(reference_year, years)[None, :],
    )
    service = result.stock * factors[None, :] * np.exp(-weighting["annual_age_decay"] * ageing)
    if weighting["kind"] == "age_profile":
        service = result.stock * age_factors(weighting["age_profile_file"], service_years, years)
    for index, year in enumerate(service_years[1:], start=1):
        service[index, year - first] *= weighting.get("new_cohort_exposure", 1.0)

    stock_total = result.stock.sum(axis=1)
    stock_shares = np.divide(
        result.stock,
        stock_total[:, None],
        out=np.zeros_like(result.stock),
        where=stock_total[:, None] > 0,
    )
    service_total = service.sum(axis=1)
    service_shares = np.divide(
        service,
        service_total[:, None],
        out=np.zeros_like(service),
        where=service_total[:, None] > 0,
    )

    service_target = None
    if "service" in asset:
        service_target = interpolate_annual(
            read_iam_series(frame, asset["region"], asset["service"]), service_years
        )
        if ((service_target > 0) & (service_total <= 0)).any():
            raise DataValidationError(
                "Positive IAM service cannot be supplied by zero serving stock."
            )
        service_shares[service_target == 0] = 0
        if "maximum_service_per_stock" in weighting:
            service_per_stock = np.divide(
                service_shares * service_target[:, None],
                result.stock,
                out=np.zeros_like(service),
                where=result.stock > 0,
            )
            invalid = (service_per_stock > weighting["maximum_service_per_stock"] * (1 + 1e-10)) & (
                service_years[:, None] <= requested_end
            )
            if invalid.any():
                time_position, cohort_position = np.argwhere(invalid)[0]
                raise DataValidationError(
                    "Modelled cohort service exceeds the declared per-stock bound: "
                    f"year={service_years[time_position]}, cohort={years[cohort_position]}, "
                    f"value={service_per_stock[time_position, cohort_position]:.8g}, "
                    f"bound={weighting['maximum_service_per_stock']:.8g}."
                )

    implied_exit = np.r_[
        np.nan,
        stock_targets[:-1] + reported_additions[1:] - stock_targets[1:],
    ]
    if end_year != requested_end:
        # Fit complete reporting windows, then trim to the requested public horizon.
        count = requested_end - reference_year + 1
        cohort_count = requested_end - first + 1
        result.years = result.years[:count]
        result.cohorts = result.cohorts[:cohort_count]
        result.stock = result.stock[:count, :cohort_count]
        for name in ("inflow", "natural_exit", "additional_exit", "balance"):
            setattr(result, name, getattr(result, name)[:count])
        stock_shares = stock_shares[:count, :cohort_count]
        service_shares = service_shares[:count, :cohort_count]
        stock_targets = stock_targets[:count]
        reported_additions = reported_additions[:count]
        implied_exit = implied_exit[:count]
        if service_target is not None:
            service_target = service_target[:count]

    evidence_basis = np.array(
        [
            "iam_addition"
            if cohort > opening_year
            else "observed"
            if observed is not None
            else "prior"
            for cohort in result.cohorts
        ],
        dtype=object,
    )
    return AssetReconstruction(
        cohorts=result,
        stock_shares=stock_shares,
        service_shares=service_shares,
        stock_targets=stock_targets,
        reported_additions=reported_additions,
        implied_exit=implied_exit,
        service_target=service_target,
        annualisation=annualisation,
        evidence_basis=evidence_basis,
    )
