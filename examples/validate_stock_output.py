"""Independently validate serialized stock enrichment against its source/report."""

import argparse
import json
from pathlib import Path

import numpy as np

from iam_preprocessor.io import read_frame, sha256_file, year_columns
from iam_preprocessor.stock_vintages import PREFIX


def validate(report_path):
    report = json.loads(report_path.read_text())
    for role in ("input", "output"):
        if sha256_file(report[f"{role}_path"]) != report[f"{role}_sha256"]:
            raise ValueError(f"{role} hash mismatch")
    original = read_frame(report["input_path"])
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
        stocks = region.loc[region.index.str.startswith(prefix + "Stock|Vintage|")]
        cohorts = np.array([int(v.split("|")[-1]) for v in stocks.index])
        quantities = stocks[labels].to_numpy(float).T
        if not np.isfinite(quantities).all() or (quantities < 0).any():
            raise ValueError("Invalid cohort quantities")
        if (quantities[cohorts[None, :] > np.array(years)[:, None]] != 0).any():
            raise ValueError("Future cohorts have positive stock")
        totals = region.loc[prefix + "Stock", labels].to_numpy(float)
        np.testing.assert_allclose(quantities.sum(axis=1), totals, rtol=1e-12, atol=1e-14)
        for family in ("Stock Share", "Service Share"):
            values = (
                region.loc[[prefix + f"{family}|Vintage|{c}" for c in cohorts], labels]
                .to_numpy(float)
                .T
            )
            if not np.isfinite(values).all() or (values < 0).any():
                raise ValueError("Invalid cohort shares")
            np.testing.assert_allclose(values.sum(axis=1), 1, rtol=0, atol=1e-10)
            if (values[cohorts[None, :] > np.array(years)[:, None]] != 0).any():
                raise ValueError("Future cohorts have positive share")
            if family == "Stock Share":
                np.testing.assert_allclose(
                    values * totals[:, None], quantities, rtol=1e-10, atol=1e-12
                )
            elif "service" in config:
                service = (
                    region.loc[[prefix + f"Service|Vintage|{c}" for c in cohorts], labels]
                    .to_numpy(float)
                    .T
                )
                service_total = region.loc[prefix + "Service", labels].to_numpy(float)
                np.testing.assert_allclose(
                    service.sum(axis=1), service_total, rtol=1e-12, atol=1e-12
                )
                np.testing.assert_allclose(
                    service, values * service_total[:, None], rtol=1e-10, atol=1e-12
                )
        balance = totals[:-1] - totals[1:]
        for name, sign in (("Inflow", 1), ("Natural Exit", -1), ("Additional Exit", -1)):
            values = region.loc[prefix + name, labels].to_numpy(float)
            if (
                not np.isnan(values[0])
                or not np.isfinite(values[1:]).all()
                or (values[1:] < -1e-12).any()
            ):
                raise ValueError("Invalid annual flow or reference-year semantics")
            balance += sign * values[1:]
        np.testing.assert_allclose(balance, 0, atol=1e-10 * max(1, totals.max()), rtol=0)
        checks.append(
            {
                "asset": asset["asset"],
                "region": asset["region"],
                "years": len(years),
                "cohorts": len(cohorts),
                "max_balance_residual": float(np.abs(balance).max()),
                "passed": True,
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
