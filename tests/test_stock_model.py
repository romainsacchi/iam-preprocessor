"""Analytical cases and independent stock/inflow-driven flodym comparisons."""

import numpy as np
import pytest
from flodym import Dimension, DimensionSet, FixedLifetime, InflowDrivenDSM, StockDrivenDSM

from iam_preprocessor.exceptions import DataValidationError
from iam_preprocessor.stock_model import reconstruct, survival_matrix


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
    years = list(range(2020, 2030))
    targets = np.linspace(10, 20, 10) if mode == "stock" else np.arange(1, 11, dtype=float)
    dims = DimensionSet(dim_list=[Dimension(name="time", letter="t", items=years)])
    law = FixedLifetime(dims=dims, mean=3, inflow_at="end")
    cls = StockDrivenDSM if mode == "stock" else InflowDrivenDSM
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


def test_zero_stock_and_restart():
    r = run(
        years=[2020, 2021, 2022], initial=[1, 0, 0], targets=[1, 0, 2], exit_policy="proportional"
    )
    np.testing.assert_allclose(r.stock.sum(axis=1), [1, 0, 2])
    assert r.inflow[-1] == 2
