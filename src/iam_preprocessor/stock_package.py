"""Files that store the estimated stock by build year."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from .exceptions import DataValidationError, IamPreprocessorError
from .io import sha256_file
from .stock_evidence import evidence_descriptor

SCHEMA_VERSION = 2
KEY = ["model", "scenario", "region", "asset", "year", "cohort_year", "metric"]
COLUMNS = KEY + ["value", "unit", "evidence_basis"]
METRICS = {
    "stock": "quantity",
    "stock_share": "share",
    "service_share": "share",
    "service": "service",
    "addition": "flow",
    "retirement_natural": "flow",
    "retirement_additional": "flow",
    "legacy_unallocated": "quantity",
}


def validate_vintage_table(table: pd.DataFrame) -> None:
    """Check the result types and ensure that each row appears once."""
    missing = set(COLUMNS) - set(table.columns)
    if missing:
        raise DataValidationError(f"Vintage table is missing columns: {sorted(missing)}")
    if table.empty:
        raise DataValidationError("Vintage table cannot be empty.")
    if table.duplicated(KEY).any():
        sample = table.loc[table.duplicated(KEY, keep=False), KEY].head().to_dict("records")
        raise DataValidationError(f"Duplicate vintage rows: {sample}")
    unknown = set(table["metric"]) - METRICS.keys()
    if unknown:
        raise DataValidationError(f"Unknown vintage metrics: {sorted(unknown)}")
    values = pd.to_numeric(table["value"], errors="coerce").to_numpy(float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise DataValidationError("Vintage values must be finite and nonnegative.")
    if table[["model", "scenario", "region", "asset", "metric", "unit"]].isna().any().any():
        raise DataValidationError("Vintage identity, metric and unit fields cannot be null.")
    evidence = {"prior", "observed", "observed_proxy", "iam_addition"}
    unknown_evidence = set(table["evidence_basis"]) - evidence
    if unknown_evidence:
        raise DataValidationError(f"Unknown evidence basis: {sorted(unknown_evidence)}")
    # The reporting year describes the whole fleet. The cohort year identifies when it was built.
    year = pd.to_numeric(table["year"], errors="coerce")
    cohort = pd.to_numeric(table["cohort_year"], errors="coerce")
    legacy = table["metric"].eq("legacy_unallocated")
    if year.isna().any() or cohort[~legacy].isna().any() or cohort[legacy].notna().any():
        raise DataValidationError("Only legacy_unallocated rows may have a null cohort_year.")
    dated = ~legacy
    if (cohort[dated] > year[dated]).any():
        raise DataValidationError("A cohort cannot occur after its stock or flow year.")
    additions = table["metric"].eq("addition")
    if not (cohort[additions] == year[additions]).all():
        raise DataValidationError("Addition rows must use the entry year as cohort_year.")
    retirements = table["metric"].isin({"retirement_natural", "retirement_additional"})
    if not (cohort[retirements] < year[retirements]).all():
        raise DataValidationError("Same-year additions cannot be retired.")
    shares = table["metric"].isin({"stock_share", "service_share"})
    if (table.loc[shares, "unit"] != "1").any() or (values[shares.to_numpy()] > 1 + 1e-10).any():
        raise DataValidationError("Share metrics must use unit 1 and lie between zero and one.")
    # Check that each fleet with positive stock has a complete set of stock shares.
    stock = table.loc[table["metric"].eq("stock")]
    share = table.loc[table["metric"].eq("stock_share")]
    stock_totals = stock.groupby(KEY[:5], dropna=False)["value"].sum()
    share_totals = share.groupby(KEY[:5], dropna=False)["value"].sum()
    if set(stock_totals.index) != set(share_totals.index):
        raise DataValidationError("Every positive stock group must have stock-share rows.")
    if not np.allclose(share_totals.to_numpy(float), 1, rtol=0, atol=1e-9):
        raise DataValidationError("Stock shares must sum to one for every positive stock group.")


def _numerical_check(diagnostic):
    """Check the stock balance and the targets that the selected mode must meet."""
    scale = max(float(diagnostic.get("maximum_stock_target", 0)), 1.0)
    tolerance = max(1e-10, 1e-9 * scale)
    mode = diagnostic["mode"]
    numerical_values = [abs(diagnostic["maximum_balance_residual"])]
    if mode in {"stock", "stock_flow"}:
        numerical_values.append(abs(diagnostic["maximum_absolute_stock_residual"]))
    if mode in {"inflow", "stock_flow"}:
        numerical_values.append(abs(diagnostic["maximum_absolute_inflow_residual"]))
    if mode == "joint":
        numerical_values.append(
            abs(diagnostic["annualisation"]["stock_anchor_max_absolute_residual"])
        )
        if diagnostic["annualisation"]["exact_inflow_constraints_feasible"]:
            numerical_values.append(
                abs(diagnostic["annualisation"]["actual_sum_absolute_rate_residual"])
            )
    numerical_value = max(numerical_values)
    numerical = "pass" if numerical_value <= tolerance else "fail"
    return {
        "status": numerical,
        "maximum_absolute_residual": numerical_value,
        "tolerance": tolerance,
    }


def validation_summary(diagnostics):
    """Group problems and give a few examples of each type."""
    failed, adjusted = [], []
    cases_with_issues = 0
    for diagnostic in diagnostics:
        identity = {"asset": diagnostic["asset"], "region": diagnostic["region"]}
        numerical = _numerical_check(diagnostic)
        numerical_failed = numerical["status"] == "fail"
        fit = diagnostic.get("annualisation")
        additions_adjusted = fit is not None and not fit["exact_inflow_constraints_feasible"]
        if numerical_failed or additions_adjusted:
            cases_with_issues += 1
        if numerical_failed:
            failed.append(
                {
                    **identity,
                    "residual": numerical["maximum_absolute_residual"],
                    "tolerance": numerical["tolerance"],
                }
            )
        if additions_adjusted:
            adjusted.append(identity)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "fail" if failed else "warning" if adjusted else "pass",
        "cases_checked": len(diagnostics),
        "cases_with_issues": cases_with_issues,
    }
    issues = []
    if failed:
        issues.append(
            {
                "message": "A required stock, additions or balance check failed.",
                "cases": len(failed),
                "examples": failed[:5],
            }
        )
    if adjusted:
        issues.append(
            {
                "message": "The joint fit adjusted reported additions to match the reported stock.",
                "cases": len(adjusted),
                "examples": adjusted[:5],
            }
        )
    if issues:
        summary["issues"] = issues
    return summary


def validation_contract(diagnostics: list[dict]) -> dict:
    """Separate numerical, structural and evidence assessments."""
    assets = []
    rank = {"pass": 0, "warning": 1, "fail": 2}
    overall = "pass"
    for diagnostic in diagnostics:
        mode = diagnostic["mode"]
        source_conflict = bool(
            diagnostic["negative_implied_exit_years"]
            or diagnostic["implied_exits_exceed_opening_stock_years"]
            or (
                mode == "joint"
                and not diagnostic["annualisation"]["exact_inflow_constraints_feasible"]
            )
        )
        structural = "warning" if source_conflict else "pass"
        observed_share = diagnostic.get("opening_evidence_share", 0.0)
        direct_share = diagnostic.get("opening_direct_evidence_share", observed_share)
        proxy_share = diagnostic.get("opening_proxy_evidence_share", 0.0)
        prior_share = diagnostic.get("opening_prior_share", 1.0 - observed_share)
        evidence = "pass" if direct_share >= 1 - 1e-9 else "warning"
        prior = "pass" if prior_share <= 1e-9 else "warning"
        checks = {
            "numerical_residuals": _numerical_check(diagnostic),
            "source_precision": {
                "status": "warning",
                "reason": "annual values between IAM anchors are linearly interpolated",
            },
            "structural_consistency": {"status": structural},
            "evidence_coverage": {
                "status": evidence,
                "opening_evidence_share": observed_share,
                "opening_direct_evidence_share": direct_share,
                "opening_proxy_evidence_share": proxy_share,
            },
            "prior_dependence": {
                "status": prior,
                "opening_stock_prior_share": prior_share,
            },
        }
        status = max((value["status"] for value in checks.values()), key=rank.get)
        overall = max((overall, status), key=rank.get)
        assets.append(
            {
                "asset": diagnostic["asset"],
                "region": diagnostic["region"],
                "status": status,
                "checks": checks,
            }
        )
    return {"schema_version": SCHEMA_VERSION, "status": overall, "assets": assets}


def _json(path: Path, value: dict) -> None:
    """Write a formatted JSON file with sorted keys."""
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_vintage_package(
    table,
    destination,
    *,
    source_path,
    config_path,
    config,
    validation,
    overwrite=False,
):
    """Atomically write a checksum-bound Parquet package and validation report."""
    table = table[COLUMNS].copy()
    validate_vintage_table(table)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        raise IamPreprocessorError(
            f"Vintage package already exists: {destination}. Use --overwrite to replace it."
        )
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        parquet = temporary / "vintages.parquet"
        table.to_parquet(parquet, index=False, compression="zstd")
        resources = [
            {
                "path": parquet.name,
                "format": "parquet",
                "sha256": sha256_file(parquet),
                "rows": len(table),
            }
        ]
        validation_path = temporary / "validation.json"
        _json(validation_path, validation)
        resources.append(
            {"path": validation_path.name, "format": "json", "sha256": sha256_file(validation_path)}
        )
        # This profile identifies the file format used by consumers of the package.
        manifest = {
            "profile": "iam-preprocessor-stock-vintages",
            "schema_version": SCHEMA_VERSION,
            "model": config["model"],
            "scenario": config["scenario"],
            "reference_year": config["reference_year"],
            "end_year": config["end_year"],
            "timing": {
                "stock": "end_of_year",
                "flow": "calendar_year",
                "cohort": "entry_or_commissioning_year",
                "entry": "end_of_year",
            },
            "source": {
                "path": str(Path(source_path).resolve()),
                "sha256": sha256_file(source_path),
            },
            "configuration": {
                "path": str(Path(config_path).resolve()),
                "sha256": sha256_file(config_path),
            },
            "registries": config.get("registries", {}),
            "evidence": evidence_descriptor(config.get("evidence_manifest")),
            "resources": resources,
        }
        _json(temporary / "datapackage.json", manifest)
        if destination.exists():
            backup = destination.with_name(f".{destination.name}.previous")
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(destination, backup)
            try:
                os.replace(temporary, destination)
            except Exception:
                os.replace(backup, destination)
                raise
            shutil.rmtree(backup)
        else:
            os.replace(temporary, destination)
        return destination
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
