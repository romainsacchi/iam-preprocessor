import json

import pandas as pd
import pytest

from iam_preprocessor.exceptions import DataValidationError
from iam_preprocessor.io import sha256_file
from iam_preprocessor.stock_package import (
    COLUMNS,
    validate_vintage_table,
    validation_contract,
    write_vintage_package,
)


def table():
    common = dict(
        model="REMIND",
        scenario="test",
        region="DEU",
        asset="pv",
        year=2020,
        cohort_year=2010,
        evidence_basis="observed",
    )
    return pd.DataFrame(
        [
            dict(common, metric="stock", value=2.0, unit="GW"),
            dict(common, metric="stock_share", value=1.0, unit="1"),
            dict(common, metric="service_share", value=1.0, unit="1"),
        ]
    )


def test_v2_contract_rejects_duplicates_unknown_metrics_and_same_year_retirement():
    valid = table()
    validate_vintage_table(valid)
    with pytest.raises(DataValidationError, match="Duplicate"):
        validate_vintage_table(pd.concat([valid, valid.iloc[:1]], ignore_index=True))
    bad = valid.copy()
    bad.loc[0, "metric"] = "mystery"
    with pytest.raises(DataValidationError, match="Unknown"):
        validate_vintage_table(bad)
    bad = valid.copy()
    bad.loc[0, ["metric", "year", "cohort_year", "unit"]] = [
        "retirement_additional",
        2020,
        2020,
        "GW/yr",
    ]
    with pytest.raises(DataValidationError, match="Same-year"):
        validate_vintage_table(bad)


def test_package_is_checksum_bound_and_parquet_is_canonical(tmp_path):
    source = tmp_path / "scenario.mif"
    source.write_text("scenario")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("config")
    diagnostics = [
        {
            "asset": "pv",
            "region": "DEU",
            "mode": "stock_flow",
            "maximum_balance_residual": 0,
            "maximum_absolute_stock_residual": 0,
            "maximum_absolute_inflow_residual": 0,
            "maximum_stock_target": 2,
            "negative_implied_exit_years": [],
            "implied_exits_exceed_opening_stock_years": [],
            "configuration": {"initial": {"kind": "observed_shares"}},
        }
    ]
    destination = tmp_path / "package"
    write_vintage_package(
        table(),
        destination,
        source_path=source,
        config_path=config_path,
        config={
            "model": "REMIND",
            "scenario": "test",
            "reference_year": 2020,
            "end_year": 2030,
        },
        diagnostics=diagnostics,
    )
    manifest = json.loads((destination / "datapackage.json").read_text())
    assert manifest["schema_version"] == 2
    assert manifest["source"]["sha256"] == sha256_file(source)
    parquet = next(row for row in manifest["resources"] if row["format"] == "parquet")
    assert parquet["sha256"] == sha256_file(destination / parquet["path"])
    pd.testing.assert_frame_equal(
        pd.read_parquet(destination / parquet["path"]), table()[COLUMNS], check_dtype=False
    )
    validation = json.loads((destination / "validation.json").read_text())
    assert validation["status"] == "warning"  # interpolation precision is disclosed


def test_joint_validation_uses_stock_anchors_and_marks_source_conflict_as_warning():
    diagnostics = [
        {
            "asset": "pv",
            "region": "DEU",
            "mode": "joint",
            "maximum_balance_residual": 1e-14,
            "maximum_absolute_stock_residual": 100,
            "maximum_absolute_inflow_residual": 10,
            "maximum_stock_target": 100,
            "negative_implied_exit_years": [2021],
            "implied_exits_exceed_opening_stock_years": [],
            "opening_evidence_share": 1,
            "opening_prior_share": 0,
            "annualisation": {
                "stock_anchor_max_absolute_residual": 1e-12,
                "exact_inflow_constraints_feasible": False,
                "actual_sum_absolute_rate_residual": 10,
            },
        }
    ]
    result = validation_contract(diagnostics)
    assert result["status"] == "warning"
    checks = result["assets"][0]["checks"]
    assert checks["numerical_residuals"]["status"] == "pass"
    assert checks["structural_consistency"]["status"] == "warning"
