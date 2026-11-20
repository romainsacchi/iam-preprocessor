"""Read and annualize the IAM inputs used by vintage reconstruction.

This module contains no stock model.  It only turns exact IAM rows and optional
opening-cohort observations into small, validated Python objects.  Keeping this
step separate makes the time and unit assumptions visible before reconstruction.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .exceptions import DataValidationError
from .io import year_columns


def read_iam_series(frame, region, selector):
    """Return one exact IAM variable/unit row as ``{year: value}``.

    Parameters
    ----------
    frame:
        Normalized IAM table.
    region:
        Exact IAM region label.
    selector:
        Mapping with ``variable`` and ``unit`` keys.
    """
    selected = frame.loc[frame["Region"].eq(region) & frame["Variable"].eq(selector["variable"])]
    if len(selected) != 1 or selected.iloc[0]["Unit"] != selector["unit"]:
        raise DataValidationError(f"Expected a unique exact variable/unit: {region}/{selector}")
    labels = year_columns(frame)
    try:
        values = pd.to_numeric(selected.iloc[0][labels], errors="raise").to_numpy(float)
    except (ValueError, TypeError) as exc:
        raise DataValidationError(f"Non-numeric IAM series: {selector}") from exc
    if not np.isfinite(values).all() or (values < 0).any():
        raise DataValidationError(f"Missing, negative or nonfinite IAM series: {selector}")
    return dict(zip(map(int, labels), values, strict=True))


def interpolate_annual(series, years):
    """Linearly interpolate annual levels or sampled annual rates.

    Extrapolation is deliberately rejected because it would add information
    outside the IAM horizon.
    """
    anchors = sorted(series)
    if min(years) < anchors[0] or max(years) > anchors[-1]:
        raise DataValidationError("Requested years require extrapolation beyond IAM anchors.")
    return np.interp(years, anchors, [series[y] for y in anchors])


def annual_additions(series, years, timing):
    """Expand an IAM addition series to annual values.

    ``sampled_annual`` values are interpolated. ``reported_periods`` values are
    copied across their explicitly declared inclusive windows.
    """
    if timing["kind"] == "sampled_annual":
        return interpolate_annual(series, years)
    rates = {}
    anchors_seen = set()
    for period in timing["periods"]:
        anchor = period["anchor"]
        if anchor not in series or anchor in anchors_seen:
            raise DataValidationError("Reporting periods need unique existing IAM anchors.")
        anchors_seen.add(anchor)
        for year in range(period["start"], period["end"] + 1):
            if year in rates:
                raise DataValidationError(f"Overlapping reporting periods in {year}.")
            rates[year] = series[anchor]
    missing = set(years) - rates.keys()
    if missing:
        raise DataValidationError(f"Reporting windows do not cover years: {sorted(missing)}")
    return np.array([rates[y] for y in years], dtype=float)


def read_initial_cohorts(initial, reference_year):
    """Return the opening observations, if any, and the earliest build year."""
    if initial["kind"] in {"equilibrium", "warm_start"}:
        opening = initial.get("base_year", reference_year)
        return None, opening - initial["maximum_age"]
    try:
        observed = pd.read_csv(initial["file"])
        allowed = {"cohort", "amount", "service_factor", "evidence_basis"}
        if set(observed.columns) - allowed:
            raise ValueError("Unexpected observation columns")
        values = observed[["cohort", "amount"]].to_numpy(float)
        if not np.isfinite(values).all() or (values[:, 1] < 0).any():
            raise ValueError("Invalid observed quantities")
        cohorts = values[:, 0]
        if (
            len(cohorts) == 0
            or len(set(cohorts)) != len(cohorts)
            or (cohorts != cohorts.astype(int)).any()
            or (cohorts > reference_year).any()
            or (cohorts < reference_year - 150).any()
            or values[:, 1].sum() <= 0
        ):
            raise ValueError("Invalid cohort years or zero total")
        observed["cohort"] = cohorts.astype(int)
        if "evidence_basis" in observed and not set(observed["evidence_basis"]).issubset(
            {"prior", "observed", "observed_proxy"}
        ):
            raise ValueError("Invalid cohort evidence basis")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DataValidationError(f"Invalid cohort observations: {initial['file']}: {exc}") from exc
    return observed, int(cohorts.min())


def annualize_source_table(frame, added_years):
    """Add annual columns to the source table without changing native anchors."""
    anchors = list(map(int, year_columns(frame)))
    additions = {}
    for year in added_years:
        if str(year) in frame.columns:
            continue
        # Always interpolate between years supplied by the IAM.
        lo, hi = max(y for y in anchors if y < year), min(y for y in anchors if y > year)
        try:
            lower = pd.to_numeric(frame[str(lo)], errors="raise")
            upper = pd.to_numeric(frame[str(hi)], errors="raise")
        except (TypeError, ValueError) as exc:
            raise DataValidationError(
                "Cannot interpolate non-numeric original IAM variables."
            ) from exc
        additions[str(year)] = lower + (upper - lower) * (year - lo) / (hi - lo)
    return pd.concat([frame, pd.DataFrame(additions, index=frame.index)], axis=1)
