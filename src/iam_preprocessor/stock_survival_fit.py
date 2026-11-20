"""Fit regional vehicle survival from observed cohort panels."""

from __future__ import annotations

from math import gamma

import numpy as np
from scipy.optimize import least_squares

from .exceptions import DataValidationError


def fit_vehicle_weibull(
    opening,
    closing,
    *,
    opening_year,
    closing_year,
    net_used_trade=None,
    source_id,
):
    """Fit Weibull mean and shape after explicit cohort-level used trade.

    ``opening`` and ``closing`` map first-registration year to observed stock.
    ``net_used_trade`` is positive for net imports between snapshots. Cohorts
    absent from either snapshot are not silently treated as observed zeros.
    """
    if not source_id or closing_year <= opening_year:
        raise DataValidationError("A source and ordered observation years are required.")
    trade = net_used_trade or {}
    cohorts = sorted(set(opening) & set(closing))
    ratios, ages = [], []
    for cohort in cohorts:
        before, after = float(opening[cohort]), float(closing[cohort]) - float(trade.get(cohort, 0))
        if cohort > opening_year or before <= 0 or after < 0:
            raise DataValidationError("Invalid vehicle cohort stock or used-trade adjustment.")
        ratio = after / before
        if ratio > 1 + 1e-9:
            raise DataValidationError(
                "Adjusted cohort growth exceeds one; used trade or boundary changes remain."
            )
        if ratio > 0:
            ratios.append(min(ratio, 1.0))
            ages.append(opening_year - cohort)
    if len(ratios) < 3 or len(set(ages)) < 2:
        raise DataValidationError(
            "At least three positive observations across two ages are needed."
        )
    ratios, ages = np.asarray(ratios), np.asarray(ages, dtype=float)
    duration = closing_year - opening_year

    def residual(parameters):
        """Compare predicted and observed stock across vehicle build years."""
        mean, shape = parameters
        scale = mean / gamma(1 + 1 / shape)
        predicted = np.exp(-(((ages + duration) / scale) ** shape - (ages / scale) ** shape))
        return np.log(predicted) - np.log(ratios)

    fitted = least_squares(residual, x0=[15, 3], bounds=([1, 0.25], [80, 10]))
    if not fitted.success:
        raise DataValidationError(f"Vehicle survival fit failed: {fitted.message}")
    mean, shape = map(float, fitted.x)
    errors = residual(fitted.x)
    return {
        "distribution": "weibull",
        "mean": mean,
        "shape": shape,
        "source_id": source_id,
        "opening_year": opening_year,
        "closing_year": closing_year,
        "cohort_observations": len(ratios),
        "net_used_trade_supplied": net_used_trade is not None,
        "log_survival_rmse": float(np.sqrt(np.mean(errors**2))),
        "optimizer_status": int(fitted.status),
        "optimizer_message": fitted.message,
    }
