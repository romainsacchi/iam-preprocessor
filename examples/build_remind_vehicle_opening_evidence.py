"""Build a 2020 REMIND configuration with traceable UK vehicle-age proxies.

The DfT population is the United Kingdom, while REMIND's UKI region also
contains Ireland. The observations are therefore deliberately labelled as
composition proxies, even when their source table has almost complete dates.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pandas as pd
import yaml

from iam_preprocessor.io import read_frame, sha256_file
from iam_preprocessor.research.remind.stock_config import build_remind_stock_config
from iam_preprocessor.stock_observations import curate_vehicle_history, model_observation

SOURCE_URL = "https://assets.publishing.service.gov.uk/media/69ef3555606c20d41216341a/veh1111.ods"
MAPPINGS = {
    "passenger-bev": "passenger-ldv-4w-bev",
    "passenger-liquids": "passenger-ldv-4w-liquids",
    "heavy-trucks": "heavy-trucks-liquids",
}


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", type=Path)
    parser.add_argument("vehicle_ods", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--end-year", type=int, default=2050)
    return parser.parse_args()


def main():
    args = arguments()
    output = args.output_dir.resolve()
    raw = output / "raw"
    observations = output / "observations"
    raw.mkdir(parents=True, exist_ok=True)
    observations.mkdir(parents=True, exist_ok=True)
    source = args.vehicle_ods.resolve()
    archived = raw / "veh1111.ods"
    if source != archived:
        shutil.copy2(source, archived)

    frame = read_frame(args.scenario)
    config, skipped = build_remind_stock_config(
        frame,
        regions=["DEU", "FRA", "UKI"],
        reference_year=2020,
        end_year=args.end_year,
        reconciliation="joint",
    )
    # A 2005 equilibrium warm start cannot be advanced to 2020 for every asset:
    # several historical IAM stock/addition pairs are infeasible under their
    # survival laws. Keep the unevidenced opening state explicit at 2020 rather
    # than hiding an inconsistent historical reconciliation.
    for asset in config["assets"]:
        initial = asset["initial"]
        if initial["kind"] == "warm_start":
            asset["initial"] = {
                "kind": "equilibrium",
                "maximum_age": initial["maximum_age"],
                "acknowledge_prior": True,
                "provenance": (
                    "Stationary opening-vintage prior at 2020. The 2005-2019 IAM "
                    "stock/addition history is not forced because some mapped series are "
                    "infeasible under their configured survival laws."
                ),
            }
    history = curate_vehicle_history(archived)
    by_identity = {(asset["region"], asset["id"]): asset for asset in config["assets"]}
    summary = []
    for source_asset, target_asset in MAPPINGS.items():
        record = history[(source_asset, 2020)]
        curated = model_observation(record, reference_year=2020)
        destination = observations / f"UKI-{target_asset}-2020.csv"
        pd.DataFrame(
            {
                "cohort": [row["cohort"] for row in curated],
                "amount": [row["amount"] for row in curated],
            }
        ).to_csv(destination, index=False)
        asset = by_identity[("UKI", target_asset)]
        service_life = asset["lifetime"]["mean"]
        asset["lifetime"] = {
            "distribution": "weibull",
            "initial_mean": service_life,
            "mean": service_life,
            "shape": 3,
            "interpretation": (
                "Mean service-life prior with a Weibull tail; required because the observed "
                "opening population contains vehicles older than the REMIND serviceLife value."
            ),
            "provenance": (
                "Reviewed vehicle prior used by the bounded REMIND evidence campaign; shape "
                "is assumed, not fitted to this opening snapshot."
            ),
        }
        boundary = (
            "DfT HGV includes all fuels and is broader than the IAM liquid heavy-truck class; "
            if source_asset == "heavy-trucks"
            else "DfT UK excludes Ireland, which is included in REMIND UKI; "
        )
        asset["initial"] = {
            "kind": "observed_shares",
            "file": str(destination.relative_to(output)),
            "evidence_kind": "composition_proxy",
            "provenance": (
                "DfT VEH1111 licensed stock at end-2020 by first-use year. "
                + boundary
                + "the dated source composition is rescaled to the IAM opening stock. "
                "Unknown first-use years are allocated proportionally across dated source cohorts."
            ),
        }
        known = sum(record["cohorts"].values())
        summary.append(
            {
                "region": "UKI",
                "asset": target_asset,
                "source_population": source_asset,
                "source_total_vehicles": record["total"],
                "source_dated_vehicles": known,
                "source_dated_share": known / record["total"],
                "evidence_kind": "composition_proxy",
                "observation_file": str(destination.relative_to(output)),
                "observation_sha256": sha256_file(destination),
            }
        )

    manifest = {
        "schema_version": 1,
        "sources": [
            {
                "source_id": "dft-veh1111-2026-09-23",
                "url": SOURCE_URL,
                "version": "VEH1111 page revision 2026-09-23",
                "observation_year": 2020,
                "downloaded_at": "2026-10-27",
                "sha256": sha256_file(archived),
                "license": "Open Government Licence v3.0",
                "adapter_version": "iam-preprocessor stock_observations v1",
                "path": str(archived.relative_to(output)),
            }
        ],
    }
    manifest_path = output / "evidence-manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    config["evidence_manifest"] = manifest_path.name
    config_path = output / "stocks-with-opening-evidence.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    report = {
        "reference_year": 2020,
        "assets_total": len(config["assets"]),
        "proxy_assets": len(summary),
        "direct_observation_assets": 0,
        "prior_assets": len(config["assets"]) - len(summary),
        "proxy_details": summary,
        "skipped_mappings": skipped,
        "decision": (
            "Only reviewed, openly licensed DfT vehicle cohorts were promoted. "
            "They remain proxies and cannot satisfy direct-evidence coverage."
        ),
        "opening_prior_decision": (
            "Unevidenced assets use a 2020 equilibrium prior; infeasible 2005-2019 warm starts "
            "are not forced."
        ),
        "vehicle_lifetime_decision": (
            "The three evidenced vehicle assets use the previously reviewed Weibull shape-3 "
            "mean-life prior because observed survivors exceed fixed REMIND serviceLife ages."
        ),
    }
    (output / "opening-evidence-summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(config_path)


if __name__ == "__main__":
    main()
