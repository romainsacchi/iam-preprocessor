"""Independently validate serialized stock enrichment against its source/report."""

import argparse
import json
from math import gamma
from pathlib import Path

import numpy as np
import pandas as pd

from iam_preprocessor.io import read_frame, sha256_file, year_columns
from iam_preprocessor.lifetime import canonical_distribution
from iam_preprocessor.stock_vintages import PREFIX
from iam_preprocessor.variable_maps import vintage_suffix


def validate_long_parquet(report, report_path, original):
    """Validate the sparse v2 cohort table without relying on producer internals."""

    output = pd.read_parquet(report["output_path"])
    required = {
        "model",
        "scenario",
        "region",
        "asset",
        "year",
        "cohort_year",
        "metric",
        "value",
        "unit",
        "evidence_basis",
    }
    if set(output.columns) != required:
        raise ValueError(
            "Unexpected v2 columns: "
            f"missing={sorted(required - set(output.columns))}, "
            f"extra={sorted(set(output.columns) - required)}"
        )
    keys = ["region", "asset", "year", "cohort_year", "metric"]
    if output.duplicated(keys).any():
        raise ValueError("Duplicate v2 cohort records")
    if len(output) != report["output_rows"]:
        raise ValueError("Serialized v2 row count differs from the run report")
    if not np.isfinite(output["value"]).all() or (output["value"] < -1e-12).any():
        raise ValueError("Invalid v2 values")
    if (output["cohort_year"] > output["year"]).any():
        raise ValueError("Future cohorts occur in v2 output")

    metadata = report["assumptions"]
    reference_year = metadata["reference_year"]
    years = np.arange(reference_year, metadata["end_year"] + 1)
    source_columns = year_columns(original)
    source_years = set(map(int, source_columns))
    checks = []
    maximum_balance_residual = 0.0
    maximum_survival_residual = 0.0
    for asset in metadata["assets"]:
        config = asset["configuration"]
        subset = output.loc[
            output["region"].eq(asset["region"]) & output["asset"].eq(asset["asset"])
        ]
        if subset.empty:
            raise ValueError(f"Missing v2 asset case: {asset['asset']}/{asset['region']}")
        if config["initial"]["kind"] == "observed_shares":
            if sha256_file(config["initial"]["file"]) != asset["observation_sha256"]:
                raise ValueError("Initial observation hash mismatch")
        stock_rows = subset.loc[subset["metric"].eq("stock")]
        cohorts = np.arange(stock_rows["cohort_year"].min(), years[-1] + 1)
        stocks = (
            stock_rows.pivot(index="year", columns="cohort_year", values="value")
            .reindex(index=years, columns=cohorts, fill_value=0)
            .fillna(0)
            .to_numpy(float)
        )
        totals = stocks.sum(axis=1)
        scale = max(1.0, float(totals.max()))
        opening_by_basis = (
            stock_rows.loc[stock_rows["year"].eq(reference_year)]
            .groupby("evidence_basis")["value"]
            .sum()
        )
        opening_total = totals[0]
        expected_prior = opening_by_basis.get("prior", 0.0) / opening_total if opening_total else 0
        expected_direct = (
            opening_by_basis.get("observed", 0.0) / opening_total if opening_total else 0
        )
        expected_proxy = (
            opening_by_basis.get("observed_proxy", 0.0) / opening_total if opening_total else 0
        )
        reported_direct = asset.get(
            "opening_direct_evidence_share", asset.get("opening_evidence_share", 0.0)
        )
        reported_proxy = asset.get("opening_proxy_evidence_share", 0.0)
        reported_prior = asset.get("opening_prior_share", 1.0 - reported_direct - reported_proxy)
        np.testing.assert_allclose(reported_prior, expected_prior, atol=1e-12)
        np.testing.assert_allclose(reported_direct, expected_direct, atol=1e-12)
        np.testing.assert_allclose(reported_proxy, expected_proxy, atol=1e-12)

        for metric in ("stock_share", "service_share"):
            rows = subset.loc[subset["metric"].eq(metric)]
            values = (
                rows.pivot(index="year", columns="cohort_year", values="value")
                .reindex(index=years, columns=cohorts, fill_value=0)
                .fillna(0)
                .to_numpy(float)
            )
            expected_share_sum = (totals > 0).astype(float)
            np.testing.assert_allclose(values.sum(axis=1), expected_share_sum, rtol=0, atol=1e-10)
            if metric == "stock_share":
                np.testing.assert_allclose(values * totals[:, None], stocks, rtol=1e-10, atol=1e-12)

        def annual_metric(name, data=subset):
            """Collect one annual metric for the current asset and region."""
            return (
                data.loc[data["metric"].eq(name)]
                .groupby("year")["value"]
                .sum()
                .reindex(years, fill_value=0)
                .to_numpy(float)
            )

        additions = annual_metric("addition")
        natural = annual_metric("retirement_natural")
        additional = annual_metric("retirement_additional")
        balance = totals[:-1] + additions[1:] - natural[1:] - additional[1:] - totals[1:]
        np.testing.assert_allclose(balance, 0, rtol=0, atol=1e-10 * scale)
        maximum_balance_residual = max(maximum_balance_residual, float(np.abs(balance).max()))

        source_region = original.loc[original.Region.eq(asset["region"])].set_index("Variable")
        stock_source = source_region.loc[config["stock"]["variable"]]
        for year, actual in zip(years, totals, strict=True):
            if year in source_years:
                np.testing.assert_allclose(
                    actual, stock_source[str(year)], rtol=0, atol=1e-9 * scale
                )

        joint = asset.get("annualisation")
        if joint is not None:
            np.testing.assert_allclose(
                additions[1:], joint["annual_inflows"][: len(years) - 1], rtol=1e-12, atol=1e-12
            )
            flow_source = source_region.loc[config["inflow"]["variable"]]
            fit_years = np.asarray(joint["solve_years"][1:])
            for constraint in joint["flow_constraints"]:
                target = float(flow_source[str(constraint["anchor"])])
                actual = float(additions[1:][np.isin(fit_years, constraint["years"])].mean())
                np.testing.assert_allclose(constraint["target_rate"], target, rtol=1e-12)
                np.testing.assert_allclose(constraint["reconstructed_rate"], actual, rtol=1e-12)
                np.testing.assert_allclose(constraint["rate_residual"], actual - target, atol=1e-10)

            # Recalculate every cohort trajectory from the serialized opening
            # stock, additions, lifetime law, and additional-exit fractions.
            law = config["lifetime"]
            distribution = canonical_distribution(law["distribution"])
            parameter = "maximum" if distribution == "quartic" else "mean"
            lifetimes = np.full(len(cohorts), law[f"initial_{parameter}"], dtype=float)
            future = cohorts > reference_year
            if "source" in law:
                lifetimes[future] = np.interp(
                    cohorts[future],
                    list(map(int, source_columns)),
                    source_region.loc[law["source"]["variable"], source_columns].to_numpy(float),
                )
            else:
                lifetimes[future] = law[parameter]
            births = stocks[0].copy()
            births[future] = additions[cohorts[future] - reference_year]
            fractions = dict(
                zip(joint["solve_years"], joint["additional_exit_fractions"], strict=True)
            )
            expected = np.zeros_like(stocks)
            for index, year in enumerate(years):
                age = np.maximum(0, year - cohorts)
                initial_age = np.maximum(0, reference_year - cohorts)
                if law["distribution"] == "weibull":
                    scale_lifetime = lifetimes / gamma(1 + 1 / law["shape"])
                    surviving = np.exp(
                        -(
                            (age / scale_lifetime) ** law["shape"]
                            - (initial_age / scale_lifetime) ** law["shape"]
                        )
                    )
                elif distribution == "quartic":
                    raw = np.maximum(0, 1 - (age / lifetimes) ** 4)
                    opening = np.maximum(0, 1 - (initial_age / lifetimes) ** 4)
                    surviving = np.divide(raw, opening, out=np.zeros_like(raw), where=opening > 0)
                else:
                    surviving = (age < lifetimes).astype(float)
                remaining = np.array(
                    [
                        np.prod(
                            [
                                1 - fractions[exit_year]
                                for exit_year in range(
                                    max(reference_year, int(cohort)) + 1, year + 1
                                )
                            ]
                        )
                        for cohort in cohorts
                    ]
                )
                expected[index] = births * surviving * remaining * (cohorts <= year)
            residual = float(np.abs(stocks - expected).max())
            np.testing.assert_allclose(stocks, expected, rtol=1e-9, atol=1e-9)
            maximum_survival_residual = max(maximum_survival_residual, residual)

        checks.append(
            {
                "asset": asset["asset"],
                "region": asset["region"],
                "years": len(years),
                "cohorts": len(cohorts),
                "max_balance_residual": float(np.abs(balance).max()),
                "passed": True,
                "joint_source_constraints_checked": joint is not None,
            }
        )

    expected_cases = {(asset["region"], asset["asset"]) for asset in metadata["assets"]}
    actual_cases = set(map(tuple, output[["region", "asset"]].drop_duplicates().to_numpy()))
    if actual_cases != expected_cases:
        raise ValueError("Serialized v2 asset cases differ from the report")
    result = {
        "all_passed": True,
        "format": "v2 long-form parquet",
        "source_rows": len(original),
        "serialized_rows": len(output),
        "asset_cases_checked": len(checks),
        "annual_profiles_checked": len(years) * len(checks),
        "maximum_balance_residual": maximum_balance_residual,
        "maximum_survival_residual": maximum_survival_residual,
        "asset_cases": checks,
        "output_sha256": report["output_sha256"],
    }
    destination = report_path.parent / "serialized-output-validation.json"
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "asset_cases"}))
    return result


