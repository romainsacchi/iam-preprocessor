"""Explicit, opt-in annual-age service profiles, independent of stock survival."""

import numpy as np
import pandas as pd

from .exceptions import DataValidationError


def read_age_profile(path):
    """Require a complete age-0-based profile; the last factor is an explicit tail."""
    try:
        frame = pd.read_csv(path)
        if set(frame.columns) != {"age", "factor"} or frame.empty:
            raise ValueError("Expected age and factor columns")
        age, factor = frame["age"].to_numpy(float), frame["factor"].to_numpy(float)
        if not np.array_equal(age, np.arange(len(age))):
            raise ValueError("Ages must be consecutive integers starting at zero")
        if not np.isfinite(factor).all() or (factor < 0).any() or not (factor > 0).any():
            raise ValueError("Factors must be finite, nonnegative, with positive support")
        return factor
    except (OSError, ValueError, TypeError) as exc:
        raise DataValidationError(f"Invalid service age profile: {path}") from exc


def age_factors(path, service_years, cohorts):
    """Evolve usage as each cohort ages; hold the last documented age factor."""
    factors = read_age_profile(path)
    age = np.asarray(service_years)[:, None] - np.asarray(cohorts)[None, :]
    return np.where(age < 0, 0.0, factors[np.clip(age, 0, len(factors) - 1)])
