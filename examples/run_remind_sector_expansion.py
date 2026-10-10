"""Extend the pinned, single REMIND pilot with audited vehicle and power cohorts.

Run with PYTHONPATH=src python examples/run_remind_sector_expansion.py --help.
Scenario data, raw observations and generated profiles stay outside version control.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from run_remind_stock_pilot import make_config, record_rejected_sensitivities
from validate_stock_output import validate

import iam_preprocessor.stock_observations as observation_module
from iam_preprocessor.io import read_frame, sha256_file
from iam_preprocessor.stock_observations import (
    curate_liquid_cars,
    curate_power,
    model_observation,
    read_eia_generators,
)
from iam_preprocessor.stock_vintages import _series, prepare_stock_vintages

# Exact leaf selectors: aggregate parents and children must never be added together.
POWER = {
    "wind-onshore": ("Wind|+|Onshore", "Wind|+|Onshore", "Wind|Onshore", 25),
    "wind-offshore": ("Wind|+|Offshore", "Wind|+|Offshore", "Wind|Offshore", 25),
    "nuclear": ("+|Nuclear", "+|Nuclear", "Nuclear", 50),
    "gas-turbine": ("Gas|GT", "Gas|++|Gas Turbine", "Gas|Gas Turbine", 30),
    "geothermal": ("+|Geothermal", "+|Geothermal", "Geothermal", 30),
    "csp": ("Solar|+|CSP", "Solar|+|CSP", "Solar|CSP", 30),
}
PRIMARY = ("passenger-bev", "heavy-trucks", "pv", "ccgt", "passenger-liquids", *POWER)
NEW_CASES = (
    "primary",
    "linear-stock",
    "inflow",
    "short-life",
    "long-life",
    "inflow-penalty-low",
    "inflow-penalty-high",
)
PINS = {
    "veh1111.ods": "bc3529975f7fa9e12181b64397cb1e619ae78926130146b64f5c35b9e268d1cc",
    "eia8602022.zip": "a6f6b00f480ccfb7436804f5cb9984f27c3e0c20cfcbe9b4ed057285b5a68980",
}
DEFERRED = {
    "petrol and diesel as separate IAM fleets": "No separate native stock/sales/service series; "
    "combined Liquids only. Initial-composition sensitivities are not separate forecasts.",
    "hybrid/PHEV cars": "Hybrid electric exists, but native technology boundary versus UK HEV, "
    "PHEV and range-extended categories has not been established.",
    "gas/FCEV cars": "Native categories exist; gas versus LPG/bi-fuel crosswalk and sparse "
    "initial cohorts need review.",
    "hydropower": "Capacity, additions and lifetime exist; conventional versus pumped-storage "
    "boundary must be reconciled before using observed cohorts.",
    "coal and biomass": "Disaggregate CHP, CCS and technology aliases before selecting cohorts.",
    "battery storage": "Separate GW converter power and GWh energy stocks; obtain duration, "
    "cycle/calendar ageing and matching initial cohorts.",
    "heat, hydrogen and industrial equipment": "Some capacity/lifetime variables exist; "
    "asset boundary, initial cohorts and service units need sector-specific review.",
    "buildings, roads, water infrastructure": "No reviewed stock/inflow/lifetime crosswalk in "
    "this pilot; retain the separate observation-based infrastructure work.",
}


def make_expanded_config(archive, output, end_year=2050):
    source, config_path = make_config(archive, output, end_year)
    config = yaml.safe_load(config_path.read_text())
    frame = read_frame(source)
    paths = {name: archive / "public-sources" / name for name in PINS}
    for name, path in paths.items():
        if sha256_file(path) != PINS[name]:
            raise ValueError(f"Public observation source failed hash validation: {name}")
    cars = curate_liquid_cars(paths["veh1111.ods"])
    generators = read_eia_generators(paths["eia8602022.zip"])
    observations = {"passenger-liquids": cars["combined"]}
    observations.update({asset: curate_power(generators, asset) for asset in POWER})
    audit = {
        "implementation_sha256": {
            Path(__file__).name: sha256_file(Path(__file__)),
            "stock_observations.py": sha256_file(Path(observation_module.__file__)),
        },
        "sources": {n: {"path": str(p), "sha256": PINS[n]} for n, p in paths.items()},
        "cars_by_fuel": cars,
        "assets": {},
        "deferred": DEFERRED,
    }
    bases = {}
    for asset, record in observations.items():
        power = asset in POWER
        template = "pv" if power else "passenger-bev"
        base = deepcopy(next(a for a in config["assets"] if a["id"] == template))
        base["id"] = asset
        if power:
            capacity, service, lifetime, mean = POWER[asset]
            for role, variable, unit in (
                ("stock", "Cap|Electricity|" + capacity, "GW"),
                ("inflow", "New Cap|Electricity|" + capacity, "GW/yr"),
                ("service", "SE|Electricity|" + service, "EJ/yr"),
            ):
                base[role] = {"variable": variable, "unit": unit}
            base["lifetime"].update(
                initial_mean=mean,
                source={"variable": f"Tech|Electricity|{lifetime}|Lifetime", "unit": "years"},
            )
            initial_text = "EIA-860 operating US generator nameplate capacity by operating year. "
            initial_text += "50 states and DC; CHP and non-operating records excluded. "
            service_text = "Equal annual service per GW; no observed age-specific generation."
            observation_source = "eia8602022.zip"
        else:
            mean = 16
            for role in ("stock", "inflow", "service"):
                base[role]["variable"] = base[role]["variable"].removesuffix("BEV") + "Liquids"
            initial_text = "UK petrol plus diesel first-use-year composition is an EUR proxy. "
            initial_text += (
                "Conventional ICE proxy; IAM Liquids fuel/hybrid boundary is not resolved. "
            )
            service_text = "Equal annual service per vehicle; age-specific mileage unavailable."
            observation_source = "veh1111.ods"
        for role in ("stock", "inflow", "service"):
            _series(frame, base["region"], base[role])
        if power:
            _series(frame, base["region"], base["lifetime"]["source"])
        file = output / f"{asset}-initial.csv"
        pd.DataFrame(model_observation(record)).to_csv(file, index=False)
        base["initial"] = {
            "kind": "observed_shares",
            "file": file.name,
            "provenance": initial_text + "Unknown dates allocated proportionally to known dates "
            f"({record['unknown'] / record['total']:.6%} of selected stock). "
            "Scale shares to IAM stock; no claim that observed totals equal IAM totals. "
            f"Source {observation_source}, SHA256 {PINS[observation_source]}.",
        }
        base["service_weighting"] = {
            "kind": "equal",
            "annual_age_decay": 0,
            "provenance": service_text,
        }
        if power:
            base["service_weighting"]["maximum_service_per_stock"] = 0.031536
        bases[asset] = base
        stock_series = _series(frame, base["region"], base["stock"])
        initial_stock = float(np.interp(2022, list(stock_series), list(stock_series.values())))
        observed_native_units = record["total"] / (1000 if power else 1e6)
        audit["assets"][asset] = dict(
            record,
            initial_csv_sha256=sha256_file(file),
            initial_csv=str(file),
            unknown_share=record["unknown"] / record["total"],
            unknown_date_policy="Proportional allocation to known dates (assumption)",
            cohort_date_semantics="operating year" if power else "year of first use",
            observation_unit="MW nameplate" if power else "vehicle",
            observation_geography="USA" if power else "UK",
            iam_initial_stock=initial_stock,
            iam_stock_unit=base["stock"]["unit"],
            iam_to_observed_stock_ratio=initial_stock / observed_native_units,
            selectors={k: base[k] for k in ("stock", "inflow", "service")},
        )
        for case in NEW_CASES:
            item = deepcopy(base)
            item["id"] = asset if case == "primary" else f"{asset}-{case}"
            if case == "linear-stock":
                item["mode"] = "stock"
                item.pop("annualisation")
            elif case == "inflow":
                item.update(mode="inflow", exit_policy="error")
                item.pop("annualisation")
            elif case in ("short-life", "long-life"):
                life = mean * (0.75 if case == "short-life" else 1.25)
                item["lifetime"].pop("source", None)
                item["lifetime"].update(initial_mean=life, mean=life)
            elif case.startswith("inflow-penalty"):
                item["annualisation"]["inflow_weight"] = 1 if case.endswith("low") else 100
            config["assets"].append(item)
    for fuel in ("petrol", "diesel"):
        item = deepcopy(bases["passenger-liquids"])
        item["id"] += f"-{fuel}-composition"
        file = output / f"passenger-liquids-{fuel}-initial.csv"
        pd.DataFrame(model_observation(cars[fuel])).to_csv(file, index=False)
        unknown_share = cars[fuel]["unknown"] / cars[fuel]["total"]
        item["initial"] = {
            "kind": "observed_shares",
            "file": file.name,
            "provenance": f"UK {fuel}-only initial composition applied to the entire IAM Liquids "
            "trajectory as a sensitivity. Not a separate fuel forecast or additive stock. "
            f"Unknown dates proportionally assigned ({unknown_share:.6%}). "
            f"Source veh1111.ods, SHA256 {PINS['veh1111.ods']}.",
        }
        config["assets"].append(item)
    audit["primary_assets"] = list(PRIMARY)
    (output / "sector-observation-audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    return source, config_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--end-year", type=int, default=2050)
    args = parser.parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise ValueError("Choose an empty output directory")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source, config = make_expanded_config(args.archive, args.output_dir, args.end_year)
    record_rejected_sensitivities(source, config, primary_ids=PRIMARY)
    report = prepare_stock_vintages(source, args.output_dir, config)
    validation = validate(
        Path(report.output_path).with_name(Path(report.output_path).stem + "_report.json")
    )
    print(
        json.dumps(
            {
                "output": report.output_path,
                "sha256": report.output_sha256,
                "cases": len(report.assumptions["assets"]),
                "validation": validation,
            }
        )
    )


if __name__ == "__main__":
    main()