def validate(report_path):
    """Check the output against the original scenario and the reconstruction settings."""
    report = json.loads(report_path.read_text())
    for role in ("input", "output"):
        if sha256_file(report[f"{role}_path"]) != report[f"{role}_sha256"]:
            raise ValueError(f"{role} hash mismatch")
    original = read_frame(report["input_path"])
    if Path(report["output_path"]).suffix.lower() == ".parquet":
        return validate_long_parquet(report, report_path, original)
    enriched = read_frame(report["output_path"])
    keys = ["Model", "Scenario", "Region", "Variable", "Unit"]
    old = original.set_index(keys)
    new = enriched.set_index(keys)
    retained = old.index.intersection(new.index)
    columns = year_columns(original)
    a = old.loc[retained, columns].to_numpy(float)
    b = new.loc[retained, columns].to_numpy(float)
    np.testing.assert_allclose(a, b, rtol=1e-14, atol=0, equal_nan=True)
    metadata = report["assumptions"]
    years = list(range(metadata["reference_year"], metadata["end_year"] + 1))
    labels = list(map(str, years))
    indexed = enriched.set_index(["Region", "Variable"])
    checks = []
    for asset in metadata["assets"]:
        config = asset["configuration"]
        if config["initial"]["kind"] == "observed_shares":
            if sha256_file(config["initial"]["file"]) != asset["observation_sha256"]:
                raise ValueError("Initial observation hash mismatch")
        region = indexed.loc[asset["region"]]
        prefix = PREFIX + asset["asset"] + "|"
        stocks = region.loc[region.index.str.startswith(prefix + vintage_suffix("stock", ""))]
        cohorts = np.array([int(v.split("|")[-1]) for v in stocks.index])
        quantities = stocks[labels].to_numpy(float).T
        if not np.isfinite(quantities).all() or (quantities < 0).any():
            raise ValueError("Invalid cohort quantities")
        if (quantities[cohorts[None, :] > np.array(years)[:, None]] != 0).any():
            raise ValueError("Future cohorts have positive stock")
        totals = region.loc[prefix + vintage_suffix("stock"), labels].to_numpy(float)
        np.testing.assert_allclose(quantities.sum(axis=1), totals, rtol=1e-12, atol=1e-14)
        for family in ("stock_share", "service_share"):
            values = (
                region.loc[[prefix + vintage_suffix(family, c) for c in cohorts], labels]
                .to_numpy(float)
                .T
            )
            if not np.isfinite(values).all() or (values < 0).any():
                raise ValueError("Invalid cohort shares")
            np.testing.assert_allclose(values.sum(axis=1), 1, rtol=0, atol=1e-10)
            if (values[cohorts[None, :] > np.array(years)[:, None]] != 0).any():
                raise ValueError("Future cohorts have positive share")
            if family == "stock_share":
                np.testing.assert_allclose(
                    values * totals[:, None], quantities, rtol=1e-10, atol=1e-12
                )
            elif "service" in config:
                weighting = config["service_weighting"]
                if weighting["kind"] == "age_profile":
                    if sha256_file(weighting["age_profile_file"]) != asset["age_profile_sha256"]:
                        raise ValueError("Age profile hash mismatch")
                    curve = (
                        pd.read_csv(weighting["age_profile_file"])
                        .set_index("age")["factor"]
                        .to_dict()
                    )
                    # Scalar independent lookup checks ageing and explicit tail behavior.
                    expected = quantities * np.array(
                        [
                            [0 if c > y else curve[min(y - c, max(curve))] for c in cohorts]
                            for y in years
                        ]
                    )
                    for t, y in enumerate(years[1:], 1):
                        expected[t, cohorts == y] *= weighting.get("new_cohort_exposure", 1)
                    expected /= expected.sum(axis=1)[:, None]
                    np.testing.assert_allclose(values, expected, rtol=1e-10, atol=1e-12)
                service = (
                    region.loc[[prefix + vintage_suffix("service", c) for c in cohorts], labels]
                    .to_numpy(float)
                    .T
                )
                service_total = region.loc[prefix + vintage_suffix("service"), labels].to_numpy(
                    float
                )
                np.testing.assert_allclose(
                    service.sum(axis=1), service_total, rtol=1e-12, atol=1e-12
                )
                np.testing.assert_allclose(
                    service, values * service_total[:, None], rtol=1e-10, atol=1e-12
                )
        balance = totals[:-1] - totals[1:]
        for name, sign in (("inflow", 1), ("natural_exit", -1), ("additional_exit", -1)):
            values = region.loc[prefix + vintage_suffix(name), labels].to_numpy(float)
            if (
                not np.isnan(values[0])
                or not np.isfinite(values[1:]).all()
                or (values[1:] < -1e-12).any()
            ):
                raise ValueError("Invalid annual flow or reference-year semantics")
            balance += sign * values[1:]
        np.testing.assert_allclose(balance, 0, atol=1e-10 * max(1, totals.max()), rtol=0)
        joint = asset.get("annualisation")
        if joint is not None:
            source_region = original.loc[original.Region.eq(asset["region"])].set_index("Variable")
            stock_source = source_region.loc[config["stock"]["variable"]]
            flow_source = source_region.loc[config["inflow"]["variable"]]
            source_years = set(map(int, columns))
            for year, actual in zip(years, totals, strict=True):
                if year in source_years:
                    np.testing.assert_allclose(
                        actual, stock_source[str(year)], rtol=1e-8, atol=1e-9
                    )
            fit_years = np.asarray(joint["solve_years"][1:])
            fit_inflows = np.asarray(joint["annual_inflows"])
            np.testing.assert_allclose(
                fit_inflows[: len(years) - 1],
                region.loc[prefix + vintage_suffix("inflow"), labels[1:]].to_numpy(float),
                rtol=1e-12,
                atol=1e-12,
            )
            for constraint in joint["flow_constraints"]:
                target = float(flow_source[str(constraint["anchor"])])
                actual = float(fit_inflows[np.isin(fit_years, constraint["years"])].mean())
                np.testing.assert_allclose(constraint["target_rate"], target, rtol=1e-12)
                np.testing.assert_allclose(constraint["reconstructed_rate"], actual, rtol=1e-12)
                np.testing.assert_allclose(constraint["rate_residual"], actual - target, atol=1e-10)
                if joint["exact_inflow_constraints_feasible"]:
                    np.testing.assert_allclose(actual, target, rtol=1e-8, atol=1e-8)
                if "target_total" in constraint:
                    width = len(constraint["years"])
                    np.testing.assert_allclose(constraint["target_total"], target * width)
                    np.testing.assert_allclose(
                        constraint["total_residual"], (actual - target) * width, atol=1e-8
                    )
            # Independent closed-form survival check, without the producer or flodym.
            law = config["lifetime"]
            distribution = canonical_distribution(law["distribution"])
            parameter = "maximum" if distribution == "quartic" else "mean"
            initial_parameter = f"initial_{parameter}"
            lifetimes = np.full(len(cohorts), law[initial_parameter], dtype=float)
            future = cohorts > years[0]
            if "source" in law:
                lifetimes[future] = np.interp(
                    cohorts[future],
                    list(map(int, columns)),
                    source_region.loc[law["source"]["variable"], columns].to_numpy(float),
                )
            else:
                lifetimes[future] = law[parameter]
            births = quantities[0].copy()
            births[future] = fit_inflows[cohorts[future] - years[0] - 1]
            fractions = dict(
                zip(joint["solve_years"], joint["additional_exit_fractions"], strict=True)
            )
            for index, year in enumerate(years):
                age = np.maximum(0, year - cohorts)
                initial_age = np.maximum(0, years[0] - cohorts)
                if law["distribution"] == "weibull":
                    scale = lifetimes / gamma(1 + 1 / law["shape"])
                    surviving = np.exp(
                        -((age / scale) ** law["shape"] - (initial_age / scale) ** law["shape"])
                    )
                elif distribution == "quartic":
                    raw = np.maximum(0, 1 - (age / lifetimes) ** 4)
                    opening = np.maximum(0, 1 - (initial_age / lifetimes) ** 4)
                    surviving = np.divide(
                        raw,
                        opening,
                        out=np.zeros_like(raw),
                        where=opening > 0,
                    )
                else:
                    surviving = (age < lifetimes).astype(float)
                remaining = np.array(
                    [
                        np.prod(
                            [1 - fractions[y] for y in range(max(years[0], int(c)) + 1, year + 1)]
                        )
                        for c in cohorts
                    ]
                )
                expected = births * surviving * remaining * (cohorts <= year)
                np.testing.assert_allclose(quantities[index], expected, rtol=1e-9, atol=1e-9)
        checks.append(
            {
                "asset": asset["asset"],
                "region": asset["region"],
                "years": len(years),
                "cohorts": len(cohorts),
                "max_balance_residual": float(np.abs(balance).max()),
                "passed": True,
                "joint_source_constraints_checked": joint is not None,
            }
        )
    result = {
        "all_passed": True,
        "source_rows": len(original),
        "retained_source_rows": len(retained),
        "original_anchor_values_checked": int(a.size),
        "asset_cases": checks,
        "annual_profiles_checked": len(years) * len(checks),
        "output_sha256": report["output_sha256"],
    }
    destination = report_path.parent / "serialized-output-validation.json"
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "asset_cases"}))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    validate(parser.parse_args().report)
