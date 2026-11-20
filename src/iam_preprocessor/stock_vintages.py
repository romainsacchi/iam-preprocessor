"""Orchestrate stock-vintage reconstruction and write its public outputs.

Input interpretation lives in :mod:`vintage_inputs`; reconstruction of one
asset lives in :mod:`vintage_reconstruction`.  This module assembles their
results into the IAM-style compatibility table and the canonical data package.
"""

from __future__ import annotations

import json
from importlib.metadata import distribution, version
from pathlib import Path

import numpy as np
import pandas as pd

from .crypto import encrypt_file
from .exceptions import DataValidationError, IamPreprocessorError
from .filtering import filter_variables
from .io import read_frame, sha256_file, validate_frame, write_csv_atomic, year_columns
from .report import ProcessingReport
from .stock_config import load_stock_config
from .stock_package import write_vintage_package
from .vintage_inputs import (
    annual_additions,
    annualize_source_table,
    interpolate_annual,
    read_iam_series,
    read_initial_cohorts,
)
from .vintage_reconstruction import reconstruct_asset

PREFIX = "Stock Vintage|v1|"

# Compatibility names retained for existing notebooks and downstream imports.
_series = read_iam_series
interpolate = interpolate_annual
annual_inflows = annual_additions
_observations = read_initial_cohorts
_annualize_originals = annualize_source_table


def _asset_result(frame, asset, reference_year, end_year):
    """Compatibility wrapper for the former tuple-returning private helper."""
    return reconstruct_asset(frame, asset, reference_year, end_year).as_legacy_tuple()


