"""Build a REMIND sensitivity with 2005 road-vehicle evidence from JRC-IDEES.

The source table provides 2005 stocks and annual new-vehicle counts for
2000--2005. The recent entry cohorts are used as composition proxies; the
unobserved older remainder retains an explicitly labelled equilibrium prior.

JRC-IDEES-2021 covers EU27 countries and does not contain the United Kingdom.
DEU and FRA are anchored; UKI is deliberately left unchanged rather than mixed
with the manually transcribed IEDC copy of the older JRC-IDEES-2015 release.
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

JRC_SHA256 = "a023357fd5eb758495adf7e0fb28d5eb4f27dd4752ea6cbb5ee47faf4c158864"
JRC_DOWNLOAD_URL = (
    "https://ckan.tdc.prod.datopian.com/dataset/"
    "ce8e9578-0209-48cf-8165-4cf2f15f0501/resource/"
    "b11d0772-9c53-4b1d-992d-5df54188fffb/download/"
    "jrc-idees-2021-roadtransport-me1z1o.csv"
)
JRC_OFFICIAL_URL = "https://data.jrc.ec.europa.eu/dataset/82322924-506a-4c9a-8532-2bdd30d69bf5"
REGIONS = {"DEU": "DE", "FRA": "FR"}


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("jrc_csv", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--end-year", type=int, default=2050)
    return parser.parse_args()


def jrc_table(path):
    frame = pd.read_csv(path)
    required = {
        "VARIABLE",
        "UNIT_MEASURE",
        "GEO",
        "TYPE",
        "MODE",
        "TECHNOLOGY",
        "FUEL_MAIN",
        "TIME_PERIOD",
        "VALUE",
    }
    if not required.issubset(frame.columns):
        raise ValueError(f"JRC table is missing columns: {sorted(required - set(frame.columns))}")
    selected = frame.loc[
        frame["VARIABLE"].isin({"Stock", "StockNew"})
        & frame["UNIT_MEASURE"].eq("number")
        & frame["TIME_PERIOD"].between(2000, 2005)
        & frame["GEO"].isin(REGIONS.values())
    ].copy()
    if selected.empty:
        raise ValueError("No 2000--2005 JRC vehicle-stock records found for DE and FR.")
    if selected["VALUE"].isna().any() or (selected["VALUE"] < 0).any():
        raise ValueError("JRC vehicle stocks must be finite and nonnegative.")
    return selected


def one_value(
    jrc,
    geo,
    mode,
    technology="Total",
    fuel="Total",
    *,
    variable="Stock",
    year=2005,
):
    rows = jrc.loc[
        jrc["GEO"].eq(geo)
        & jrc["MODE"].eq(mode)
        & jrc["TECHNOLOGY"].eq(technology)
        & jrc["FUEL_MAIN"].eq(fuel)
        & jrc["VARIABLE"].eq(variable)
        & jrc["TIME_PERIOD"].eq(year)
    ]
    if len(rows) != 1:
        raise ValueError(
            f"Expected one JRC row for {variable}/{year}/{geo}/{mode}/"
            f"{technology}/{fuel}; got {len(rows)}."
        )
    return float(rows.iloc[0]["VALUE"]) / 1_000_000


def source_value(frame, region, variable):
    rows = frame.loc[
        frame["Region"].eq(region)
        & frame["Variable"].eq(variable)
        & frame["Unit"].eq("million veh")
    ]
    if len(rows) != 1:
        raise ValueError(f"Expected one REMIND stock row for {region}/{variable}.")
    return float(rows.iloc[0]["2005"])


def target_stocks(frame, config, jrc, *, variable="Stock", year=2005):
    assets = {(a["region"], a["id"]): a for a in config["assets"]}
    result = {}
    rules = {}

    def lookup(geo, mode, technology="Total", fuel="Total"):
        return one_value(
            jrc,
            geo,
            mode,
            technology,
            fuel,
            variable=variable,
            year=year,
        )

    for region, geo in REGIONS.items():
        # Passenger cars: JRC's listed technologies exhaust the reported total.
        # PHEV is the nearest available source category for REMIND Hybrid electric;
        # the mapping is explicit because the two labels are not fully equivalent.
        car_ids = {
            "bev": "passenger-ldv-4w-bev",
            "fcev": "passenger-ldv-4w-fcev",
            "gases": "passenger-ldv-4w-gases",
            "hybrid": "passenger-ldv-4w-hybrid",
            "liquids": "passenger-ldv-4w-liquids",
        }
        car_total = lookup(geo, "Car")
        car_bev = lookup(geo, "Car", "BEV")
        car_gases = lookup(geo, "Car", "ICE", "NGas")
        car_fcev = 0.0
        car_hybrid = lookup(geo, "Car", "PHEV")
        car_liquids = car_total - car_bev - car_gases - car_fcev - car_hybrid
        if car_liquids < 0:
            raise ValueError(f"Negative residual car liquids stock for {region}.")
        values = {
            car_ids["bev"]: car_bev,
            car_ids["fcev"]: car_fcev,
            car_ids["gases"]: car_gases,
            car_ids["hybrid"]: car_hybrid,
            car_ids["liquids"]: car_liquids,
        }
        for asset_id, value in values.items():
            result[region, asset_id] = value
            rules[region, asset_id] = (
                "JRC direct stock"
                if asset_id.endswith(("-bev", "-gases"))
                else "JRC exhaustive split: unlisted FCEV assigned zero"
                if asset_id.endswith("-fcev")
                else "JRC PHEV mapped to REMIND Hybrid electric; boundary differs"
                if asset_id.endswith("-hybrid")
                else "JRC total residual after mapped technology stocks"
            )

        # Buses and light commercial vehicles: anchor compatible BEV and natural-
        # gas categories, assign the unlisted FCEV category zero, and assign the
        # JRC total residual to liquids.
        for family, mode in (("buses", "Bus"), ("light-trucks", "LCV")):
            ids = {key: f"{family}-{key}" for key in ("bev", "fcev", "gases", "liquids")}
            total = lookup(geo, mode)
            bev = lookup(geo, mode, "BEV", "Elec")
            gases = lookup(geo, mode, "ICE", "NGas")
            fcev = 0.0
            liquids = total - bev - gases - fcev
            if liquids < 0:
                raise ValueError(f"Negative residual {family} liquids stock for {region}.")
            for asset_id, value, rule in (
                (ids["bev"], bev, "JRC direct stock"),
                (ids["fcev"], fcev, "JRC exhaustive split: unlisted FCEV assigned zero"),
                (ids["gases"], gases, "JRC direct stock"),
                (ids["liquids"], liquids, "JRC total residual after BEV, gas and FCEV"),
            ):
                result[region, asset_id] = value
                rules[region, asset_id] = rule

        # JRC reports only an HGV total. Preserve REMIND's 2005 technology shares
        # and rescale all four children to the JRC total.
        heavy_ids = [f"heavy-trucks-{key}" for key in ("bev", "fcev", "gases", "liquids")]
        old = {
            asset_id: source_value(frame, region, assets[region, asset_id]["stock"]["variable"])
            for asset_id in heavy_ids
        }
        old_total = sum(old.values())
        if old_total <= 0:
            raise ValueError(f"Cannot allocate JRC heavy-truck total for {region}.")
        heavy_total = lookup(geo, "HGV_all")
        for asset_id in heavy_ids:
            result[region, asset_id] = heavy_total * old[asset_id] / old_total
            rules[region, asset_id] = "JRC HGV total allocated by original REMIND technology share"
    return result, rules


def main():
    args = arguments()
    output = args.output_dir.resolve()
    raw = output / "raw"
    observations = output / "observations"
    raw.mkdir(parents=True, exist_ok=True)
    observations.mkdir(parents=True, exist_ok=True)
    source = args.jrc_csv.resolve()
    if sha256_file(source) != JRC_SHA256:
        raise ValueError("JRC source checksum differs from the reviewed download.")
    archived = raw / "JRC-IDEES-2021_RoadTransport.csv"
    if source != archived:
        shutil.copy2(source, archived)

    frame = read_frame(args.scenario)
    config, skipped = build_remind_stock_config(
        frame,
        regions=["DEU", "FRA", "UKI"],
        reference_year=2005,
        end_year=args.end_year,
        reconciliation="joint",
    )
    jrc = jrc_table(archived)
    targets, rules = target_stocks(frame, config, jrc)
    histories = {identity: {} for identity in targets}
    for year in range(2000, 2006):
        annual, _ = target_stocks(frame, config, jrc, variable="StockNew", year=year)
        for identity in histories:
            histories[identity][year] = annual[identity]
    assets = {(a["region"], a["id"]): a for a in config["assets"]}
    mapping = []
    mapping_by_identity = {}
    for identity, target in targets.items():
        region, asset_id = identity
        asset = assets.get(identity)
        if asset is None:
            raise ValueError(f"JRC target is not a selected REMIND asset: {identity}")
        variable = asset["stock"]["variable"]
        rows = (
            frame["Region"].eq(region)
            & frame["Variable"].eq(variable)
            & frame["Unit"].eq("million veh")
        )
        if rows.sum() != 1:
            raise ValueError(f"Expected one target IAM row for {region}/{asset_id}.")
        old = float(frame.loc[rows, "2005"].iloc[0])
        frame.loc[rows, "2005"] = target
        record = {
            "region": region,
            "asset": asset_id,
            "variable": variable,
            "unit": "million veh",
            "remind_2005": old,
            "jrc_anchored_2005": target,
            "absolute_change": target - old,
            "relative_change": target / old - 1 if old else None,
            "mapping_rule": rules[identity],
            "opening_proxy_share": 0.0,
            "opening_prior_share": 0.0 if target == 0 else 1.0,
            "registration_reconciliation_factor": None,
        }
        mapping.append(record)
        mapping_by_identity[identity] = record

    observation_summary = []
    for identity, target in targets.items():
        asset = assets[identity]
        recent = histories[identity]
        recent_total = sum(recent.values())
        if target <= 0 or recent_total <= 0:
            asset["initial"]["provenance"] = (
                "Equilibrium opening-vintage prior at 2005, rescaled to the JRC-IDEES-2021 "
                "stock anchor. No positive mapped StockNew cohort was available. "
                f"{rules[identity]}."
            )
            continue
        factor = min(1.0, target / recent_total)
        reconciled = {year: amount * factor for year, amount in recent.items()}
        proxy_total = sum(reconciled.values())
        prior_total = max(0.0, target - proxy_total)
        maximum_age = asset["initial"]["maximum_age"]
        # The fixed vehicle survival prior has zero stock at exactly maximum_age;
        # distribute the older remainder over positive-survival cohorts only.
        older = list(range(2005 - maximum_age + 1, 2000))
        rows = [
            {
                "cohort": cohort,
                "amount": prior_total / len(older),
                "evidence_basis": "prior",
            }
            for cohort in older
            if prior_total > 0
        ]
        rows.extend(
            {
                "cohort": year,
                "amount": amount,
                "evidence_basis": "observed_proxy",
            }
            for year, amount in reconciled.items()
            if amount > 0
        )
        destination = observations / f"{identity[0]}-{identity[1]}-2005.csv"
        pd.DataFrame(rows).to_csv(destination, index=False)
        asset["initial"] = {
            "kind": "observed_shares",
            "file": str(destination.relative_to(output)),
            "evidence_kind": "composition_proxy",
            "provenance": (
                "Hybrid opening composition at 2005. JRC-IDEES-2021 StockNew counts for "
                "2000-2005 define recent entry-cohort proxies; the older stock remainder is "
                "distributed using the configured equilibrium prior. StockNew is not a direct "
                "observation of surviving end-2005 cohorts. Recent entries are proportionally "
                f"reconciled only when their sum exceeds the mapped 2005 stock. {rules[identity]}."
            ),
        }
        record = mapping_by_identity[identity]
        record["opening_proxy_share"] = proxy_total / target
        record["opening_prior_share"] = prior_total / target
        record["registration_reconciliation_factor"] = factor
        observation_summary.append(
            {
                "region": identity[0],
                "asset": identity[1],
                "file": str(destination.relative_to(output)),
                "sha256": sha256_file(destination),
                "jrc_stocknew_2000_2005": recent_total,
                "jrc_stock_2005": target,
                "opening_proxy_share": proxy_total / target,
                "opening_prior_share": prior_total / target,
                "registration_reconciliation_factor": factor,
            }
        )

    derived = output / f"{args.scenario.stem}_JRC-IDEES-2005.mif"
    frame.to_csv(derived, sep=";", index=False)
    pd.DataFrame(mapping).to_csv(output / "jrc-remind-2005-mapping.csv", index=False)

    manifest = {
        "schema_version": 1,
        "sources": [
            {
                "source_id": "jrc-idees-2021-road-transport-tdc-2025-04-02",
                "url": JRC_DOWNLOAD_URL,
                "version": "JRC-IDEES-2021 road transport; TDC update 2025-04-02",
                "observation_year": 2005,
                "downloaded_at": "2026-10-27",
                "sha256": sha256_file(archived),
                "license": "CC BY 4.0",
                "adapter_version": "build_remind_jrc_vehicle_stock_run v2",
                "path": str(archived.relative_to(output)),
            }
        ],
    }
    manifest_path = output / "evidence-manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    config["evidence_manifest"] = manifest_path.name
    config_path = output / "stocks-jrc-2005.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    summary = {
        "reference_year": 2005,
        "end_year": args.end_year,
        "jrc_official_dataset": JRC_OFFICIAL_URL,
        "jrc_distribution": JRC_DOWNLOAD_URL,
        "jrc_sha256": sha256_file(archived),
        "iam_source": str(args.scenario.resolve()),
        "iam_source_sha256": sha256_file(args.scenario),
        "derived_scenario": str(derived),
        "derived_scenario_sha256": sha256_file(derived),
        "config": str(config_path),
        "config_sha256": sha256_file(config_path),
        "anchored_regions": sorted(REGIONS),
        "unmodified_regions": ["UKI"],
        "anchored_assets": len(mapping),
        "opening_proxy_assets": len(observation_summary),
        "opening_proxy_details": observation_summary,
        "total_assets": len(config["assets"]),
        "skipped_mappings": skipped,
        "methodological_decision": (
            "JRC changes compatible 2005 stock amounts and provides partial 2000-2005 entry-"
            "cohort proxies from StockNew. Older opening cohorts remain equilibrium priors; "
            "StockNew is not treated as direct surviving-stock evidence. UKI remains unchanged "
            "because the JRC-IDEES-2021 source omits the United Kingdom."
        ),
    }
    (output / "jrc-run-input-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(config_path)
    print(derived)


if __name__ == "__main__":
    main()
