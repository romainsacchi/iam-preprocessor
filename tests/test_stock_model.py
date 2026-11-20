"""Analytical cases and integration checks for the FLODyM stock solvers."""

import numpy as np
import pytest

from iam_preprocessor.exceptions import DataValidationError
from iam_preprocessor.stock_model import reconstruct, reconstruct_stock_flow, survival_matrix


def run(*, years, initial, means=3, targets, mode="stock", exit_policy="error", ref=None):
    sf = survival_matrix(years, np.full(len(years), means), distribution="fixed")
    return reconstruct(
        years=years,
        reference_year=years[0] if ref is None else ref,
        initial=initial,
        survival=sf,
        targets=targets,
        mode=mode,
        exit_policy=exit_policy,
    )


def test_fixed_lifetime_replacement_and_conservation():
    r = run(years=list(range(2020, 2027)), initial=[10, 0, 0, 0, 0, 0, 0], targets=[10] * 7)
    np.testing.assert_allclose(r.inflow[1:], [0, 0, 10, 0, 0, 10])
    np.testing.assert_allclose(r.natural_exit[1:], r.inflow[1:])
    np.testing.assert_allclose(r.stock.sum(axis=1), 10)
    assert np.nanmax(np.abs(r.balance)) == 0


@pytest.mark.parametrize("mode", ["stock", "inflow"])
@pytest.mark.parametrize("distribution", ["fixed", "weibull"])
def test_against_flodym_native_dsm(mode, distribution):
    from math import gamma

    flodym = pytest.importorskip("flodym")
    years = list(range(2020, 2030))
    targets = np.linspace(10, 20, 10) if mode == "stock" else np.arange(1, 11, dtype=float)
    dims = flodym.DimensionSet(dim_list=[flodym.Dimension(name="time", letter="t", items=years)])
    if distribution == "fixed":
        law = flodym.FixedLifetime(dims=dims, mean=3, inflow_at="end")
    else:
        law = flodym.WeibullLifetime(
            dims=dims, weibull_scale=3 / gamma(1.5), weibull_shape=2, inflow_at="end"
        )
    cls = flodym.StockDrivenDSM if mode == "stock" else flodym.InflowDrivenDSM
    cohort = flodym.Dimension(name="cohort", letter="c", items=years)
    native = cls(dims=dims, cohort_dim=cohort, lifetime_model=law)
    getattr(native, "stock" if mode == "stock" else "inflow").set_values(targets)
    native.compute()
    initial = [targets[0]] + [0] * 9
    survival = survival_matrix(
        years,
        np.full(len(years), 3),
        distribution=distribution,
        shape=2 if distribution == "weibull" else None,
    )
    result = reconstruct(
        years=years,
        reference_year=years[0],
        initial=initial,
        survival=survival,
        targets=targets,
        mode=mode,
        exit_policy="error",
    )
    np.testing.assert_allclose(result.stock, native.get_stock_by_cohort().values)
    np.testing.assert_allclose(result.inflow[1:], native.inflow.values[1:])
    np.testing.assert_allclose(result.natural_exit[1:], native.outflow.values[1:])


def test_initial_observed_stock_is_conditioned_not_depreciated_twice():
    years = list(range(2010, 2025))
    sf = survival_matrix(years, np.full(len(years), 10), distribution="weibull", shape=2)
    initial = np.zeros(len(years))
    initial[0] = 100
    r = reconstruct(
        years=years,
        reference_year=2020,
        initial=initial,
        survival=sf,
        targets=np.zeros(5),
        mode="inflow",
        exit_policy="error",
    )
    assert r.stock[0, 0] == 100
    np.testing.assert_allclose(r.stock[:, 0], 100 * sf[10:, 0] / sf[10, 0])


def test_decline_requires_explicit_exit_assumption():
    kwargs = dict(years=[2020, 2021, 2022], initial=[100, 0, 0], targets=[100, 50, 20], means=50)
    with pytest.raises(DataValidationError, match="additional exits"):
        run(**kwargs)
    r = run(**kwargs, exit_policy="proportional")
    np.testing.assert_allclose(r.additional_exit[1:], [50, 30])
    np.testing.assert_allclose(r.inflow[1:], 0)
    np.testing.assert_allclose(r.balance[1:], 0)