def enrich_stock_vintages(frame, config, *, return_v2=False, include_v1=True):
    """Return an enriched table and diagnostics using a validated stock configuration.

    One model/scenario per file is required because premise discards those two
    dimensions when loading. No native IAM-vintage fidelity is claimed.
    """
    validate_frame(frame)
    identity = frame[["Model", "Scenario"]].drop_duplicates().values.tolist()
    if identity != [[config["model"], config["scenario"]]]:
        raise DataValidationError("Input must contain exactly the configured model and scenario.")
    if frame["Variable"].str.startswith("Stock Vintage|").any():
        raise DataValidationError("Input already contains stock-vintage enrichment.")
    ref, end = config["reference_year"], config["end_year"]
    rows, diagnostics, v2_rows = [], [], []
    for asset in config["assets"]:
        try:
            reconstruction = reconstruct_asset(frame, asset, ref, end)
        except DataValidationError as exc:
            raise DataValidationError(f"{asset['id']}/{asset['region']}: {exc}") from exc
        result = reconstruction.cohorts
        shares = reconstruction.stock_shares
        service_shares = reconstruction.service_shares
        targets = reconstruction.stock_targets
        flows = reconstruction.reported_additions
        implied = reconstruction.implied_exit
        service_target = reconstruction.service_target
        joint_diagnostics = reconstruction.annualisation
        basis_by_cohort = reconstruction.evidence_basis
        prefix = PREFIX + asset["id"] + "|"
        stock_unit = asset["stock"]["unit"]

        def add_v2(
            year,
            cohort,
            metric,
            value,
            unit,
            *,
            region=asset["region"],
            asset_id=asset["id"],
            cohort_basis=None,
        ):
            if not np.isfinite(value) or value <= 0:
                return
            v2_rows.append(
                {
                    "model": config["model"],
                    "scenario": config["scenario"],
                    "region": region,
                    "asset": asset_id,
                    "year": int(year),
                    "cohort_year": int(cohort),
                    "metric": metric,
                    "value": float(value),
                    "unit": unit,
                    "evidence_basis": cohort_basis if cohort_basis is not None else "iam_addition",
                }
            )

        def add(suffix, unit, values, *, region=asset["region"], prefix=prefix, years=result.years):
            if not include_v1:
                return
            rows.append(
                {
                    "Model": config["model"],
                    "Scenario": config["scenario"],
                    "Region": region,
                    "Variable": prefix + suffix,
                    "Unit": unit,
                    **{str(y): float(v) for y, v in zip(years, values, strict=True)},
                }
            )

        for j, cohort in enumerate(result.cohorts):
            # Include every cohort, including zero/future cohorts, to avoid implicit missing=zero.
            add(f"Stock|Vintage|{cohort}", stock_unit, result.stock[:, j])
            add(f"Stock Share|Vintage|{cohort}", "1", shares[:, j])
            add(f"Service Share|Vintage|{cohort}", "1", service_shares[:, j])
            if service_target is not None:
                add(
                    f"Service|Vintage|{cohort}",
                    asset["service"]["unit"],
                    service_shares[:, j] * service_target,
                )
            for i, year in enumerate(result.years):
                basis = basis_by_cohort[j]
                add_v2(year, cohort, "stock", result.stock[i, j], stock_unit, cohort_basis=basis)
                add_v2(year, cohort, "stock_share", shares[i, j], "1", cohort_basis=basis)
                add_v2(
                    year,
                    cohort,
                    "service_share",
                    service_shares[i, j],
                    "1",
                    cohort_basis=basis,
                )
                if service_target is not None:
                    add_v2(
                        year,
                        cohort,
                        "service",
                        service_shares[i, j] * service_target[i],
                        asset["service"]["unit"],
                        cohort_basis=basis,
                    )
                if i and result.natural_exit_by_cohort is not None:
                    add_v2(
                        year,
                        cohort,
                        "retirement_natural",
                        result.natural_exit_by_cohort[i, j],
                        stock_unit + "/yr",
                        cohort_basis=basis,
                    )
                if i and result.additional_exit_by_cohort is not None:
                    add_v2(
                        year,
                        cohort,
                        "retirement_additional",
                        result.additional_exit_by_cohort[i, j],
                        stock_unit + "/yr",
                        cohort_basis=basis,
                    )
        for i, year in enumerate(result.years[1:], start=1):
            add_v2(year, year, "addition", result.inflow[i], stock_unit + "/yr")
        totals = result.stock.sum(axis=1)
        add("Coverage", "1", np.ones(len(result.years)))
        add("Stock", stock_unit, totals)
        for name, values in (
            ("Inflow", result.inflow),
            ("Natural Exit", result.natural_exit),
            ("Additional Exit", result.additional_exit),
            ("Balance Residual", result.balance),
            ("Inflow Residual", result.inflow - flows),
            ("Implied Exit From IAM Totals", implied),
        ):
            add(name, stock_unit + "/yr", values)
        add("Stock Residual", stock_unit, totals - targets)
        if service_target is not None:
            add("Service", asset["service"]["unit"], service_target)
        diagnostic = {
            "asset": asset["id"],
            "region": asset["region"],
            "mode": asset["mode"],
            "maximum_balance_residual": float(np.max(np.abs(result.balance[1:]))),
            "maximum_absolute_stock_residual": float(np.max(np.abs(totals - targets))),
            "maximum_absolute_inflow_residual": float(
                np.max(np.abs(result.inflow[1:] - flows[1:]))
            ),
            "maximum_stock_target": float(np.max(targets)),
            "opening_prior_share": float(
                result.stock[0, basis_by_cohort == "prior"].sum() / result.stock[0].sum()
                if result.stock[0].sum()
                else 0
            ),
            "opening_evidence_share": float(
                result.stock[0, basis_by_cohort == "observed"].sum() / result.stock[0].sum()
                if result.stock[0].sum()
                else 0
            ),
            "total_additional_exits": float(np.sum(result.additional_exit[1:])),
            "negative_implied_exit_years": result.years[
                np.isfinite(implied) & (implied < -1e-12)
            ].tolist(),
            "implied_exits_exceed_opening_stock_years": result.years[1:][
                implied[1:] > targets[:-1] + 1e-12
            ].tolist(),
            "zero_stock_years": result.years[totals == 0].tolist(),
            "zero_service_years": result.years[service_shares.sum(axis=1) == 0].tolist(),
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
        diagnostics.append(diagnostic)
    if include_v1:
        annual = _annualize_originals(frame, range(ref, end + 1))
        enriched = pd.concat([annual, pd.DataFrame(rows)], ignore_index=True)
        enriched = enriched[
            [c for c in enriched.columns if c not in year_columns(enriched)]
            + year_columns(enriched)
        ]
    else:
        enriched = frame
    validate_frame(enriched)
    if return_v2:
        return enriched, diagnostics, pd.DataFrame(v2_rows)
    return enriched, diagnostics


def prepare_stock_vintages(
    source,
    output_dir,
    config_path,
    *,
    filter_output=False,
    encrypt_to=None,
    key_file=None,
    package_only=False,
    overwrite=False,
):
    """Write enriched CSV and hashed report, optionally filtering and encrypting.

    Run on a single unencrypted IAM file. Subsequent encryption uses the existing
    premise-compatible interface. Generated scenarios remain local/private.
    """
    source, output_dir = Path(source), Path(output_dir)
    config = load_stock_config(config_path)
    destination = output_dir / f"{source.stem}_stock_vintages.csv"
    package_path = output_dir / f"{source.stem}_stock_vintages_v2"
    report_path = output_dir / f"{source.stem}_stock_vintages_report.json"
    if package_only and (filter_output or encrypt_to is not None):
        raise IamPreprocessorError(
            "Package-only output cannot be filtered or encrypted as a v1 IAM CSV."
        )
    paths = [report_path, package_path]
    if not package_only:
        paths.append(destination)
    if encrypt_to is not None:
        paths.append(Path(encrypt_to) / destination.name)
    if len({p.resolve() for p in paths}) != len(paths):
        raise IamPreprocessorError("Plain and encrypted destinations must differ.")
    if not overwrite and any(p.exists() for p in paths):
        raise IamPreprocessorError("Output already exists; use --overwrite to replace it.")
    frame = read_frame(source)
    enriched, diagnostics, v2 = enrich_stock_vintages(
        frame, config, return_v2=True, include_v1=not package_only
    )
    flodym = distribution("flodym")
    flodym_origin = json.loads(flodym.read_text("direct_url.json") or "{}")
    report = ProcessingReport(
        model=config["model"],
        input_path=str(source.resolve()),
        input_sha256=sha256_file(source),
        input_rows=len(frame),
        derived_variables=sorted(set(enriched["Variable"]) - set(frame["Variable"])),
        assumptions={
            "stock_vintage_schema_version": 1,
            "canonical_stock_vintage_schema_version": 2,
            "v1_compatibility_output": not package_only,
            "origin": "reconstructed_not_native",
            "scenario": config["scenario"],
            "reference_year": config["reference_year"],
            "end_year": config["end_year"],
            "config_sha256": sha256_file(config_path),
            "flodym_version": flodym.version,
            "flodym_commit": flodym_origin.get("vcs_info", {}).get("commit_id"),
            "software_versions": {
                name: version(name)
                for name in ("iam-preprocessor", "flodym", "numpy", "pandas", "scipy", "osqp")
            },
            "implementation_sha256": {
                name: sha256_file(Path(__file__).with_name(name))
                for name in (
                    "stock_vintages.py",
                    "vintage_inputs.py",
                    "vintage_reconstruction.py",
                    "flodym_stock.py",
                    "stock_model.py",
                    "stock_config.py",
                    "stock_usage.py",
                    "stock_annualisation.py",
                    "io.py",
                    "filtering.py",
                )
            },
            "assets": diagnostics,
            "stock_timing": "end_of_year",
            "entry_timing": "end_of_year",
            "service_timing": "end_year_serving_stock_proxy_with_explicit_new_cohort_exposure",
            "original_added_columns": "linear_between_existing_anchors_no_extrapolation",
            "allocation_basis": "common_amortisation",
            "exchange_amount_changed": False,
            "service_target_effect": "total_only_does_not_identify_relative_cohort_use",
        },
    )
    for d in diagnostics:
        if d["negative_implied_exit_years"]:
            report.warnings.append(
                f"{d['asset']}/{d['region']}: stock and annualised inflow imply "
                f"negative exits in {d['negative_implied_exit_years']}; "
                "this diagnostic uses independent linear/flat annualisation. "
                "For joint mode, see the separate constraint reconciliation."
            )
        if "annualisation" in d and not d["annualisation"]["exact_inflow_constraints_feasible"]:
            report.warnings.append(
                f"{d['asset']}/{d['region']}: reported inflows conflict with stock anchors "
                "under the configured survival/exit assumptions. Stock anchors retained; "
                "a configured rate-residual penalty balances inflow agreement and smoothness. "
                "Every source-constraint discrepancy is explicitly reported."
            )
        if d["total_additional_exits"] > 0:
            report.warnings.append(
                f"{d['asset']}/{d['region']}: additional exits follow the configured "
                f"{d['configuration']['exit_policy']} policy. Physical disposal is unobserved."
            )
    if filter_output:
        enriched = filter_variables(enriched)
    write_vintage_package(
        v2,
        package_path,
        source_path=source,
        config_path=config_path,
        config=config,
        diagnostics=diagnostics,
        overwrite=overwrite,
        csv_copy=not package_only,
    )
    report.assumptions["vintage_package_path"] = str(package_path.resolve())
    report.assumptions["vintage_package_manifest_sha256"] = sha256_file(
        package_path / "datapackage.json"
    )
    if package_only:
        canonical = package_path / "vintages.parquet"
        report.output_path = str(canonical.resolve())
        report.output_sha256 = sha256_file(canonical)
        report.output_rows = len(v2)
    else:
        write_csv_atomic(enriched, destination, overwrite=overwrite)
        report.output_path = str(destination.resolve())
        report.output_sha256 = sha256_file(destination)
        report.output_rows = len(enriched)
        if encrypt_to is not None:
            encrypted = Path(encrypt_to) / destination.name
            encrypt_file(destination, encrypted, key_file=key_file, overwrite=overwrite)
            report.encrypted_output_path = str(encrypted.resolve())
            report.encrypted_output_sha256 = sha256_file(encrypted)
    report.write(report_path, overwrite=overwrite)
    return report
