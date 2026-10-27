from math import gamma

import numpy as np
import pytest

from iam_preprocessor.exceptions import DataValidationError
from iam_preprocessor.stock_survival_fit import fit_vehicle_weibull


def panel(mean=18, shape=2.5, opening_year=2020, closing_year=2023):
    cohorts = range(2005, 2020, 2)
    scale = mean / gamma(1 + 1 / shape)
    opening = {cohort: 100.0 for cohort in cohorts}
    closing = {
        cohort: 100
        * np.exp(
            -(
                ((closing_year - cohort) / scale) ** shape
                - ((opening_year - cohort) / scale) ** shape
            )
        )
        for cohort in cohorts
    }
    return opening, closing


def test_recovers_vehicle_survival_and_reports_fit_diagnostics():
    opening, closing = panel()
    result = fit_vehicle_weibull(
        opening,
        closing,
        opening_year=2020,
        closing_year=2023,
        source_id="jrc-vehicle-panel",
    )
    assert result["mean"] == pytest.approx(18, rel=1e-6)
    assert result["shape"] == pytest.approx(2.5, rel=1e-6)
    assert result["log_survival_rmse"] < 1e-8
    assert not result["net_used_trade_supplied"]


def test_used_trade_is_explicit_and_unresolved_growth_fails():
    opening, closing = panel()
    cohort = max(opening)
    closing[cohort] += 25
    with pytest.raises(DataValidationError, match="growth exceeds"):
        fit_vehicle_weibull(
            opening,
            closing,
            opening_year=2020,
            closing_year=2023,
            source_id="test",
        )
    result = fit_vehicle_weibull(
        opening,
        closing,
        opening_year=2020,
        closing_year=2023,
        net_used_trade={cohort: 25},
        source_id="test",
    )
    assert result["net_used_trade_supplied"]