def test_impossible_old_cohort_rejected():
    with pytest.raises(DataValidationError, match="impossible"):
        run(years=list(range(2000, 2023)), initial=[1] + [0] * 22, targets=[1, 1], ref=2021)


def test_new_lifetime_applies_to_new_cohort_only():
    years = list(range(2020, 2026))
    sf = survival_matrix(years, [2, 10, 10, 10, 10, 10], distribution="fixed")
    assert sf[2, 0] == 0
    assert sf[5, 1] == 1


def test_fixed_lifetime_matrix_and_shape_validation():
    sf = survival_matrix([2020, 2021, 2022], [2, 2, 2], distribution="fixed")
    np.testing.assert_array_equal(sf[:, 0], [1, 1, 0])
    with pytest.raises(DataValidationError, match="do not use a shape"):
        survival_matrix([2020, 2021], [2, 2], distribution="fixed", shape=3)


def test_fixed_lifetime_uses_calendar_ages_with_skipped_years():
    sf = survival_matrix([2020, 2022, 2025], [2.5, 10, 10], distribution="fixed")
    np.testing.assert_array_equal(sf, [[1, 0, 0], [1, 1, 0], [0, 1, 1]])


def test_stock_driven_solver_keeps_opening_cohorts_of_different_scales():
    result = run(
        years=list(range(2019, 2023)),
        ref=2020,
        initial=[1e20, 1, 0, 0],
        targets=[1e20, 1e20, 2],
    )
    np.testing.assert_array_equal(result.stock[:, 1], [1, 1, 1])
    np.testing.assert_array_equal(result.inflow[1:], [0, 1])
    assert np.isnan(result.inflow[0])


@pytest.mark.parametrize(
    ("policy", "expected"), [("proportional", [2.8, 4.2]), ("oldest_first", [1.0, 6.0])]
)
def test_stock_driven_solver_applies_flodym_early_retirement(policy, expected, monkeypatch):
    from flodym import StockDrivenDSM

    compute = StockDrivenDSM.compute
    behaviors = []

    def record_behavior(model):
        behaviors.append(model.negative_inflow_behavior)
        return compute(model)

    monkeypatch.setattr(StockDrivenDSM, "compute", record_behavior)
    result = run(
        years=[2019, 2020, 2021, 2022],
        ref=2020,
        initial=[4, 6, 0, 0],
        targets=[10, 7, 8],
        means=100,
        exit_policy=policy,
    )
    assert behaviors == [{"proportional": "remove_flat", "oldest_first": "remove_oldest"}[policy]]
    np.testing.assert_allclose(result.stock[1, :2], expected)
    np.testing.assert_allclose(result.additional_exit_by_cohort[1, :2], [4, 6] - np.array(expected))
    assert result.inflow[1] == pytest.approx(0)
    assert result.inflow[2] == pytest.approx(1)


def test_remind_maximum_lifetime_survival_and_cutoff():
    years = list(range(2020, 2026))
    sf = survival_matrix(years, np.full(len(years), 5), distribution="remind")
    expected = np.maximum(0, 1 - (np.arange(6) / 5) ** 4)
    np.testing.assert_allclose(sf[:, 0], expected)
    assert sf[5, 0] == 0
    assert sf[4, 0] > 0
    np.testing.assert_array_equal(np.triu(sf, 1), 0)


def test_remind_observed_cohorts_use_conditional_survival():
    years = list(range(2020, 2027))
    sf = survival_matrix(
        years,
        np.full(len(years), 5),
        distribution="remind",
        conditional_year=2022,
    )
    assert sf[2, 0] == 1
    expected = (1 - (3 / 5) ** 4) / (1 - (2 / 5) ** 4)
    assert sf[3, 0] == pytest.approx(expected)
    assert sf[5, 0] == 0


def test_remind_observed_cohort_at_maximum_lifetime_is_impossible():
    years = list(range(2020, 2027))
    sf = survival_matrix(
        years,
        np.full(len(years), 2),
        distribution="remind",
        conditional_year=2022,
    )
    initial = np.zeros(len(years))
    initial[0] = 1
    with pytest.raises(DataValidationError, match="impossible"):
        reconstruct(
            years=years,
            reference_year=2022,
            initial=initial,
            survival=sf,
            targets=np.zeros(5),
            mode="inflow",
            exit_policy="error",
        )


def test_remind_distribution_rejects_weibull_shape():
    with pytest.raises(DataValidationError, match="do not use a shape"):
        survival_matrix([2020, 2021], [30, 30], distribution="remind", shape=3)


