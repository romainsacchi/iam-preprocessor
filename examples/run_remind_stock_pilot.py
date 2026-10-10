"""Reproduce the local SSP2-NPi2025 pilot from the existing evidence archive.

No source or generated scenario data is bundled. Initial shares are imported
from the archived, curated 2022 observations; future pilot projections are not
used as input. Run with ``python examples/run_remind_stock_pilot.py --help``.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from iam_preprocessor.exceptions import DataValidationError
from iam_preprocessor.io import read_frame, sha256_file
from iam_preprocessor.stock_config import load_stock_config
from iam_preprocessor.stock_vintages import PREFIX, _asset_result, prepare_stock_vintages

FILES = {
    "passenger-bev": "bev-npi2025-cohorts.json",
    "heavy-trucks": "trucks-npi2025-cohorts.json",
    "pv": "pv-npi2025-cohorts.json",
    "ccgt": "ccgt-npi-cohorts.json",
}
MEANS = {"passenger-bev": 16, "heavy-trucks": 12, "pv": 30, "ccgt": 35}
ARCHIVE_MANIFEST_SHA256 = "c15467bdb209ece5c556248c16edc6257dae034dd121b9a6c935b4f5fe726231"
CASES = (
    "primary",
    "inflow",
    "short-life",
    "long-life",
    "equal-service",
    "age-decay",
    "equilibrium",
    "half-year-entrants",
    "linear-stock",
    "inflow-penalty-low",
    "inflow-penalty-high",
)


def make_config(archive, output, end_year, annualisation="joint"):
    if not 2030 <= end_year <= 2050:
        raise ValueError(
            "This reviewed REMIND example supports 2030–2050; later periods need review."
        )
    manifest_path = archive / "manifest.json"
    if sha256_file(manifest_path) != ARCHIVE_MANIFEST_SHA256:
        raise ValueError("Archive manifest differs from the reviewed evidence snapshot.")
    pins = {item["path"]: item["sha256"] for item in json.loads(manifest_path.read_text())["files"]}
    config = {
        "schema_version": 1,
        "model": "REMIND",
        "scenario": "SSP2-NPi2025",
        "reference_year": 2022,
        "end_year": end_year,
        "assets": [],
    }
    inputs = {}
    source = archive / "iam-inputs/remind 3.5.2/REMIND_generic_SSP2-NPi2025.mif"
    for asset, name in FILES.items():
        path = archive / "cohorts" / name
        if sha256_file(path) != pins.get(str(path.relative_to(archive))):
            raise ValueError(f"Archived reference cohorts failed hash validation: {name}")
        evidence = json.loads(path.read_text())
        if sha256_file(source) != evidence["iam_source"]["sha256"]:
            raise ValueError("Scenario differs from the pinned source archive.")
        initial = evidence["cases"]["primary"]["annual"][0]
        if initial["service_year"] != 2022:
            raise ValueError("Expected an observed 2022 initial condition.")
        power = asset in ("pv", "ccgt")
        quantities = initial["cohort_capacity_mw_ac" if power else "cohort_stock_vehicles"]
        outputs = initial["cohort_generation_mwh" if power else "cohort_service_index"]
        average = sum(outputs.values()) / sum(quantities.values())
        rows = [
            {
                "cohort": int(c),
                "amount": q,
                "service_factor": outputs.get(c, 0) / q / average if q else 0,
            }
            for c, q in quantities.items()
        ]
        observation = output / f"{asset}-initial.csv"
        pd.DataFrame(rows).to_csv(observation, index=False)
        variables = evidence["iam_source"]["variables"]

        def selector(key, variables=variables):
            return dict(zip(("variable", "unit"), variables[key], strict=True))

        mean = MEANS[asset]
        law = {
            "distribution": "weibull",
            "initial_mean": mean,
            "shape": 3,
            "interpretation": "Assumed mean service life for a Weibull sensitivity; "
            "not native REMIND survival",
            "provenance": "Power: scenario technical life reinterpreted as a modelling prior. "
            "Vehicles: explicit 16/12-year mean priors; not native EDGE lifetime parameters.",
        }
        law.update({"source": selector("lifetime")} if power else {"mean": mean})
        timing = (
            {
                "kind": "reported_periods",
                "periods": [
                    {"anchor": y, "start": y - 2, "end": y + 2} for y in range(2025, 2056, 5)
                ],
                "provenance": "Pinned remind2 reporter: five-year centred reported rates; "
                "flat within-window expansion is assumed, not unique native annual investment.",
            }
            if power
            else {
                "kind": "sampled_annual",
                "provenance": "Pinned reporttransport: sampled annual vehicle sales; "
                "linear interpolation assumed.",
            }
        )
        base = {
            "id": asset,
            "region": "USA" if power else "EUR",
            "mode": annualisation,
            "exit_policy": "proportional",
            "stock": selector("capacity" if power else "stock"),
            "inflow": selector("additions" if power else "sales"),
            "service": selector("generation" if power else "service"),
            "inflow_timing": timing,
            "lifetime": law,
            "initial": {
                "kind": "observed_shares",
                "file": observation.name,
                "provenance": (
                    "US-WECC selected observed plants used as a USA age-composition proxy. "
                    if power
                    else "UK selected observed vehicles used as an EUR age-composition proxy. "
                )
                + "Shares scaled to IAM regional stock, not an observed regional total. "
                + f"Archived source {name}, SHA256 {sha256_file(path)}.",
            },
            "service_weighting": {
                "kind": "observed_factors" if power else "equal",
                "annual_age_decay": 0,
                "provenance": "Initial observed output/capacity factors; "
                "future entrants at initial fleet mean."
                if power
                else "Equal annual service per vehicle assumed; age-specific use unavailable.",
            },
        }
        if power:
            base["service_weighting"]["future_factor"] = 1
            # EJ/yr per GW, equivalent to 8760 full-load hours (365-day convention).
            base["service_weighting"]["maximum_service_per_stock"] = 0.031536
        if annualisation == "joint":
            base["annualisation"] = {
                "inflow_constraints": "penalized",
                "reference_weight": 0.01,
                "inflow_weight": 10,
                "provenance": "Exact native stock anchors; source inflow samples/window "
                "means imposed when feasible. Otherwise balance squared rate residuals "
                "and curvature with declared weights. Fixed baseline proportional exit fractions.",
            }
        for case in CASES:
            item = deepcopy(base)
            item["id"] = asset if case == "primary" else f"{asset}-{case}"
            if case == "inflow":
                item.update(mode="inflow", exit_policy="error")
                item.pop("annualisation", None)
            elif case == "linear-stock":
                item.update(mode="stock")
                item.pop("annualisation", None)
            elif case in ("inflow-penalty-low", "inflow-penalty-high"):
                if annualisation != "joint":
                    continue
                item["annualisation"]["inflow_weight"] = 1 if case == "inflow-penalty-low" else 100
            elif case in ("short-life", "long-life"):
                factor = 0.75 if case == "short-life" else 1.25
                item["lifetime"].pop("source", None)
                item["lifetime"].update(mean=mean * factor, initial_mean=mean * factor)
            elif case == "equal-service":
                item["service_weighting"] = {
                    "kind": "equal",
                    "annual_age_decay": 0,
                    "provenance": "Equal service per vehicle or GW sensitivity.",
                }
            elif case == "age-decay":
                item["service_weighting"]["annual_age_decay"] = 0.03
                item["service_weighting"]["provenance"] += (
                    " Additional 3% exponential annual age decay sensitivity."
                )
            elif case == "half-year-entrants":
                item["service_weighting"]["new_cohort_exposure"] = 0.5
                item["service_weighting"]["provenance"] += (
                    " Half-year service exposure for new cohorts."
                )
            elif case == "equilibrium":
                item["initial"] = {
                    "kind": "equilibrium",
                    "maximum_age": 120,
                    "provenance": "Truncated stationary-inflow age prior; unobserved sensitivity.",
                }
                item["service_weighting"] = {
                    "kind": "equal",
                    "annual_age_decay": 0,
                    "provenance": "Equal service per unit assumed.",
                }
            if power:
                item["service_weighting"]["maximum_service_per_stock"] = 0.031536
            config["assets"].append(item)
        inputs[asset] = {
            "path": str(path),
            "sha256": sha256_file(path),
            "observation_file_sha256": sha256_file(observation),
        }
    path = output / "remind-npi2025-stock-config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    (output / "pilot-inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
    return source, path


def plot_results(output, report):
    frame = read_frame(report.output_path).set_index(["Region", "Variable"])
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    ages = []
    for (asset, _), ax in zip(FILES.items(), axes.flat, strict=True):
        region = "USA" if asset in ("pv", "ccgt") else "EUR"
        subset = frame.loc[region]
        for year in sorted({2022, 2030, report.assumptions["end_year"]}):
            rows = subset.loc[
                subset.index.str.startswith(PREFIX + asset + "|Service Share|Vintage|")
            ]
            cohorts = np.array([int(v.split("|")[-1]) for v in rows.index])
            ax.plot(cohorts, rows[str(year)], label=str(year))
        ax.set(
            title=f"{asset}: reconstructed service composition",
            xlabel="Entry / cohort year",
            ylabel="Share",
        )
        ax.legend()
        for case in CASES:
            ident = asset if case == "primary" else f"{asset}-{case}"
            rows = subset.loc[
                subset.index.str.startswith(PREFIX + ident + "|Service Share|Vintage|")
            ]
            if rows.empty:
                continue
            cohorts = np.array([int(v.split("|")[-1]) for v in rows.index])
            for year in range(
                report.assumptions["reference_year"], report.assumptions["end_year"] + 1
            ):
                weights = rows[str(year)].to_numpy(float)
                ages.append(
                    {
                        "asset": asset,
                        "case": case,
                        "year": year,
                        "mean_age": float(np.dot(year - cohorts, weights)),
                        "weight_sum": float(weights.sum()),
                    }
                )
    fig.savefig(output / "vintage-distributions.pdf")
    fig.savefig(output / "vintage-distributions.png", dpi=180)
    plt.close(fig)
    ages = pd.DataFrame(ages)
    ages.to_csv(output / "mean-age-sensitivities.csv", index=False)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    for asset, ax in zip(FILES, axes.flat, strict=True):
        for case in CASES:
            data = ages.loc[ages.asset.eq(asset) & ages.case.eq(case)]
            if data.empty:
                continue
            ax.plot(data.year, data.mean_age, label=case)
        ax.set(title=asset, xlabel="Service year", ylabel="Mean serving-stock age (years)")
        ax.legend(fontsize=7)
    fig.savefig(output / "lifetime-and-constraint-sensitivities.pdf")
    fig.savefig(output / "lifetime-and-constraint-sensitivities.png", dpi=180)
    plt.close(fig)


def record_rejected_sensitivities(source, config_path):
    """Keep physical service-limit failures visible without exporting invalid profiles.

    Primary cases, solver failures and other data errors always abort. Only
    optional sensitivity cases exceeding the declared service bound are excluded.
    """
    frame, config = read_frame(source), load_stock_config(config_path)
    rejected = []
    for asset in config["assets"]:
        try:
            _asset_result(frame, asset, config["reference_year"], config["end_year"])
        except DataValidationError as exc:
            if asset["id"] in FILES or "service exceeds the declared per-stock bound" not in str(
                exc
            ):
                raise
            rejected.append({"asset": asset["id"], "reason": str(exc), "configuration": asset})
    raw = yaml.safe_load(config_path.read_text())
    ids = {item["asset"] for item in rejected}
    raw["assets"] = [a for a in raw["assets"] if a["id"] not in ids]
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    ledger = {
        "attempted_cases": len(config["assets"]),
        "accepted_cases": len(raw["assets"]),
        "rejected": rejected,
    }
    (config_path.parent / "rejected-sensitivities.json").write_text(
        json.dumps(ledger, indent=2) + "\n"
    )
    return ledger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--end-year", type=int, default=2050)
    parser.add_argument("--annualisation", choices=("joint", "stock"), default="joint")
    args = parser.parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise ValueError("Choose an empty local output directory.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source, config = make_config(args.archive, args.output_dir, args.end_year, args.annualisation)
    record_rejected_sensitivities(source, config)
    report = prepare_stock_vintages(source, args.output_dir, config)
    plot_results(args.output_dir, report)
    print(
        json.dumps(
            {
                "output": report.output_path,
                "sha256": report.output_sha256,
                "rows": report.output_rows,
                "cases": len(report.assumptions["assets"]),
            }
        )
    )


if __name__ == "__main__":
    main()
