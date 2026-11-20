import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from iam_preprocessor.cli import app
from iam_preprocessor.exceptions import DataValidationError, IamPreprocessorError
from iam_preprocessor.io import sha256_file
from iam_preprocessor.stock_config import load_stock_config
from iam_preprocessor.stock_vintages import PREFIX, calculate_stock_vintages, prepare_stock_vintages
from iam_preprocessor.stock_workflow import write_stock_config
from iam_preprocessor.vintage_inputs import annual_additions


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


def vintage_value(table, metric, year, cohort):
    return table.set_index(["metric", "year", "cohort_year"])["value"].get(
        (metric, year, cohort), 0
    )


def annual_stock(table, years):
    stock = table.loc[table["metric"].eq("stock")]
    return stock.groupby("year")["value"].sum().reindex(years, fill_value=0).to_numpy()


def test_initial_shares_and_service_shares_leave_scenario_table_untouched(inputs):
    frame, _, path, _ = inputs
    original = frame.copy(deep=True)
    table, diag = calculate_stock_vintages(frame, load_stock_config(path))
    pd.testing.assert_frame_equal(frame, original)
    assert vintage_value(table, "stock_share", 2020, 2010) == pytest.approx(0.2)
    assert vintage_value(table, "service_share", 2020, 2010) == pytest.approx(0.1)
    assert annual_stock(table, [2021])[0] == pytest.approx(10.4)
    assert abs(diag[0]["maximum_balance_residual"]) < 1e-12
    assert diag[0]["observation_sha256"]
    for metric in ("stock_share", "service_share"):
        shares = table.loc[table.metric.eq(metric)].groupby("year")["value"].sum()
        assert shares.index.tolist() == list(range(2020, 2031))
        np.testing.assert_allclose(shares, 1)


