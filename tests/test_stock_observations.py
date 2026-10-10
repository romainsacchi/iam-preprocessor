"""Observation selection, missing-age accounting and rare surviving old cohorts."""

import numpy as np
import pytest

from iam_preprocessor.exceptions import DataValidationError
from iam_preprocessor.stock_model import reconstruct, survival_matrix
from iam_preprocessor.stock_observations import curate_power, model_observation, vehicle_count


def generator(ident, year=2020, capacity=10, **kwargs):
    record = {
        "Plant Code": 1,
        "Generator ID": ident,
        "Technology": "Onshore Wind Turbine",
        "State": "TX",
        "Status": "OP",
        "Associated with Combined Heat and Power System": "N",
        "Operating Year": year,
        "Nameplate Capacity (MW)": capacity,
    }
    record.update(kwargs)
    return record


def test_eia_selection_reconciles_capacity_and_retains_unknown_dates():
    rows = [
        generator("a", 2000, 20),
        generator("b", None, 5),
        generator("c", capacity=3, Status="SB"),
        generator("d", capacity=4, State="PR"),
        generator("e", capacity=6, **{"Associated with Combined Heat and Power System": "Y"}),
        generator("f", capacity=100, Technology="Nuclear"),
    ]
    result = curate_power(rows, "wind-onshore")
    assert result["total"] == 25
    assert result["selected_capacity_mw"] == 38
    assert result["unknown"] == 5
    assert result["included_generator_records"] == 2
    assert sum(r["capacity_mw"] for r in result["excluded"].values()) == 13
    assert model_observation(result) == [{"cohort": 2000, "amount": 25}]


def test_generator_duplicates_and_future_dates_cannot_be_hidden_by_aggregation():
    with pytest.raises(ValueError, match="Duplicate"):
        curate_power([generator("a"), generator("a")], "wind-onshore")
    with pytest.raises(ValueError, match="operating year"):
        curate_power([generator("a", 2023)], "wind-onshore")


def test_unknown_dates_are_assigned_once_without_changing_known_composition():
    record = dict(cohorts={2000: 10, 2020: 30}, unknown=10, total=50)
    assert model_observation(record) == [
        {"cohort": 2000, "amount": 12.5},
        {"cohort": 2020, "amount": 37.5},
    ]
    with pytest.raises(ValueError, match="unaccounted"):
        model_observation(dict(record, total=51))
    with pytest.raises(ValueError, match="unaccounted"):
        model_observation(dict(cohorts={1800: 1}, unknown=0, total=1))


def test_numeric_ods_values_preserve_rounded_low_counts():
    assert vehicle_count(("[low]", "0.001")) == 1
    assert vehicle_count(("0.0", "0.049")) == 49
    with pytest.raises(ValueError, match="Missing numeric"):
        vehicle_count(("[z]", None))
    with pytest.raises(ValueError, match="non-integer"):
        vehicle_count(("0", "0.0005"))


def test_conditional_weibull_preserves_observed_tail_when_absolute_survival_underflows():
    years = np.arange(1900, 2031)
    means = np.full(len(years), 12)
    raw = survival_matrix(years.tolist(), means, distribution="weibull", shape=3)
    assert raw[122, 0] == 0
    conditional = survival_matrix(
        years.tolist(), means, distribution="weibull", shape=3, conditional_year=2022
    )
    assert conditional[122, 0] == 1
    assert 0 < conditional[123, 0] < 1
    initial = np.zeros(len(years))
    initial[0], initial[120] = 1, 99
    result = reconstruct(
        years=years,
        reference_year=2022,
        initial=initial,
        survival=conditional,
        targets=np.full(9, 100),
        mode="stock",
        exit_policy="proportional",
    )
    from math import gamma

    expected = np.exp(-((123 / (12 / gamma(4 / 3))) ** 3 - (122 / (12 / gamma(4 / 3))) ** 3))
    assert result.stock[1, 0] == pytest.approx(expected, rel=1e-12)
    np.testing.assert_allclose(result.stock.sum(axis=1), 100)
    # Future entrants and ordinary conditional ratios are unchanged.
    np.testing.assert_array_equal(conditional[:, 123:], raw[:, 123:])
    assert conditional[123, 120] == pytest.approx(raw[123, 120] / raw[122, 120])


def test_conditioning_does_not_rescue_impossible_fixed_lifetime_observations():
    years = np.arange(2000, 2025)
    sf = survival_matrix(
        years.tolist(), np.full(len(years), 10), distribution="fixed", conditional_year=2022
    )
    initial = np.r_[1, np.zeros(len(years) - 1)]
    with pytest.raises(DataValidationError, match="impossible"):
        reconstruct(
            years=years,
            reference_year=2022,
            initial=initial,
            survival=sf,
            targets=np.ones(3),
            mode="stock",
            exit_policy="proportional",
        )


def test_car_fuel_selection_keeps_unknowns_and_never_adds_parent_total(monkeypatch):
    from iam_preprocessor import stock_observations as observations

    header = [
        "Geography",
        "Time",
        "Unit",
        "Body",
        "Fuel",
        "2000",
        "2022",
        "2023",
        "Unknown first use",
        "Total",
    ]
    rows = [[(h, None) for h in header]]
    for fuel, old, new, unknown in (
        ("PETROL", 10, 20, 2),
        ("DIESEL", 5, 15, 3),
        ("Total", 100, 100, 100),
        ("HYBRID ELECTRIC (PETROL)", 50, 50, 50),
    ):
        row = [
            (v, None)
            for v in ("United Kingdom", "2022 Q4 (end December)", "Thousands", "Cars", fuel)
        ]
        row += [("rounded", str(v / 1000)) for v in (old, new)]
        row += [("[z]", None)]
        row += [("rounded", str(v / 1000)) for v in (unknown, old + new + unknown)]
        rows.append(row)
    monkeypatch.setattr(observations, "ods_rows", lambda *args: iter(rows))
    result = observations.curate_liquid_cars(None)
    assert result["combined"] == dict(cohorts={2000: 15, 2022: 35}, unknown=5, total=55)
    assert result["petrol"]["total"] == 32
    assert result["diesel"]["total"] == 23
    rows.append(rows[1])
    with pytest.raises(ValueError, match="duplicate"):
        observations.curate_liquid_cars(None)
