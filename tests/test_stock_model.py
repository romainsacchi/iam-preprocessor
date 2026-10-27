"""Analytical cases and independent stock/inflow-driven flodym comparisons."""

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
def test_against_flodym_native_dsm(mode):
    flodym = pytest.importorskip("flodym")
    years = list(range(2020, 2030))
    targets = np.linspace(10, 20, 10) if mode == "stock" else np.arange(1, 11, dtype=float)
    dims = flodym.DimensionSet(dim_list=[flodym.Dimension(name="time", letter="t", items=years)])
    law = flodym.FixedLifetime(dims=dims, mean=3, inflow_at="end")
    cls = flodym.StockDrivenDSM if mode == "stock" else flodym.InflowDrivenDSM
    native = cls(dims=dims, lifetime_model=law)
    getattr(native, "stock" if mode == "stock" else "inflow").values[:] = targets
    native.compute()
    initial = [targets[0]] + [0] * 9
    result = run(years=years, initial=initial, targets=targets, mode=mode)
    np.testing.assert_allclose(result.stock, native.get_stock_by_cohort())
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


def test_fixed_lifetime_matrix_does_not_require_flodym_runtime():
    sf = survival_matrix([2020, 2021, 2022], [2, 2, 2], distribution="fixed")
    np.testing.assert_array_equal(sf[:, 0], [1, 1, 0])
    with pytest.raises(DataValidationError, match="do not use a shape"):
        survival_matrix([2020, 2021], [2, 2], distribution="fixed", shape=3)


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


def test_stock_flow_hazard_weighted_and_observed_exit_allocations():
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
    weighted = reconstruct_stock_flow(**common, exit_policy="hazard_weighted")
    assert weighted.additional_exit_by_cohort[1, 0] > weighted.additional_exit_by_cohort[1, 1]
    required = weighted.additional_exit[1]
    observations = np.zeros((2, 3))
    observations[1, 1] = required
    observed = reconstruct_stock_flow(**common, exit_policy="observed", observed_exits=observations)
    assert observed.additional_exit_by_cohort[1, 1] == pytest.approx(required)