def test_zero_stock_and_restart():
    r = run(
        years=[2020, 2021, 2022], initial=[1, 0, 0], targets=[1, 0, 2], exit_policy="proportional"
    )
    np.testing.assert_allclose(r.stock.sum(axis=1), [1, 0, 2])
    assert r.inflow[-1] == 2


def test_stock_flow_preserves_reported_additions_and_allocates_oldest_first():
    years = np.arange(2019, 2023)
    sf = survival_matrix(years, np.full(4, 100), distribution="fixed")
    result = reconstruct_stock_flow(
        years=years,
        reference_year=2020,
        initial=[4, 6, 0, 0],
        survival=sf,
        stock_targets=[10, 9, 10],
        inflow_targets=[0, 2, 1],
        exit_policy="oldest_first",
    )
    np.testing.assert_allclose(result.stock.sum(axis=1), [10, 9, 10])
    np.testing.assert_allclose(result.inflow[1:], [2, 1])
    np.testing.assert_allclose(result.additional_exit[1:], [3, 0])
    assert result.additional_exit_by_cohort[1, 0] == 3
    assert result.additional_exit_by_cohort[1, 2] == 0


def test_stock_flow_fails_instead_of_inventing_inflow_or_retiring_new_assets():
    years = np.arange(2020, 2022)
    sf = survival_matrix(years, np.full(2, 100), distribution="fixed")
    common = dict(
        years=years,
        reference_year=2020,
        initial=[10, 0],
        survival=sf,
        inflow_targets=[0, 1],
    )
    with pytest.raises(DataValidationError, match="cannot balance"):
        reconstruct_stock_flow(**common, stock_targets=[10, 12])
    with pytest.raises(DataValidationError, match="surviving opening stock"):
        reconstruct_stock_flow(**common, stock_targets=[10, 0], exit_policy="proportional")
    with pytest.raises(DataValidationError, match="select an explicit allocation"):
        reconstruct_stock_flow(**common, stock_targets=[10, 10], exit_policy="error")


@pytest.mark.parametrize("mode", ["stock", "stock_flow"])
def test_flo_dym_hazard_scaling_preserves_stock_targets_and_new_additions(mode):
    # This stock target corresponds to doubling the natural hazards: the
    # per-cohort annual survival probabilities are squared by FLODyM.
    common = dict(
        years=[2019, 2020, 2021],
        reference_year=2020,
        initial=[4, 6, 0],
        survival=[[1, 0, 0], [1, 1, 0], [0.5, 0.75, 1]],
        exit_policy="remove_by_hazard",
    )
    if mode == "stock":
        result = reconstruct(**common, mode="stock", targets=[10, 4.375])
        new_additions = 0
    else:
        result = reconstruct_stock_flow(**common, stock_targets=[10, 5.375], inflow_targets=[0, 1])
        new_additions = 1
    np.testing.assert_allclose(result.stock[1], [1, 3.375, new_additions], atol=1e-10)
    np.testing.assert_allclose(result.natural_exit_by_cohort[1], [2, 1.5, 0])
    np.testing.assert_allclose(result.additional_exit_by_cohort[1], [1, 1.125, 0])
    assert result.inflow[1] == pytest.approx(new_additions, abs=1e-10)


def test_hazard_scaling_reports_infeasibility_with_zero_hazard():
    with pytest.raises(DataValidationError, match="FLODyM hazard scaling failed"):
        run(
            years=[2020, 2021],
            initial=[10, 0],
            means=100,
            targets=[10, 5],
            exit_policy="remove_by_hazard",
        )


def test_stock_flow_observed_exit_allocation():
    years = np.arange(2019, 2022)
    sf = survival_matrix(years, np.full(3, 10), distribution="remind")
    common = dict(
        years=years,
        reference_year=2020,
        initial=[5, 5, 0],
        survival=sf,
        stock_targets=[10, 8],
        inflow_targets=[0, 0],
    )
    required = 5 * (sf[2, 0] / sf[1, 0] + sf[2, 1] / sf[1, 1]) - 8
    observations = np.zeros((2, 3))
    observations[1, 1] = required
    observed = reconstruct_stock_flow(**common, exit_policy="observed", observed_exits=observations)
    assert observed.additional_exit_by_cohort[1, 1] == pytest.approx(required)