@pytest.mark.parametrize("model", ["IMAGE 3.4", "MESSAGEix-GLOBIOM 2.0", "Other IAM"])
def test_model_neutral_cli_uses_yaml_and_reconstructs(inputs, tmp_path, model):
    frame, config, mapping, source = inputs
    frame["Model"] = model
    frame["Scenario"] = "model-specific run"
    names = dict(zip(frame.Variable, ["installed", "new", "lifetime", "use"], strict=True))
    frame["Variable"] = frame["Variable"].map(names)
    other_region = frame.assign(Region="World")
    other_region.loc[other_region.Variable.eq("installed"), ["2020", "2025", "2030"]] *= 2
    frame = pd.concat([frame, other_region], ignore_index=True)
    frame.to_csv(source, sep=";", index=False)
    asset = config["assets"][0]
    asset.pop("region")
    if model == "IMAGE 3.4":
        lifetime = asset["lifetime"]
        lifetime["distribution"] = "quartic"
        lifetime["initial_maximum"] = lifetime.pop("initial_mean")
        lifetime.pop("shape")
    for selector in (
        asset["stock"],
        asset["inflow"],
        asset["lifetime"]["source"],
        asset["service"],
    ):
        selector["variable"] = names[selector["variable"]]
    mapping.write_text(yaml.safe_dump({"assets": [asset]}))
    destination = tmp_path / "configured" / "stocks.yaml"
    runner = CliRunner()
    result = runner.invoke(
        app, ["stock-config", str(source), "--mapping", str(mapping), "-o", str(destination)]
    )
    assert result.exit_code == 0, result.output
    bound = load_stock_config(destination)
    assert (bound["model"], bound["scenario"]) == (model, "model-specific run")
    assert [asset["region"] for asset in bound["assets"]] == ["EUR", "World"]
    for asset in bound["assets"]:
        assert Path(asset["initial"]["file"]) == tmp_path / "cohorts.csv"
    inventory_path = tmp_path / "stock-inventory.csv"
    audit = runner.invoke(
        app,
        ["stock-inventory", str(source), "--config", str(destination), "-o", str(inventory_path)],
    )
    assert audit.exit_code == 0, audit.output
    inventory = pd.read_csv(inventory_path, sep=";")
    assert set(inventory["variable"]) == {"installed", "new", "lifetime", "use"}
    assert set(inventory["status"]) == {"available"}
    assert set(inventory["region"]) == {"EUR", "World"}
    output = tmp_path / "output"
    result = runner.invoke(
        app,
        [
            "stock-vintages",
            str(source),
            "--config",
            str(destination),
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    vintages = pd.read_parquet(next(output.glob("*/vintages.parquet")))
    assert set(vintages["model"]) == {model}
    assert set(vintages["scenario"]) == {"model-specific run"}
    opening = vintages.loc[vintages["year"].eq(2020) & vintages["metric"].eq("stock")]
    assert opening.groupby("region")["value"].sum().to_dict() == pytest.approx(
        {"EUR": 10, "World": 20}
    )


def test_stock_config_reports_missing_inputs_in_any_region(inputs, tmp_path):
    frame, config, mapping, source = inputs
    asset = config["assets"][0]
    asset.pop("region")
    only_stock = frame.loc[frame["Variable"].eq(asset["stock"]["variable"])].assign(Region="USA")
    pd.concat([frame, only_stock], ignore_index=True).to_csv(source, sep=";", index=False)
    mapping.write_text(yaml.safe_dump(config))
    destination = tmp_path / "stocks.yaml"

    with pytest.raises(DataValidationError, match="USA.*Sales"):
        write_stock_config(source, destination, mapping=mapping)
    assert not destination.exists()


def test_composition_proxy_is_not_reported_as_direct_evidence(inputs):
    frame, config, path, _ = inputs
    config["assets"][0]["initial"]["evidence_kind"] = "composition_proxy"
    path.write_text(yaml.safe_dump(config))
    table, diagnostics = calculate_stock_vintages(frame, load_stock_config(path))
    diagnostic = diagnostics[0]
    assert diagnostic["opening_evidence_share"] == pytest.approx(1)
    assert diagnostic["opening_direct_evidence_share"] == pytest.approx(0)
    assert diagnostic["opening_proxy_evidence_share"] == pytest.approx(1)
    opening = table.loc[table["year"].eq(2020) & table["metric"].eq("stock")]
    assert set(opening["evidence_basis"]) == {"observed_proxy"}


def test_observation_file_can_distinguish_proxy_cohorts_from_prior(inputs):
    _, config, path, _ = inputs
    observation = path.parent / Path(config["assets"][0]["initial"]["file"])
    pd.DataFrame(
        {
            "cohort": [2010, 2020],
            "amount": [2, 8],
            "service_factor": [0.5, 1.125],
            "evidence_basis": ["prior", "observed_proxy"],
        }
    ).to_csv(observation, index=False)
    table, diagnostics = calculate_stock_vintages(inputs[0], load_stock_config(path))
    diagnostic = diagnostics[0]
    assert diagnostic["opening_prior_share"] == pytest.approx(0.2)
    assert diagnostic["opening_proxy_evidence_share"] == pytest.approx(0.8)
    opening = table.loc[table["year"].eq(2020) & table["metric"].eq("stock")]
    assert opening.set_index("cohort_year")["evidence_basis"].to_dict() == {
        2010: "prior",
        2020: "observed_proxy",
    }


def test_initial_evidence_kind_is_strict(inputs):
    _, config, path, _ = inputs
    config["assets"][0]["initial"]["evidence_kind"] = "maybe_observed"
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(DataValidationError, match="evidence_kind"):
        load_stock_config(path)


def test_equilibrium_initialization_allows_zero_opening_stock(inputs):
    frame, config, path, _ = inputs
    frame.loc[frame.Variable.eq("Stock|Cars"), "2020"] = 0
    frame.loc[frame.Variable.eq("ES|Cars"), "2020"] = 0
    asset = config["assets"][0]
    asset["initial"] = {
        "kind": "equilibrium",
        "maximum_age": 20,
        "provenance": "test zero initial stock",
    }
    asset["service_weighting"] = {
        "kind": "equal",
        "annual_age_decay": 0,
        "provenance": "test",
    }
    path.write_text(yaml.safe_dump(config))
    table, _ = calculate_stock_vintages(frame, load_stock_config(path))
    assert annual_stock(table, [2020])[0] == 0


def test_remind_maximum_lifetime_configuration_drives_conditional_survival(inputs):
    frame, config, path, _ = inputs
    law = config["assets"][0]["lifetime"]
    law.clear()
    law.update(
        distribution="remind",
        initial_maximum=30,
        source={"variable": "Tech|Cars|Lifetime", "unit": "years"},
        interpretation="REMIND maximum lifetime",
        provenance="test REMIND technical note",
    )
    path.write_text(yaml.safe_dump(config))
    table, _ = calculate_stock_vintages(frame, load_stock_config(path))
    expected = 2 * (1 - (11 / 30) ** 4) / (1 - (10 / 30) ** 4)
    assert vintage_value(table, "stock", 2021, 2010) == pytest.approx(expected)


def test_remind_lifetime_schema_rejects_mean_and_shape_fields(inputs):
    _, config, path, _ = inputs
    law = config["assets"][0]["lifetime"]
    law.clear()
    law.update(
        distribution="remind",
        initial_maximum=30,
        maximum=30,
        mean=24,
        interpretation="invalid mixed semantics",
        provenance="test",
    )
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(DataValidationError, match="do not accept mean or shape"):
        load_stock_config(path)


def test_period_rates_preserve_integrals_and_support_irregular_explicit_windows():
    timing = {
        "kind": "reported_periods",
        "periods": [
            {"anchor": 2060, "start": 2058, "end": 2062},
            {"anchor": 2070, "start": 2063, "end": 2072},
        ],
    }
    rates = annual_additions({2060: 2, 2070: 3}, range(2058, 2073), timing)
    assert sum(rates[:5]) == 10
    assert sum(rates[5:]) == 30
    with pytest.raises(DataValidationError, match="cover"):
        annual_additions({2060: 2, 2070: 3}, range(2057, 2073), timing)
    timing["periods"][1]["start"] = 2062
    with pytest.raises(DataValidationError, match="Overlapping"):
        annual_additions({2060: 2, 2070: 3}, range(2058, 2073), timing)


def test_sampled_sales_interpolation_does_not_claim_period_integral():
    np.testing.assert_allclose(
        annual_additions({2020: 1, 2025: 6}, [2021, 2022], {"kind": "sampled_annual"}), [2, 3]
    )


def test_stock_vintage_cli_writes_only_separate_package_and_report(inputs, tmp_path):
    _, _, config, source = inputs
    original = source.read_bytes()
    output = tmp_path / "out"
    result = CliRunner().invoke(
        app,
        ["stock-vintages", str(source), "--config", str(config), "-o", str(output)],
    )
    assert result.exit_code == 0, result.output
    assert source.read_bytes() == original

    report_path = output / f"{source.stem}_stock_vintages_report.json"
    package = output / f"{source.stem}_stock_vintages_v2"
    assert set(output.iterdir()) == {report_path, package}
    assert {path.name for path in package.iterdir()} == {
        "vintages.parquet",
        "datapackage.json",
        "validation.json",
    }
    report = json.loads(report_path.read_text())
    assert Path(report["output_path"]) == package / "vintages.parquet"
    assert sha256_file(report["output_path"]) == report["output_sha256"]
    assert report["assumptions"]["origin"] == "reconstructed_not_native"
    assert report["assumptions"]["software_versions"]["flodym"] == "1.1.0"
    assert "flodym_stock.py" in report["assumptions"]["implementation_sha256"]
    manifest = json.loads((package / "datapackage.json").read_text())
    assert manifest["schema_version"] == 2
    assert manifest["source"]["sha256"] == sha256_file(source)
    vintages = pd.read_parquet(package / "vintages.parquet")
    assert report["output_rows"] == len(vintages)
    assert set(vintages["metric"]) >= {
        "stock",
        "stock_share",
        "addition",
        "retirement_natural",
    }
    with pytest.raises(IamPreprocessorError, match="already exists"):
        prepare_stock_vintages(source, output, config)


def test_overwrite_cannot_replace_a_directory_containing_the_scenario(inputs, tmp_path):
    _, _, config, source = inputs
    package = tmp_path / f"{source.stem}_stock_vintages_v2"
    package.mkdir()
    nested_source = package / source.name
    nested_source.write_bytes(source.read_bytes())
    with pytest.raises(IamPreprocessorError, match="cannot contain the input scenario"):
        prepare_stock_vintages(nested_source, tmp_path, config, overwrite=True)
    assert nested_source.read_bytes() == source.read_bytes()


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
        calculate_stock_vintages(bad, load_stock_config(path))


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


@pytest.mark.parametrize("policy", ["oldest_first", "remove_by_hazard"])
def test_joint_mode_rejects_unimplemented_cohort_exit_allocations(inputs, policy):
    _, config, path, _ = inputs
    asset = config["assets"][0]
    asset.update(
        mode="joint",
        exit_policy=policy,
        annualisation={
            "inflow_constraints": "penalized",
            "reference_weight": 0.01,
            "inflow_weight": 10,
            "provenance": "test",
        },
    )
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(DataValidationError, match="Joint mode supports"):
        load_stock_config(path)


def test_hazard_exit_configuration_requires_flodym_policy_name(inputs):
    _, config, path, _ = inputs
    config["assets"][0]["exit_policy"] = "remove_by_hazard"
    path.write_text(yaml.safe_dump(config))
    assert load_stock_config(path)["assets"][0]["exit_policy"] == "remove_by_hazard"
    config["assets"][0]["exit_policy"] = "hazard_weighted"
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(DataValidationError, match="remove_by_hazard"):
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
    table, _ = calculate_stock_vintages(frame, load_stock_config(path))
    shares = table.loc[table.metric.eq("stock_share") & table.year.eq(2020), "value"]
    assert shares.sum() == pytest.approx(1)


def test_no_service_from_zero_stock_and_no_extrapolation(inputs):
    frame, config, path, _ = inputs
    config["end_year"] = 2031
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(DataValidationError, match="extrapolation"):
        calculate_stock_vintages(frame, load_stock_config(path))
    config["end_year"] = 2030
    path.write_text(yaml.safe_dump(config))
    frame.loc[0, "2030"] = 0
    with pytest.raises(DataValidationError, match="Positive IAM service"):
        calculate_stock_vintages(frame, load_stock_config(path))


def test_inflow_mode_reports_stock_residual_and_does_not_enforce_stock(inputs):
    frame, config, path, _ = inputs
    config = deepcopy(config)
    config["assets"][0].update(mode="inflow", exit_policy="error")
    path.write_text(yaml.safe_dump(config))
    _, diagnostics = calculate_stock_vintages(frame, load_stock_config(path))
    assert diagnostics[0]["maximum_absolute_inflow_residual"] == 0
    assert diagnostics[0]["maximum_absolute_stock_residual"] > 0


def test_strict_stock_flow_mode_preserves_both_input_series(inputs):
    frame, config, path, _ = inputs
    frame.loc[frame.Variable.eq("Stock|Cars"), ["2020", "2025", "2030"]] = [10, 15, 20]
    frame.loc[frame.Variable.eq("Sales|Cars"), ["2020", "2025", "2030"]] = [1, 1, 1]
    asset = config["assets"][0]
    asset.update(mode="stock_flow", exit_policy="error")
    asset["lifetime"] = {
        "distribution": "fixed",
        "initial_mean": 100,
        "mean": 100,
        "interpretation": "test",
        "provenance": "test",
    }
    asset["service_weighting"] = {
        "kind": "equal",
        "annual_age_decay": 0,
        "provenance": "test",
    }
    path.write_text(yaml.safe_dump(config))
    table, diagnostics = calculate_stock_vintages(frame, load_stock_config(path))
    np.testing.assert_allclose(
        annual_stock(table, range(2020, 2031)),
        np.arange(10, 21),
    )
    assert diagnostics[0]["maximum_absolute_stock_residual"] < 1e-12
    assert diagnostics[0]["maximum_absolute_inflow_residual"] < 1e-12


def test_warm_start_propagates_iam_additions_from_first_anchor(inputs):
    frame, config, path, _ = inputs
    frame.loc[frame.Variable.eq("Stock|Cars"), ["2020", "2025", "2030"]] = [10, 15, 20]
    frame.loc[frame.Variable.eq("Sales|Cars"), ["2020", "2025", "2030"]] = [1, 1, 1]
    config.update(schema_version=2, reference_year=2025)
    asset = config["assets"][0]
    asset.update(mode="stock_flow", exit_policy="error")
    asset["initial"] = {
        "kind": "warm_start",
        "base_kind": "equilibrium",
        "base_year": 2020,
        "maximum_age": 20,
        "acknowledge_prior": True,
        "provenance": "test legacy prior",
    }
    asset["lifetime"] = {
        "distribution": "fixed",
        "initial_mean": 100,
        "mean": 100,
        "interpretation": "test",
        "provenance": "test",
    }
    asset["service_weighting"] = {
        "kind": "equal",
        "annual_age_decay": 0,
        "provenance": "test",
    }
    path.write_text(yaml.safe_dump(config))
    vintages, diagnostics = calculate_stock_vintages(frame, load_stock_config(path))
    opening = vintages.loc[vintages["metric"].eq("stock") & vintages["year"].eq(2025)]
    assert opening.groupby("evidence_basis")["value"].sum().to_dict() == {
        "iam_addition": pytest.approx(5),
        "prior": pytest.approx(10),
    }
    assert diagnostics[0]["opening_prior_share"] == pytest.approx(2 / 3)


def test_new_cohort_exposure_changes_service_only(inputs):
    frame, _, path, _ = inputs
    config = load_stock_config(path)
    baseline, _ = calculate_stock_vintages(frame, config)
    config["assets"][0]["service_weighting"]["new_cohort_exposure"] = 0.5
    changed, _ = calculate_stock_vintages(frame, config)
    assert vintage_value(changed, "service_share", 2021, 2021) < vintage_value(
        baseline, "service_share", 2021, 2021
    )
    pd.testing.assert_frame_equal(
        baseline.loc[baseline.metric.isin(["stock", "stock_share"])].reset_index(drop=True),
        changed.loc[changed.metric.isin(["stock", "stock_share"])].reset_index(drop=True),
    )
    config["assets"][0]["service_weighting"]["maximum_service_per_stock"] = 0.01
    with pytest.raises(DataValidationError, match="per-stock bound"):
        calculate_stock_vintages(frame, config)


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
    table, diagnostics = calculate_stock_vintages(frame, load_stock_config(path))
    joint = diagnostics[0]["annualisation"]
    assert joint["solve_years"][-1] == 2030
    assert joint["flow_constraints"][-1]["years"] == list(range(2026, 2031))
    assert table.year.max() == 2028
    assert table.cohort_year.max() <= 2028
    assert annual_stock(table, [2025])[0] == pytest.approx(12)


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
    table, diagnostics = calculate_stock_vintages(frame, load_stock_config(path))
    np.testing.assert_allclose(
        annual_stock(table, years),
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
    baseline, _ = calculate_stock_vintages(frame, load_stock_config(path))
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
    table, diagnostics = calculate_stock_vintages(frame, load_stock_config(path))
    pd.testing.assert_frame_equal(
        baseline.loc[baseline.metric.isin(["stock", "stock_share"])].reset_index(drop=True),
        table.loc[table.metric.isin(["stock", "stock_share"])].reset_index(drop=True),
    )
    for y in (2020, 2021, 2025):
        service_ratio = vintage_value(table, "service_share", y, 2010) / vintage_value(
            table, "service_share", y, 2020
        )
        stock_ratio = vintage_value(table, "stock", y, 2010) / vintage_value(
            table, "stock", y, 2020
        )
        assert service_ratio / stock_ratio == pytest.approx((1 + y - 2020) / (1 + y - 2010))
    assert diagnostics[0]["age_profile_sha256"] == sha256_file(usage)
    config["assets"][0]["service_weighting"]["tail_policy"] = "guess"
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(DataValidationError, match="hold_last"):
        load_stock_config(path)
