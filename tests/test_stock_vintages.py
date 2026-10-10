import json
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
import yaml
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from iam_preprocessor.cli import app
from iam_preprocessor.exceptions import DataValidationError, IamPreprocessorError
from iam_preprocessor.filtering import filter_variables
from iam_preprocessor.io import read_frame, sha256_file
from iam_preprocessor.stock_config import load_stock_config
from iam_preprocessor.stock_vintages import (
    PREFIX,
    annual_inflows,
    enrich_stock_vintages,
    prepare_stock_vintages,
)


@pytest.fixture
def inputs(tmp_path):
    frame = pd.DataFrame(
        [
            {
                "Model": "REMIND",
                "Scenario": "test",
                "Region": "EUR",
                "Variable": v,
                "Unit": u,
                "2020": a,
                "2025": b,
                "2030": c,
            }
            for v, u, a, b, c in [
                ("Stock|Cars", "million veh", 10, 12, 14),
                ("Sales|Cars", "million veh", 1, 2, 3),
                ("Tech|Cars|Lifetime", "years", 10, 12, 14),
                ("ES|Cars", "billion pkm/yr", 100, 150, 200),
            ]
        ]
    )
    observations = tmp_path / "cohorts.csv"
    pd.DataFrame({"cohort": [2010, 2020], "amount": [2, 8], "service_factor": [0.5, 1.125]}).to_csv(
        observations, index=False
    )
    config = {
        "schema_version": 1,
        "model": "REMIND",
        "scenario": "test",
        "reference_year": 2020,
        "end_year": 2030,
        "assets": [
            {
                "id": "cars",
                "region": "EUR",
                "mode": "stock",
                "exit_policy": "proportional",
                "stock": {"variable": "Stock|Cars", "unit": "million veh"},
                "inflow": {"variable": "Sales|Cars", "unit": "million veh"},
                "service": {"variable": "ES|Cars", "unit": "billion pkm/yr"},
                "inflow_timing": {"kind": "sampled_annual", "provenance": "test sampled rates"},
                "lifetime": {
                    "distribution": "weibull",
                    "initial_mean": 15,
                    "shape": 3,
                    "source": {"variable": "Tech|Cars|Lifetime", "unit": "years"},
                    "interpretation": "explicit mean-life assumption",
                    "provenance": "test",
                },
                "initial": {"kind": "observed_shares", "file": "cohorts.csv", "provenance": "test"},
                "service_weighting": {
                    "kind": "observed_factors",
                    "future_factor": 1,
                    "annual_age_decay": 0,
                    "provenance": "test",
                },
            }
        ],
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    source = tmp_path / "remind_test.mif"
    frame.to_csv(source, sep=";", index=False)
    return frame, config, config_path, source


def test_initial_shares_service_shares_and_original_anchor_preservation(inputs):
    frame, _, path, _ = inputs
    result, diag = enrich_stock_vintages(frame, load_stock_config(path))
    pd.testing.assert_frame_equal(
        result.iloc[: len(frame)][frame.columns].reset_index(drop=True), frame, check_dtype=False
    )
    values = result.set_index("Variable")
    assert values.at[PREFIX + "cars|Stock Share|Vintage|2010", "2020"] == pytest.approx(0.2)
    assert values.at[PREFIX + "cars|Service Share|Vintage|2010", "2020"] == pytest.approx(0.1)
    assert values.at["Stock|Cars", "2021"] == pytest.approx(10.4)
    assert abs(diag[0]["maximum_balance_residual"]) < 1e-12
    assert diag[0]["observation_sha256"]
    for family in ("Stock Share", "Service Share"):
        subset = values.loc[values.index.str.startswith(PREFIX + f"cars|{family}|Vintage|")]
        np.testing.assert_allclose(subset[[str(y) for y in range(2020, 2031)]].sum(), 1)


def test_period_rates_preserve_integrals_and_support_irregular_explicit_windows():
    timing = {
        "kind": "reported_periods",
        "periods": [
            {"anchor": 2060, "start": 2058, "end": 2062},
            {"anchor": 2070, "start": 2063, "end": 2072},
        ],
    }
    rates = annual_inflows({2060: 2, 2070: 3}, range(2058, 2073), timing)
    assert sum(rates[:5]) == 10
    assert sum(rates[5:]) == 30
    with pytest.raises(DataValidationError, match="cover"):
        annual_inflows({2060: 2, 2070: 3}, range(2057, 2073), timing)
    timing["periods"][1]["start"] = 2062
    with pytest.raises(DataValidationError, match="Overlapping"):
        annual_inflows({2060: 2, 2070: 3}, range(2058, 2073), timing)


def test_sampled_sales_interpolation_does_not_claim_period_integral():
    np.testing.assert_allclose(
        annual_inflows({2020: 1, 2025: 6}, [2021, 2022], {"kind": "sampled_annual"}), [2, 3]
    )


def test_filter_encrypt_and_cli_roundtrip(inputs, tmp_path):
    _, _, config, source = inputs
    key = Fernet.generate_key()
    key_path = tmp_path / "key.txt"
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    result = CliRunner().invoke(
        app,
        [
            "stock-vintages",
            str(source),
            "--config",
            str(config),
            "-o",
            str(tmp_path / "out"),
            "--filter-output",
            "--encrypt-to",
            str(tmp_path / "encrypted"),
            "--key-file",
            str(key_path),
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(next((tmp_path / "out").glob("*report.json")).read_text())
    plain = read_frame(report["output_path"])
    assert plain["Variable"].str.startswith(PREFIX).sum() > 10
    assert sha256_file(report["output_path"]) == report["output_sha256"]
    assert (
        Fernet(key).decrypt(
            (tmp_path / "encrypted" / (source.stem + "_stock_vintages.csv")).read_bytes()
        )
        == (tmp_path / "out" / (source.stem + "_stock_vintages.csv")).read_bytes()
    )
    assert report["assumptions"]["origin"] == "reconstructed_not_native"
    assert filter_variables(plain).equals(plain)
    with pytest.raises(IamPreprocessorError, match="already exists"):
        prepare_stock_vintages(source, tmp_path / "out", config)


@pytest.mark.parametrize("problem", ["scenario", "unit", "missing", "duplicate", "enriched", "nan"])
def test_rejects_ambiguous_or_invalid_inputs(inputs, problem):
    frame, _, path, _ = inputs
    bad = frame.copy()
    if problem == "scenario":
        bad.loc[0, "Scenario"] = "other"
    elif problem == "unit":
        bad.loc[0, "Unit"] = "vehicles"
    elif problem == "missing":
        bad = bad.iloc[1:]
    elif problem == "duplicate":
        bad = pd.concat([bad, bad.iloc[:1]])
    elif problem == "enriched":
        bad.loc[0, "Variable"] = PREFIX + "cars|Coverage"
    else:
        bad.loc[0, "2025"] = np.nan
    with pytest.raises(DataValidationError):
        enrich_stock_vintages(bad, load_stock_config(path))


@pytest.mark.parametrize(
    "problem", ["typo", "life", "future", "shape", "mean_and_source", "extra_periods"]
)
def test_rejects_bad_configuration(inputs, problem):
    _, config, path, _ = inputs
    a = config["assets"][0]
    if problem == "typo":
        a["mod"] = "stock"
    elif problem == "life":
        a["lifetime"]["initial_mean"] = -1
    elif problem == "future":
        config["end_year"] = 2101
    elif problem == "shape":
        a["lifetime"]["shape"] = True
    elif problem == "mean_and_source":
        a["lifetime"]["mean"] = 20
    else:
        a["inflow_timing"]["periods"] = []
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(DataValidationError):
        load_stock_config(path)


def test_equilibrium_is_explicit_and_has_normalized_shares(inputs):
    frame, config, path, _ = inputs
    a = config["assets"][0]
    a["initial"] = {
        "kind": "equilibrium",
        "maximum_age": 60,
        "provenance": "stationary inflow prior",
    }
    a["service_weighting"] = {
        "kind": "equal",
        "annual_age_decay": 0,
        "provenance": "equal use prior",
    }
    path.write_text(yaml.safe_dump(config))
    enriched, _ = enrich_stock_vintages(frame, load_stock_config(path))
    s = enriched.loc[enriched.Variable.str.contains(r"Stock Share\|Vintage\|")]
    assert s["2020"].sum() == pytest.approx(1)


def test_no_service_from_zero_stock_and_no_extrapolation(inputs):
    frame, config, path, _ = inputs
    config["end_year"] = 2031
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(DataValidationError, match="extrapolation"):
        enrich_stock_vintages(frame, load_stock_config(path))
    config["end_year"] = 2030
    path.write_text(yaml.safe_dump(config))
    frame.loc[0, "2030"] = 0
    with pytest.raises(DataValidationError, match="Positive IAM service"):
        enrich_stock_vintages(frame, load_stock_config(path))


def test_inflow_mode_reports_stock_residual_and_does_not_enforce_stock(inputs):
    frame, config, path, _ = inputs
    config = deepcopy(config)
    config["assets"][0].update(mode="inflow", exit_policy="error")
    path.write_text(yaml.safe_dump(config))
    _, diagnostics = enrich_stock_vintages(frame, load_stock_config(path))
    assert diagnostics[0]["maximum_absolute_inflow_residual"] == 0
    assert diagnostics[0]["maximum_absolute_stock_residual"] > 0


def test_new_cohort_exposure_changes_service_only(inputs):
    frame, _, path, _ = inputs
    config = load_stock_config(path)
    baseline, _ = enrich_stock_vintages(frame, config)
    config["assets"][0]["service_weighting"]["new_cohort_exposure"] = 0.5
    changed, _ = enrich_stock_vintages(frame, config)
    old, new = baseline.set_index("Variable"), changed.set_index("Variable")
    assert (
        new.at[PREFIX + "cars|Service Share|Vintage|2021", "2021"]
        < old.at[PREFIX + "cars|Service Share|Vintage|2021", "2021"]
    )
    selected = old.index.str.startswith(PREFIX + "cars|Stock")
    pd.testing.assert_frame_equal(old.loc[selected], new.loc[selected])
    config["assets"][0]["service_weighting"]["maximum_service_per_stock"] = 0.01
    with pytest.raises(DataValidationError, match="per-stock bound"):
        enrich_stock_vintages(frame, config)


def test_shared_asset_id_cannot_hide_unit_differences_between_regions(inputs):
    _, config, path, _ = inputs
    second = deepcopy(config["assets"][0])
    second["region"] = "USA"
    second["stock"]["unit"] = "vehicles"
    second["inflow"]["unit"] = "vehicles"
    config["assets"].append(second)
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(DataValidationError, match="consistent units"):
        load_stock_config(path)


def test_joint_fits_complete_windows_before_trimming_export(inputs):
    frame, config, path, _ = inputs
    config["end_year"] = 2028
    asset = config["assets"][0]
    asset.update(
        mode="joint",
        annualisation={
            "inflow_constraints": "penalized",
            "reference_weight": 0.01,
            "inflow_weight": 10,
            "provenance": "Explicit test smoothing/fit weights",
        },
    )
    asset["inflow_timing"] = {
        "kind": "reported_periods",
        "provenance": "Test period means",
        "periods": [
            {"anchor": 2025, "start": 2021, "end": 2025},
            {"anchor": 2030, "start": 2026, "end": 2030},
        ],
    }
    path.write_text(yaml.safe_dump(config))
    enriched, diagnostics = enrich_stock_vintages(frame, load_stock_config(path))
    joint = diagnostics[0]["annualisation"]
    assert joint["solve_years"][-1] == 2030
    assert joint["flow_constraints"][-1]["years"] == list(range(2026, 2031))
    values = enriched.set_index("Variable")
    assert values.at[PREFIX + "cars|Coverage", "2028"] == 1
    assert np.isnan(values.at[PREFIX + "cars|Coverage", "2030"])
    assert not values.index.str.endswith("|Vintage|2029").any()
    assert values.at[PREFIX + "cars|Stock", "2025"] == pytest.approx(12)
    pd.testing.assert_frame_equal(
        enriched.iloc[: len(frame)][frame.columns].reset_index(drop=True), frame, check_dtype=False
    )


def test_joint_no_extra_exits_does_not_require_linear_intermediate_stocks(inputs):
    from iam_preprocessor.stock_model import survival_matrix

    frame, config, path, _ = inputs
    years = np.arange(2020, 2031)
    frame = frame.astype({str(y): float for y in (2020, 2025, 2030)})
    sf = survival_matrix(years.tolist(), np.full(len(years), 10), distribution="weibull", shape=3)
    pd.DataFrame({"cohort": [2020], "amount": [100]}).to_csv(
        path.parent / "cohorts.csv", index=False
    )
    frame.loc[0, ["2020", "2025", "2030"]] = 100 * sf[[0, 5, 10], 0]
    frame.loc[1, ["2020", "2025", "2030"]] = 0
    asset = config["assets"][0]
    asset.update(
        mode="joint",
        exit_policy="error",
        annualisation={
            "inflow_constraints": "strict",
            "reference_weight": 0.01,
            "inflow_weight": 10,
            "provenance": "Pure natural survival test",
        },
    )
    asset["lifetime"].pop("source")
    asset["lifetime"].update(initial_mean=10, mean=10)
    asset["service_weighting"] = {"kind": "equal", "annual_age_decay": 0, "provenance": "test"}
    path.write_text(yaml.safe_dump(config))
    enriched, diagnostics = enrich_stock_vintages(frame, load_stock_config(path))
    values = enriched.set_index("Variable")
    np.testing.assert_allclose(
        values.loc[PREFIX + "cars|Stock", list(map(str, years))].to_numpy(float),
        100 * sf[:, 0],
        atol=1e-8,
    )
    assert diagnostics[0]["total_additional_exits"] == pytest.approx(0)


@pytest.mark.parametrize(
    "problem", ["missing", "typo", "negative_weight", "boolean_weight", "unused"]
)
def test_joint_configuration_is_explicit(inputs, problem):
    _, config, path, _ = inputs
    asset = config["assets"][0]
    asset.update(
        mode="joint",
        annualisation={
            "inflow_constraints": "strict",
            "reference_weight": 0.01,
            "inflow_weight": 10,
            "provenance": "Test policy",
        },
    )
    if problem == "missing":
        asset.pop("annualisation")
    elif problem == "typo":
        asset["annualisation"]["inflow_constraints"] = "guess"
    elif problem == "negative_weight":
        asset["annualisation"]["reference_weight"] = -1
    elif problem == "boolean_weight":
        asset["annualisation"]["inflow_weight"] = True
    else:
        asset["mode"] = "stock"
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(DataValidationError):
        load_stock_config(path)


def test_age_usage_profile_changes_only_service_and_advances_each_cohort(inputs, tmp_path):
    frame, config, path, _ = inputs
    baseline, _ = enrich_stock_vintages(frame, load_stock_config(path))
    usage = tmp_path / "age.csv"
    pd.DataFrame({"age": range(31), "factor": [1 / (1 + a) for a in range(31)]}).to_csv(
        usage, index=False
    )
    config["assets"][0]["service_weighting"] = dict(
        kind="age_profile",
        age_profile_file="age.csv",
        tail_policy="hold_last",
        annual_age_decay=0,
        provenance="Test annual-age curve",
    )
    path.write_text(yaml.safe_dump(config))
    enriched, diagnostics = enrich_stock_vintages(frame, load_stock_config(path))
    a, b = [v.set_index("Variable") for v in (baseline, enriched)]
    stocks = a.index.str.startswith(PREFIX + "cars|Stock")
    pd.testing.assert_frame_equal(a.loc[stocks], b.loc[stocks])
    for y in (2020, 2021, 2025):
        service_ratio = (
            b.at[PREFIX + "cars|Service Share|Vintage|2010", str(y)]
            / b.at[PREFIX + "cars|Service Share|Vintage|2020", str(y)]
        )
        stock_ratio = (
            b.at[PREFIX + "cars|Stock|Vintage|2010", str(y)]
            / b.at[PREFIX + "cars|Stock|Vintage|2020", str(y)]
        )
        assert service_ratio / stock_ratio == pytest.approx((1 + y - 2020) / (1 + y - 2010))
    assert diagnostics[0]["age_profile_sha256"] == sha256_file(usage)
    config["assets"][0]["service_weighting"]["tail_policy"] = "guess"
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(DataValidationError, match="hold_last"):
        load_stock_config(path)
