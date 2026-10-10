"""Conservation and constraint semantics, independent of plot smoothness."""

import numpy as np
import pytest

from iam_preprocessor.exceptions import DataValidationError
from iam_preprocessor.stock_annualisation import (
    fit_annual_additions,
    joint_horizon,
    reconstruct_joint,
)
from iam_preprocessor.stock_model import reconstruct, survival_matrix


def fit_fixture(timing, flow_series, *, scale=1):
    years = np.arange(2020, 2036)
    sf = survival_matrix(years.tolist(), np.full(len(years), 100), distribution="fixed")
    # True annual entries 1..15; their stock anchors are independently summed.
    source = {2020: 100 * scale, 2025: 115 * scale, 2035: 220 * scale}
    targets = np.interp(years, list(source), list(source.values()))
    initial = np.r_[100 * scale, np.zeros(15)]
    baseline = reconstruct(
        years=years,
        reference_year=2020,
        initial=initial,
        survival=sf,
        targets=targets,
        mode="stock",
        exit_policy="error",
    )
    result, report = reconstruct_joint(
        baseline=baseline,
        survival=sf,
        stock_series=source,
        flow_series={k: v * scale for k, v in flow_series.items()},
        timing=timing,
        reference_inflows=np.r_[0, np.full(5, 3 * scale), np.full(10, 10.5 * scale)],
        options={"inflow_constraints": "strict", "reference_weight": 0.01, "inflow_weight": 100},
    )
    return result, report, baseline


@pytest.mark.parametrize("scale", [1e-6, 1, 1e6])
def test_smooth_five_and_ten_year_periods_preserve_stock_and_additions(scale):
    result, report, baseline = fit_fixture(
        {
            "kind": "reported_periods",
            "periods": [
                {"anchor": 2025, "start": 2021, "end": 2025},
                {"anchor": 2035, "start": 2026, "end": 2035},
            ],
        },
        {2025: 3, 2035: 10.5},
        scale=scale,
    )
    assert report["exact_inflow_constraints_feasible"]
    assert result.inflow[1:6].sum() / scale == pytest.approx(15, abs=1e-7)
    assert result.inflow[6:].sum() / scale == pytest.approx(105, abs=1e-7)
    np.testing.assert_allclose(result.stock[[0, 5, 15]].sum(axis=1) / scale, [100, 115, 220])
    assert report["fitted_curvature_l2"] < report["baseline_curvature_l2"] / 2
    assert (
        abs(result.inflow[6] - result.inflow[5]) < abs(baseline.inflow[6] - baseline.inflow[5]) / 2
    )
    assert np.min(result.stock) >= 0
    np.testing.assert_allclose(result.balance[1:] / scale, 0, atol=1e-12)
    for t in range(1, len(result.years)):
        # No retirements for this analytical 100-year-life example.
        np.testing.assert_allclose(result.stock[t, :t], result.stock[t - 1, :t])
        assert result.stock[t, t] == result.inflow[t]


def test_sampled_annual_entries_are_points_not_interval_totals():
    result, report, _ = fit_fixture({"kind": "sampled_annual"}, {2025: 5, 2035: 15})
    assert result.inflow[5] == pytest.approx(5)
    assert result.inflow[15] == pytest.approx(15)
    assert report["exact_inflow_constraints_feasible"]
    assert all("target_total" not in row for row in report["flow_constraints"])


def test_conflict_is_rejected_or_minimally_reported_never_hidden():
    kwargs = dict(
        response=np.eye(2),
        initial_stock=np.zeros(2),
        stock_targets=np.array([2.0, 3.0]),
        flow_matrix=np.eye(2),
        flow_targets=np.array([4.0, 5.0]),
        reference=np.array([4.0, 5.0]),
        reference_weight=0.01,
        inflow_weight=100,
    )
    with pytest.raises(DataValidationError, match="Infeasible"):
        fit_annual_additions(**kwargs, inflow_constraints="strict")
    values, report = fit_annual_additions(**kwargs, inflow_constraints="penalized")
    np.testing.assert_allclose(values, [2, 3])
    assert not report["exact_inflow_constraints_feasible"]
    assert report["minimum_sum_absolute_rate_residual"] == pytest.approx(4)
    assert report["actual_sum_absolute_rate_residual"] == pytest.approx(4)


def test_decline_retains_explicit_baseline_exit_fractions():
    years = np.arange(2020, 2026)
    sf = survival_matrix(years.tolist(), np.full(len(years), 100), distribution="fixed")
    baseline = reconstruct(
        years=years,
        reference_year=2020,
        initial=np.r_[100.0, np.zeros(5)],
        survival=sf,
        targets=np.linspace(100, 50, 6),
        mode="stock",
        exit_policy="proportional",
    )
    result, report = reconstruct_joint(
        baseline=baseline,
        survival=sf,
        stock_series={2020: 100, 2025: 50},
        flow_series={2025: 0},
        timing={
            "kind": "reported_periods",
            "periods": [{"anchor": 2025, "start": 2021, "end": 2025}],
        },
        reference_inflows=np.zeros(6),
        options={"inflow_constraints": "strict", "reference_weight": 0.01, "inflow_weight": 100},
    )
    np.testing.assert_allclose(result.stock, baseline.stock, atol=1e-8)
    np.testing.assert_allclose(result.additional_exit[1:], 10)
    assert report["additional_exit_fractions"][-1] == pytest.approx(1 / 6)


def test_horizon_completes_windows_and_includes_next_stock_anchor():
    stocks = {2020: 1, 2025: 2, 2030: 3, 2035: 4}
    timing = {
        "kind": "reported_periods",
        "periods": [
            {"anchor": 2025, "start": 2023, "end": 2027},
            {"anchor": 2030, "start": 2028, "end": 2032},
        ],
    }
    assert joint_horizon(stocks, 2022, 2030, timing) == 2032
    assert joint_horizon(stocks, 2022, 2028, timing) == 2032
    assert joint_horizon(stocks, 2022, 2028, {"kind": "sampled_annual"}) == 2030
    with pytest.raises(DataValidationError, match="partial initial"):
        joint_horizon(stocks, 2024, 2030, timing)
    with pytest.raises(DataValidationError, match="cover"):
        joint_horizon(stocks, 2020, 2030, timing)
    with pytest.raises(DataValidationError, match="extrapolation"):
        joint_horizon({2025: 2, 2030: 3}, 2022, 2030, timing)
