"""Orchestrate stock-vintage reconstruction and write its public outputs.

Input interpretation lives in :mod:`vintage_inputs`; reconstruction of one
asset lives in :mod:`vintage_reconstruction`.  This module saves their
results in a separate data package.
"""

from __future__ import annotations

import json
from importlib.metadata import distribution, version
from pathlib import Path

import numpy as np
import pandas as pd

from .exceptions import DataValidationError, IamPreprocessorError
from .io import read_frame, sha256_file, validate_frame
from .report import ProcessingReport
from .stock_config import load_stock_config
from .stock_package import (
    COLUMNS,
    SCHEMA_VERSION,
    validation_contract,
    validation_summary,
    write_vintage_package,
)
from .variable_maps import variable_map
from .vintage_reconstruction import reconstruct_asset

VINTAGE_OUTPUT = variable_map("vintage_output_variables.yaml")
PREFIX = VINTAGE_OUTPUT["prefix"]


def calculate_stock_vintages(frame, config):
    """Return a table of annual vintage results and diagnostics for each asset."""
    validate_frame(frame)
    identity = frame[["Model", "Scenario"]].drop_duplicates().values.tolist()
    if identity != [[config["model"], config["scenario"]]]:
        raise DataValidationError("Input must contain exactly the configured model and scenario.")
    if frame["Variable"].str.startswith(VINTAGE_OUTPUT["namespace"]).any():
        raise DataValidationError("Input already contains stock-vintage enrichment.")

    ref, end = config["reference_year"], config["end_year"]
    rows, diagnostics = [], []
    for asset in config["assets"]:
        try:
            reconstruction = reconstruct_asset(frame, asset, ref, end)
        except DataValidationError as exc:
            raise DataValidationError(f"{asset['id']}/{asset['region']}: {exc}") from exc
        _append_asset_rows(config, asset, reconstruction, rows)
        diagnostics.append(_asset_diagnostics(asset, reconstruction))
    return pd.DataFrame(rows, columns=COLUMNS), diagnostics


def _append_asset_rows(config, asset, reconstruction, rows):
    """Add the results for one asset and region to the vintage table."""
    result = reconstruction.cohorts
    shares = reconstruction.stock_shares
    service_shares = reconstruction.service_shares
    service_target = reconstruction.service_target
    basis_by_cohort = reconstruction.evidence_basis
    stock_unit = asset["stock"]["unit"]

    def add(
        year,
        cohort,
        metric,
        value,
        unit,
        cohort_basis="iam_addition",
    ):
        """Store only positive quantities in the long-format package."""
        if not np.isfinite(value) or value <= 0:
            return
        rows.append(
            {
                "model": config["model"],
                "scenario": config["scenario"],
                "region": asset["region"],
                "asset": asset["id"],
                "year": int(year),
                "cohort_year": int(cohort),
                "metric": metric,
                "value": float(value),
                "unit": unit,
                "evidence_basis": cohort_basis,
            }
        )

    for j, cohort in enumerate(result.cohorts):
        metrics = [
            ("stock", stock_unit, result.stock[:, j]),
            ("stock_share", "1", shares[:, j]),
            ("service_share", "1", service_shares[:, j]),
        ]
        if service_target is not None:
            metrics.append(
                ("service", asset["service"]["unit"], service_shares[:, j] * service_target)
            )

        for i, year in enumerate(result.years):
            basis = basis_by_cohort[j]
            for metric, unit, values in metrics:
                add(year, cohort, metric, values[i], unit, cohort_basis=basis)
            # Retirements describe changes after the opening year.
            if i and result.natural_exit_by_cohort is not None:
                add(
                    year,
                    cohort,
                    "retirement_natural",
                    result.natural_exit_by_cohort[i, j],
                    stock_unit + "/yr",
                    cohort_basis=basis,
                )
            if i and result.additional_exit_by_cohort is not None:
                add(
                    year,
                    cohort,
                    "retirement_additional",
                    result.additional_exit_by_cohort[i, j],
                    stock_unit + "/yr",
                    cohort_basis=basis,
                )
    # Only one build year receives additions in any given calendar year.
    for i, year in enumerate(result.years[1:], start=1):
        add(year, year, "addition", result.inflow[i], stock_unit + "/yr")


