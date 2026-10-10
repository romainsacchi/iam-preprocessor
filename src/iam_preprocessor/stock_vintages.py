"""Enrich IAM tables with explicitly reconstructed stock and service vintages."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from .crypto import encrypt_file
from .exceptions import DataValidationError, IamPreprocessorError
from .filtering import filter_variables
from .io import read_frame, sha256_file, validate_frame, write_csv_atomic, year_columns
from .report import ProcessingReport
from .stock_config import load_stock_config
from .stock_model import reconstruct, survival_matrix

PREFIX = "Stock Vintage|v1|"


def _series(frame, region, specification):
    selected = frame.loc[
        frame["Region"].eq(region) & frame["Variable"].eq(specification["variable"])
    ]
    if len(selected) != 1 or selected.iloc[0]["Unit"] != specification["unit"]:
        raise DataValidationError(
            f"Expected a unique exact variable/unit: {region}/{specification}"
        )
    labels = year_columns(frame)
    try:
        values = pd.to_numeric(selected.iloc[0][labels], errors="raise").to_numpy(float)
    except (ValueError, TypeError) as exc:
        raise DataValidationError(f"Non-numeric IAM series: {specification}") from exc
    if not np.isfinite(values).all() or (values < 0).any():
        raise DataValidationError(f"Missing, negative or nonfinite IAM series: {specification}")
    return dict(zip(map(int, labels), values, strict=True))


def interpolate(series, years):
    """Linear annual level/sample interpolation; never extrapolate."""
    anchors = sorted(series)
    if min(years) < anchors[0] or max(years) > anchors[-1]:
        raise DataValidationError("Requested years require extrapolation beyond IAM anchors.")
    return np.interp(years, anchors, [series[y] for y in anchors])


def annual_inflows(series, years, timing):
    """Expand reported average rates using explicit, non-overlapping windows."""
    if timing["kind"] == "sampled_annual":
        return interpolate(series, years)
    rates = {}
    anchors_seen = set()
    for period in timing["periods"]:
        anchor = period["anchor"]
        if anchor not in series or anchor in anchors_seen:
            raise DataValidationError("Reporting periods need unique existing IAM anchors.")
        anchors_seen.add(anchor)
        for year in range(period["start"], period["end"] + 1):
            if year in rates:
                raise DataValidationError(f"Overlapping reporting periods in {year}.")
            rates[year] = series[anchor]
    missing = set(years) - rates.keys()
    if missing:
        raise DataValidationError(f"Reporting windows do not cover years: {sorted(missing)}")
    return np.array([rates[y] for y in years], dtype=float)


def _observations(initial, reference_year):
    if initial["kind"] == "equilibrium":
        return None, reference_year - initial["maximum_age"]
    try:
        observed = pd.read_csv(initial["file"])
        if set(observed.columns) - {"cohort", "amount", "service_factor"}:
            raise ValueError("Unexpected observation columns")
        values = observed[["cohort", "amount"]].to_numpy(float)
        if not np.isfinite(values).all() or (values[:, 1] < 0).any():
            raise ValueError("Invalid observed quantities")
        cohorts = values[:, 0]
        if (
            len(cohorts) == 0
            or len(set(cohorts)) != len(cohorts)
            or (cohorts != cohorts.astype(int)).any()
            or (cohorts > reference_year).any()
            or (cohorts < reference_year - 150).any()
            or values[:, 1].sum() <= 0
        ):
            raise ValueError("Invalid cohort years or zero total")
        observed["cohort"] = cohorts.astype(int)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DataValidationError(f"Invalid cohort observations: {initial['file']}: {exc}") from exc
    return observed, int(cohorts.min())


def _asset_result(frame, asset, reference_year, end_year):
    requested_end = end_year
    stock_series = _series(frame, asset["region"], asset["stock"])
    flow_series = _series(frame, asset["region"], asset["inflow"])
    if asset["mode"] == "joint":
        from .stock_annualisation import joint_horizon

        end_year = joint_horizon(stock_series, reference_year, end_year, asset["inflow_timing"])
    observed, first = _observations(asset["initial"], reference_year)
    years = np.arange(first, end_year + 1)
    service_years = np.arange(reference_year, end_year + 1)
    ref = reference_year - first
    stock_targets = interpolate(stock_series, service_years)
    if stock_targets[0] <= 0:
        raise DataValidationError("Initial stock must be positive to infer its composition.")
    # The reference stock is an initial condition, not the reference year's inflow.
    flows = np.r_[
        0.0,
        annual_inflows(
            flow_series,
            service_years[1:],
            asset["inflow_timing"],
        ),
    ]
    lifetime = asset["lifetime"]
    means = np.full(len(years), float(lifetime["initial_mean"]))
    means[ref + 1 :] = (
        interpolate(_series(frame, asset["region"], lifetime["source"]), years[ref + 1 :])
        if "source" in lifetime
        else lifetime["mean"]
    )
    sf = survival_matrix(
        years.tolist(), means, distribution=lifetime["distribution"], shape=lifetime.get("shape")
    )
    initial = np.zeros(len(years))
    factors = np.ones(len(years))
    weighting = asset["service_weighting"]
    if observed is None:
        initial[: ref + 1] = sf[ref, : ref + 1]
    else:
        positions = observed["cohort"].to_numpy(int) - first
        initial[positions] = observed["amount"].to_numpy(float)
        if weighting["kind"] == "observed_factors":
            if "service_factor" not in observed:
                raise DataValidationError("Observation CSV is missing service_factor.")
            factors[:] = weighting["future_factor"]
            try:
                factors[positions] = observed["service_factor"].to_numpy(float)
            except (ValueError, TypeError) as exc:
                raise DataValidationError("Non-numeric observed service factors.") from exc
    if not np.isfinite(factors).all() or (factors < 0).any():
        raise DataValidationError("Service factors must be finite and nonnegative.")
    initial *= stock_targets[0] / initial.sum()
    result = reconstruct(
        years=years,
        reference_year=reference_year,
        initial=initial,
        survival=sf,
        targets=flows if asset["mode"] == "inflow" else stock_targets,
        mode="inflow" if asset["mode"] == "inflow" else "stock",
        exit_policy="proportional" if asset["mode"] == "joint" else asset["exit_policy"],
    )
    joint_diagnostics = None
    if asset["mode"] == "joint":
        from .stock_annualisation import reconstruct_joint

        result, joint_diagnostics = reconstruct_joint(
            baseline=result,
            survival=sf,
            stock_series=stock_series,
            flow_series=flow_series,
            timing=asset["inflow_timing"],
            reference_inflows=flows,
            exit_policy=asset["exit_policy"],
            options={
                k: asset["annualisation"][k]
                for k in ("inflow_constraints", "reference_weight", "inflow_weight")
            },
        )
    ageing = np.maximum(0, service_years[:, None] - np.maximum(reference_year, years)[None, :])
    service = result.stock * factors[None, :] * np.exp(-weighting["annual_age_decay"] * ageing)
    for i, year in enumerate(service_years[1:], start=1):
        service[i, year - first] *= weighting.get("new_cohort_exposure", 1.0)
    total = result.stock.sum(axis=1)
    stock_shares = np.divide(
        result.stock, total[:, None], out=np.zeros_like(result.stock), where=total[:, None] > 0
    )
    service_sum = service.sum(axis=1)
    service_shares = np.divide(
        service, service_sum[:, None], out=np.zeros_like(service), where=service_sum[:, None] > 0
    )
    service_target = None
    if "service" in asset:
        service_target = interpolate(
            _series(frame, asset["region"], asset["service"]), service_years
        )
        if ((service_target > 0) & (service_sum <= 0)).any():
            raise DataValidationError(
                "Positive IAM service cannot be supplied by zero serving stock."
            )
        service_shares[service_target == 0] = 0
        if "maximum_service_per_stock" in weighting:
            service_per_stock = np.divide(
                service_shares * service_target[:, None],
                result.stock,
                out=np.zeros_like(service),
                where=result.stock > 0,
            )
            invalid = (service_per_stock > weighting["maximum_service_per_stock"] * (1 + 1e-10)) & (
                service_years[:, None] <= requested_end
            )
            if invalid.any():
                t, c = np.argwhere(invalid)[0]
                raise DataValidationError(
                    "Modelled cohort service exceeds the declared per-stock bound: "
                    f"year={service_years[t]}, cohort={years[c]}, "
                    f"value={service_per_stock[t, c]:.8g}, "
                    f"bound={weighting['maximum_service_per_stock']:.8g}."
                )
    implied_exit = np.r_[np.nan, stock_targets[:-1] + flows[1:] - stock_targets[1:]]
    if end_year != requested_end:
        # Full reporting windows are fitted before trimming public coverage. Do not
        # silently interpret a partial window as a smaller observed period total.
        count, cohort_count = requested_end - reference_year + 1, requested_end - first + 1
        result.years = result.years[:count]
        result.cohorts = result.cohorts[:cohort_count]
        result.stock = result.stock[:count, :cohort_count]
        for name in ("inflow", "natural_exit", "additional_exit", "balance"):
            setattr(result, name, getattr(result, name)[:count])
        stock_shares, service_shares = (
            array[:count, :cohort_count] for array in (stock_shares, service_shares)
        )
        stock_targets, flows, implied_exit = (
            array[:count] for array in (stock_targets, flows, implied_exit)
        )
        if service_target is not None:
            service_target = service_target[:count]
    return (
        result,
        stock_shares,
        service_shares,
        stock_targets,
        flows,
        implied_exit,
        service_target,
        joint_diagnostics,
    )


def _annualize_originals(frame, added_years):
    """Fill only new columns so annual enrichment does not create holes in IAM data."""
    anchors = list(map(int, year_columns(frame)))
    additions = {}
    for year in added_years:
        if str(year) in frame.columns:
            continue
        lo, hi = max(y for y in anchors if y < year), min(y for y in anchors if y > year)
        try:
            lower = pd.to_numeric(frame[str(lo)], errors="raise")
            upper = pd.to_numeric(frame[str(hi)], errors="raise")
        except (TypeError, ValueError) as exc:
            raise DataValidationError(
                "Cannot interpolate non-numeric original IAM variables."
            ) from exc
        additions[str(year)] = lower + (upper - lower) * (year - lo) / (hi - lo)
    return pd.concat([frame, pd.DataFrame(additions, index=frame.index)], axis=1)


def enrich_stock_vintages(frame, config):
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
    rows, diagnostics = [], []
    for asset in config["assets"]:
        try:
            (
                result,
                shares,
                service_shares,
                targets,
                flows,
                implied,
                service_target,
                joint_diagnostics,
            ) = _asset_result(frame, asset, ref, end)
        except DataValidationError as exc:
            raise DataValidationError(f"{asset['id']}/{asset['region']}: {exc}") from exc
        prefix = PREFIX + asset["id"] + "|"
        stock_unit = asset["stock"]["unit"]

        def add(suffix, unit, values, *, region=asset["region"], prefix=prefix, years=result.years):
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
        if joint_diagnostics is not None:
            diagnostic["annualisation"] = joint_diagnostics
            diagnostic["stock_residual_basis"] = (
                "deviation from linear interpolation; source-anchor residuals reported separately"
            )
        diagnostics.append(diagnostic)
    annual = _annualize_originals(frame, range(ref, end + 1))
    enriched = pd.concat([annual, pd.DataFrame(rows)], ignore_index=True)
    enriched = enriched[
        [c for c in enriched.columns if c not in year_columns(enriched)] + year_columns(enriched)
    ]
    validate_frame(enriched)
    return enriched, diagnostics


def prepare_stock_vintages(
    source,
    output_dir,
    config_path,
    *,
    filter_output=False,
    encrypt_to=None,
    key_file=None,
    overwrite=False,
):
    """Write enriched CSV and hashed report, optionally filtering and encrypting.

    Run on a single unencrypted IAM file. Subsequent encryption uses the existing
    premise-compatible interface. Generated scenarios remain local/private.
    """
    source, output_dir = Path(source), Path(output_dir)
    config = load_stock_config(config_path)
    destination = output_dir / f"{source.stem}_stock_vintages.csv"
    report_path = output_dir / f"{source.stem}_stock_vintages_report.json"
    paths = [destination, report_path]
    if encrypt_to is not None:
        paths.append(Path(encrypt_to) / destination.name)
    if len({p.resolve() for p in paths}) != len(paths):
        raise IamPreprocessorError("Plain and encrypted destinations must differ.")
    if not overwrite and any(p.exists() for p in paths):
        raise IamPreprocessorError("Output already exists; use --overwrite to replace it.")
    frame = read_frame(source)
    enriched, diagnostics = enrich_stock_vintages(frame, config)
    report = ProcessingReport(
        model=config["model"],
        input_path=str(source.resolve()),
        input_sha256=sha256_file(source),
        input_rows=len(frame),
        derived_variables=sorted(set(enriched["Variable"]) - set(frame["Variable"])),
        assumptions={
            "stock_vintage_schema_version": 1,
            "origin": "reconstructed_not_native",
            "scenario": config["scenario"],
            "reference_year": config["reference_year"],
            "end_year": config["end_year"],
            "config_sha256": sha256_file(config_path),
            "flodym_version": version("flodym"),
            "software_versions": {
                name: version(name)
                for name in ("iam-preprocessor", "flodym", "numpy", "pandas", "scipy")
            },
            "implementation_sha256": {
                name: sha256_file(Path(__file__).with_name(name))
                for name in (
                    "stock_vintages.py",
                    "stock_model.py",
                    "stock_config.py",
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
                f"{d['asset']}/{d['region']}: proportional additional exits "
                "were assumed; these are not observed physical disposal."
            )
    if filter_output:
        enriched = filter_variables(enriched)
    write_csv_atomic(enriched, destination, overwrite=overwrite)
    report.output_path, report.output_sha256 = str(destination.resolve()), sha256_file(destination)
    report.output_rows = len(enriched)
    if encrypt_to is not None:
        encrypted = Path(encrypt_to) / destination.name
        encrypt_file(destination, encrypted, key_file=key_file, overwrite=overwrite)
        report.encrypted_output_path = str(encrypted.resolve())
        report.encrypted_output_sha256 = sha256_file(encrypted)
    report.write(report_path, overwrite=overwrite)
    return report