def _asset_diagnostics(asset, reconstruction):
    """Summarize fit errors, questionable IAM inputs and opening stock evidence."""
    result = reconstruction.cohorts
    targets = reconstruction.stock_targets
    flows = reconstruction.reported_additions
    implied = reconstruction.implied_exit
    basis = reconstruction.evidence_basis
    totals = result.stock.sum(axis=1)
    joint_diagnostics = reconstruction.annualisation

    def opening_share(cohorts):
        """Return the share of opening stock supplied by the selected cohorts."""
        return float(result.stock[0, cohorts].sum() / totals[0]) if totals[0] else 0.0

    diagnostic = {
        "asset": asset["id"],
        "region": asset["region"],
        "mode": asset["mode"],
        "maximum_balance_residual": float(np.max(np.abs(result.balance[1:]))),
        "maximum_absolute_stock_residual": float(np.max(np.abs(totals - targets))),
        "maximum_absolute_inflow_residual": float(np.max(np.abs(result.inflow[1:] - flows[1:]))),
        "maximum_stock_target": float(np.max(targets)),
        "opening_prior_share": opening_share(basis == "prior"),
        "opening_evidence_share": opening_share(np.isin(basis, ["observed", "observed_proxy"])),
        "opening_direct_evidence_share": opening_share(basis == "observed"),
        "opening_proxy_evidence_share": opening_share(basis == "observed_proxy"),
        "total_additional_exits": float(np.sum(result.additional_exit[1:])),
        "negative_implied_exit_years": result.years[
            np.isfinite(implied) & (implied < -1e-12)
        ].tolist(),
        "implied_exits_exceed_opening_stock_years": result.years[1:][
            implied[1:] > targets[:-1] + 1e-12
        ].tolist(),
        "zero_stock_years": result.years[totals == 0].tolist(),
        "zero_service_years": result.years[reconstruction.service_shares.sum(axis=1) == 0].tolist(),
        "configuration": asset,
    }
    if asset["initial"]["kind"] == "observed_shares":
        diagnostic["observation_sha256"] = sha256_file(asset["initial"]["file"])
    if asset["service_weighting"]["kind"] == "age_profile":
        diagnostic["age_profile_sha256"] = sha256_file(
            asset["service_weighting"]["age_profile_file"]
        )
    if joint_diagnostics is not None:
        diagnostic["annualisation"] = joint_diagnostics
        diagnostic["stock_residual_basis"] = (
            "deviation from linear interpolation; source-anchor residuals reported separately"
        )
    return diagnostic


def prepare_stock_vintages(
    source, output_dir, config_path, *, overwrite=False, detailed_report=False
):
    """Write a separate stock-vintage package and report for one scenario file."""
    source, output_dir = Path(source), Path(output_dir)
    config = load_stock_config(config_path)
    package_path = output_dir / f"{source.stem}_stock_vintages_v2"
    report_path = output_dir / f"{source.stem}_stock_vintages_report.json"
    package_root = package_path.resolve()
    if any(Path(path).resolve().is_relative_to(package_root) for path in (source, config_path)):
        raise IamPreprocessorError(
            "The vintage package cannot contain the input scenario or settings."
        )
    if not overwrite and any(path.exists() for path in (report_path, package_path)):
        raise IamPreprocessorError("Output already exists; use --overwrite to replace it.")
    frame = read_frame(source)
    vintages, diagnostics = calculate_stock_vintages(frame, config)
    validation = validation_summary(diagnostics)
    if detailed_report:
        validation["assets"] = validation_contract(diagnostics)["assets"]
    # Record the library revision and input hashes so the run can be reproduced.
    flodym = distribution("flodym")
    flodym_origin = json.loads(flodym.read_text("direct_url.json") or "{}")
    report = ProcessingReport(
        model=config["model"],
        input_path=str(source.resolve()),
        input_sha256=sha256_file(source),
        input_rows=len(frame),
        warnings=[
            f"{issue['message']} Affected cases ({issue['cases']} of {len(diagnostics)})."
            for issue in validation.get("issues", [])
        ],
        assumptions={
            "stock_vintage_schema_version": SCHEMA_VERSION,
            "origin": "reconstructed_not_native",
            "scenario": config["scenario"],
            "reference_year": config["reference_year"],
            "end_year": config["end_year"],
            "config_path": str(Path(config_path).resolve()),
            "config_sha256": sha256_file(config_path),
            "validation_status": validation["status"],
            "asset_region_cases": validation["cases_checked"],
            "cases_with_issues": validation["cases_with_issues"],
            "flodym_version": flodym.version,
            "flodym_commit": flodym_origin.get("vcs_info", {}).get("commit_id"),
            "software_versions": {
                name: version(name)
                for name in ("iam-prep-for-premise", "flodym", "numpy", "pandas", "scipy", "osqp")
            },
            "implementation_sha256": {
                name: sha256_file(Path(__file__).with_name(name))
                for name in (
                    "stock_vintages.py",
                    "vintage_inputs.py",
                    "vintage_reconstruction.py",
                    "flodym_stock.py",
                    "stock_model.py",
                    "lifetime.py",
                    "stock_config.py",
                    "stock_usage.py",
                    "stock_annualisation.py",
                    "io.py",
                    "variable_maps.py",
                )
            },
            "variable_mapping_sha256": {
                name: sha256_file(Path(__file__).with_name("data") / name)
                for name in ("vintage_output_variables.yaml",)
            },
            "stock_timing": "end_of_year",
            "entry_timing": "end_of_year",
            "service_timing": "end_year_serving_stock_proxy_with_explicit_new_cohort_exposure",
            "allocation_basis": "common_amortisation",
            "exchange_amount_changed": False,
            "service_target_effect": "total_only_does_not_identify_relative_cohort_use",
        },
    )
    if detailed_report:
        report.assumptions["assets"] = diagnostics
    write_vintage_package(
        vintages,
        package_path,
        source_path=source,
        config_path=config_path,
        config=config,
        validation=validation,
        overwrite=overwrite,
    )
    report.assumptions["vintage_package_path"] = str(package_path.resolve())
    report.assumptions["vintage_package_manifest_sha256"] = sha256_file(
        package_path / "datapackage.json"
    )
    parquet = package_path / "vintages.parquet"
    report.output_path = str(parquet.resolve())
    report.output_sha256 = sha256_file(parquet)
    report.output_rows = len(vintages)
    report.write(report_path, overwrite=overwrite)
    return report
