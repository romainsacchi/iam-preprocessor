"""Reproduce the frozen REMIND evidence campaign; private data stays outside Git.

Historical predictions use opening cohorts plus declared drivers only. The scorer
receives closing composition afterwards. No lifetime parameters are fitted here.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from validate_stock_output import validate

from iam_preprocessor.exceptions import DataValidationError
from iam_preprocessor.io import read_frame, sha256_file
from iam_preprocessor.stock_config import load_stock_config
from iam_preprocessor.stock_history import (
    read_snapshot,
    registry,
    select_snapshot,
    summarize,
    transition_ledger,
)
from iam_preprocessor.stock_observations import curate_vehicle_history
from iam_preprocessor.stock_service import audit_service, read_generation
from iam_preprocessor.stock_validation import conditional_history, opening_survival, score_cohorts
from iam_preprocessor.stock_vintages import _asset_result, _series, prepare_stock_vintages


def save(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def csv(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False)


def verify_manifest(path):
    manifest = json.loads(path.read_text())
    files = {}
    for role, item in manifest["files"].items():
        source = path.parent / item["file"]
        if sha256_file(source) != item["sha256"]:
            raise ValueError(f"Frozen input changed: {role}")
        files[role] = source
    return files


def naei_profiles(pdf, output):
    """Extract the published 2019 New Fleet and HGV columns, preserving age order."""
    if sha256_file(pdf) != "facb7aa1690a2ab40328243797f6790ed85f1526e79d601f5a0def4cf8c08706":
        raise ValueError("Supplemental NAEI source hash mismatch")
    content = subprocess.check_output(
        ["pdftotext", "-f", "42", "-l", "46", "-layout", str(pdf), "-"], text=True
    )
    a, b = content.split(
        "Table 5-3 Relative mileage with age indices for Petrol LGVs, HGVs and buses"
    )
    numeric = r"([\d.]+|N/A)"

    def rows(section, columns):
        result = []
        for line in section.splitlines():
            match = re.search(
                r"(?:^|\s)(\d{1,2})\s+" + r"\s+".join([numeric] * columns) + r"\s*$", line
            )
            if match:
                result.append((int(match[1]), float(match[4])))
        return result

    cars, trucks = rows(a, 4), rows(b, 6)
    if len(cars) != 100 or len(trucks) != 25:
        raise ValueError("NAEI table extraction count mismatch")
    profiles = dict(petrol=cars[:25], diesel=cars[25:50], trucks=trucks)
    paths = {}
    for name, values in profiles.items():
        if [x[0] for x in values] != list(range(25)):
            raise ValueError("NAEI age ordering mismatch")
        paths[name] = output / f"naei-{name}-age-usage.csv"
        pd.DataFrame(values, columns=["age", "factor"]).to_csv(paths[name], index=False)
    save(
        output / "vehicle-usage-assessment.json",
        dict(
            source_url="https://naei.energysecurity.gov.uk/sites/default/files/2025-03/4_NAEI_Improvement_Report_Road_Transport_Fleet_Turnover_Model_Development.pdf",
            source_sha256=sha256_file(pdf),
            tables=["5-2: 2019 New Fleet petrol/diesel", "5-3: HGV New Fleet"],
            evidence=(
                "MOT 2007–2019 and NTS for cars; CSRGT-based HGV profile; "
                "published 2025, not 2025 observations"
            ),
            curves={name: dict(file=str(p), sha256=sha256_file(p)) for name, p in paths.items()},
            decision="sensitivities only; equal service retained for all vehicle defaults",
            limitations=[
                "UK proxy for EUR; HGV proxy for 40t trucks",
                "Constant occupancy/payload across age assumed",
                "Hold age-24 factor at all older ages",
                "One historical period does not identify future usage",
                "No eligible BEV age curve found",
                (
                    "Petrol/diesel curves applied to combined Liquids separately; not "
                    "separate IAM fleets"
                ),
            ],
            alternative_sources=[
                dict(
                    source="NTS0903/NTS0904",
                    url="https://www.gov.uk/government/statistical-data-sets/nts09-vehicle-mileage-and-occupancy",
                    decision=(
                        "Mileage and occupancy marginals do not identify joint fuel-by-age service"
                    ),
                ),
                dict(
                    source="DfT road freight tables",
                    url="https://www.gov.uk/government/statistical-data-sets/domestic-road-freight-activity-rfs01",
                    decision="Activity aggregates do not identify joint age/payload profile",
                ),
                dict(
                    source="MOT bulk API",
                    url="https://documentation.history.mot.api.gov.uk/mot-history-api/download-vehicle-mot-history-data",
                    decision=(
                        "No authorized bulk credential in campaign; young cars and heavy "
                        "vehicle coverage incomplete; no access request made"
                    ),
                ),
            ],
        ),
    )
    return paths


def historical_tests(history, panels, mappings, output, campaign):
    metrics, predictions, inputs, transitions, exclusions = [], [], [], [], []
    for asset, m in mappings.items():
        power = m["kind"] == "power"
        available = sorted(y for a, y in history if a == asset)
        refs = [2020] if power else campaign["vehicle_initial_years"]
        for ref in refs:
            end = min(2022 if power else (2025 if ref == 2022 else 2022), max(available))
            opening = history[asset, ref]
            initial = opening["cohorts"]
            totals = {y: sum(history[asset, y]["cohorts"].values()) for y in range(ref, end + 1)}
            # The prediction function never receives the later cohort vectors.
            for method in ("prior", "no-retirement", "equilibrium"):
                predicted = conditional_history(
                    initial, ref, totals, m["mean_life"], m["shape"], method=method
                )
                inputs.append(
                    dict(
                        asset=asset,
                        experiment="C",
                        reference_year=ref,
                        method=method,
                        fields=["initial_cohorts", "lifetime_prior", "closing_totals"],
                        totals=totals,
                        later_cohort_composition_supplied=False,
                    )
                )
                for y in range(ref + 1, end + 1):
                    actual = history[asset, y]
                    split = (
                        "frozen_test"
                        if ref == 2022
                        else "retrospective_holdout"
                        if y == 2022
                        else "development"
                    )
                    metric = score_cohorts(
                        predicted[y],
                        actual["cohorts"],
                        y,
                        total_is_input=True,
                        tail_age=40 if power else 20,
                    )
                    metrics.append(
                        dict(
                            asset=asset,
                            experiment="C",
                            method=method,
                            reference_year=ref,
                            year=y,
                            split=split,
                            observed_unknown=actual["unknown"],
                            observed_total=actual["total"],
                            dated_coverage=1 - actual["unknown"] / actual["total"],
                            **metric,
                        )
                    )
                    if method == "prior":
                        for c in sorted(set(predicted[y]) | set(actual["cohorts"])):
                            predictions.append(
                                dict(
                                    asset=asset,
                                    reference_year=ref,
                                    year=y,
                                    cohort=c,
                                    predicted=predicted[y].get(c, 0),
                                    observed=actual["cohorts"].get(c, 0),
                                )
                            )
            for y in range(ref + 1, end + 1):
                if power:
                    ledger = transition_ledger(panels[ref], panels[y], m, asset)
                    transitions.extend(ledger)
                    allowed = {"continuing", "capacity_change", "reported_retirement"}
                    known = [
                        r
                        for r in ledger
                        if r["opening_capacity"] > 0
                        and r["event"] in allowed
                        and r["opening_cohort"] is not None
                    ]
                    a, b = defaultdict(float), defaultdict(float)
                    for row in known:
                        c = row["opening_cohort"]
                        a[c] += row["opening_capacity"]
                        if row["event"] != "reported_retirement":
                            b[c] += row["opening_capacity"]
                    excluded = sum(r["opening_capacity"] for r in ledger if r not in known)
                    exclusions.append(
                        dict(
                            asset=asset,
                            reference_year=ref,
                            year=y,
                            excluded_opening_capacity=excluded,
                            reasons=dict(
                                Counter(
                                    r["event"]
                                    for r in ledger
                                    if r["opening_capacity"] and r not in known
                                )
                            ),
                        )
                    )
                    label = (
                        "confirmed operating retention in opening-capacity units; "
                        "unresolved identities excluded"
                    )
                else:
                    a = initial
                    b = {c: q for c, q in history[asset, y]["cohorts"].items() if c <= ref}
                    excluded = opening["unknown"]
                    label = (
                        "net licensed cohort retention; imports/reactivation not separable "
                        "from retirement"
                    )
                for method in ("prior", "no-retirement"):
                    prediction = opening_survival(
                        a, ref, y, m["mean_life"], m["shape"], method=method
                    )
                    metrics.append(
                        dict(
                            asset=asset,
                            experiment="A",
                            method=method,
                            reference_year=ref,
                            year=y,
                            split="frozen_test"
                            if ref == 2022
                            else "retrospective_holdout"
                            if y == 2022
                            else "development",
                            interpretation=label,
                            excluded_opening_stock=excluded,
                            dated_coverage=sum(a.values()) / opening["total"],
                            **score_cohorts(
                                prediction, b, y, total_is_input=False, tail_age=40 if power else 20
                            ),
                        )
                    )
    csv(output / "historical-metrics.csv", metrics)
    csv(output / "historical-predictions.csv", predictions)
    csv(output / "power-transition-ledger.csv", transitions)
    save(output / "historical-input-contracts.json", inputs)
    save(output / "historical-exclusions.json", exclusions)
    save(
        output / "historical-experiment-b.json",
        dict(
            status="unsupported for this campaign",
            reason=(
                "No independently verified gross additions series aligned with "
                "each observed-stock boundary. Youngest closing-stock cohorts are "
                "not sales. EIA new entries include coverage and category changes."
            ),
            lifetime_parameters_fitted=False,
            cohort_composition_holdout_used_for_tuning=False,
        ),
    )
    return metrics


def audit_sources(files, output, campaign):
    mappings = registry()
    frame = read_frame(files["scenario"])
    panels = {y: read_snapshot(files[f"eia860{y}.zip"], y) for y in (2020, 2021, 2022)}
    for y, panel in panels.items():
        save(output / f"eia-{y}-records.json", panel)
    history = curate_vehicle_history(files["veh1111.ods"])
    comparisons, boundaries, selections = [], [], []
    for asset, m in mappings.items():
        series = _series(frame, m["region"], m["stock"])
        for y in (2020, 2021, 2022):
            if m["kind"] == "power":
                selected, ledger = select_snapshot(panels[y], m)
                selections.extend(dict(asset=asset, **r) for r in ledger)
                history[asset, y] = summarize(selected)
                alternatives = [
                    ("OP_nonCHP", {}),
                    ("all_operable", {"statuses": ("OP", "SB", "OS", "OA")}),
                    ("including_CHP", {"allow_chp": True}),
                ]
                if asset in ("pv", "ccgt"):
                    alternatives.append(("WECC", {"geography": "WECC"}))
                for label, opts in alternatives:
                    rows, _ = select_snapshot(panels[y], m, **opts)
                    for rating in ("capacity", "summer_capacity", "winter_capacity"):
                        boundaries.append(
                            dict(
                                asset=asset,
                                year=y,
                                boundary=label,
                                rating=rating,
                                reported_MW=sum(r[rating] for r in rows if r[rating] is not None),
                                missing_rating_records=sum(r[rating] is None for r in rows),
                                records=len(rows),
                            )
                        )
            observed = history[asset, y]
            iam = float(np.interp(y, list(series), list(series.values())))
            obs = observed["total"] / (1000 if m["kind"] == "power" else 1e6)
            comparisons.append(
                dict(
                    asset=asset,
                    year=y,
                    native_anchor=y in series,
                    iam_stock=iam,
                    observed_stock=obs,
                    ratio_iam_to_observed=iam / obs,
                    source_geography=m["source_geography"],
                    iam_region=m["region"],
                    comparable_total=False,
                    interpretation=m["boundary_note"],
                    unknown_observed=observed["unknown"],
                    source_records=observed.get("generator_records"),
                    cohort_date_kind=m["cohort_date_kind"],
                )
            )
    csv(output / "stock-comparison.csv", comparisons)
    csv(output / "boundary-alternatives.csv", boundaries)
    csv(output / "power-selection-ledger.csv", selections)
    save(
        output / "observed-cohort-history.json",
        [dict(asset=a, year=y, **v) for (a, y), v in history.items()],
    )
    (output / "stock-asset-mappings.yaml").write_text(
        yaml.safe_dump(dict(schema_version=1, assets=mappings), sort_keys=False)
    )
    metrics = historical_tests(history, panels, mappings, output, campaign)
    generators, plants = read_generation(files["f923_2022.zip"])
    save(
        output / "generation-identity-audit.json",
        dict(
            ambiguous_generators=[
                dict(plant_id=k[0], generator_id=k[1], **v)
                for k, v in generators.items()
                if v.get("ambiguous")
            ],
            ambiguous_plant_groups=[
                dict(plant_id=k[0], prime_mover=k[1], fuel=k[2], **v)
                for k, v in plants.items()
                if v.get("ambiguous")
            ],
        ),
    )
    service, decisions, reconciliation, bins = [], [], [], []
    for asset, m in mappings.items():
        if m["kind"] != "power":
            continue
        selected, _ = select_snapshot(panels[2022], m)
        rows, rec, factors, decision = audit_service(
            selected,
            panels[2022],
            panels[2021],
            generators,
            plants,
            m,
            asset,
            minimum=campaign["service_coverage_min"],
            bin_minimum=campaign["service_bin_coverage_min"],
            material_bin=campaign["material_bin_share"],
        )
        csv(output / f"{asset}-generation-factors.csv", factors)
        service.extend(rows)
        decisions.append(decision)
        reconciliation.extend(rec)
        bins.extend(decision["age_bins"])
    csv(output / "generation-match-ledger.csv", service)
    csv(output / "generation-reconciliation.csv", reconciliation)
    csv(output / "generation-coverage-by-age.csv", bins)
    save(output / "service-decisions.json", decisions)
    return mappings, metrics, decisions


def configure(files, baseline, output, decisions, curves):
    config = load_stock_config(baseline / "remind-npi2025-stock-config.yaml")
    # Copy every original input, keeping all 93 existing sensitivity cases reproducible.
    copied = {}
    for asset in config["assets"]:
        if asset["initial"]["kind"] == "observed_shares":
            old = Path(asset["initial"]["file"])
            dest = output / old.name
            if dest.name in copied and copied[dest.name] != old:
                raise ValueError("Observation basename collision")
            dest.write_bytes(old.read_bytes())
            copied[dest.name] = old
            asset["initial"]["file"] = str(dest)
    primary = {a["id"]: a for a in config["assets"] if a["id"] in registry()}
    frame = read_frame(files["scenario"])
    candidates = []
    for d in decisions:
        name = d["asset"]
        case = deepcopy(primary[name])
        case["id"] = name + "-generation-service"
        observed = pd.read_csv(case["initial"]["file"])
        f = pd.read_csv(output / f"{name}-generation-factors.csv").set_index("cohort")
        # Keep the pilot's original initial-stock quantities, including WECC PV/CCGT.
        observed["service_factor"] = observed.cohort.map(f.service_factor).fillna(1.0)
        dest = output / f"{name}-service-candidate-initial.csv"
        observed.to_csv(dest, index=False)
        case["initial"]["file"] = str(dest)
        case["service_weighting"].update(
            kind="observed_factors",
            annual_age_decay=0,
            future_factor=1,
            provenance=(
                "EIA-923 2022 cross-sectional generation/capacity; allocated or "
                "missing output explicitly labelled; future cohorts factor 1. See "
                "service-decisions.json."
            ),
        )
        if name in ("pv", "ccgt"):
            d["baseline_geography_proxy"] = (
                "National factors on unchanged selected-WECC cohort amounts"
            )
            d["default_eligible_by_coverage"] = False
        try:
            _asset_result(frame, case, config["reference_year"], config["end_year"])
        except DataValidationError as exc:
            d.update(
                physical_check_pending=False,
                physical_check_passed=False,
                physical_failure=str(exc),
                decision="retain_default_candidate_rejected",
            )
        else:
            d.update(
                physical_check_pending=False,
                physical_check_passed=True,
                decision="promote_generation_service"
                if d["default_eligible_by_coverage"]
                else "retain_default_export_sensitivity",
            )
            if d["default_eligible_by_coverage"]:
                old = deepcopy(primary[name])
                old["id"] = name + "-previous-service"
                candidates.append(old)
                case["id"] = name
                config["assets"][config["assets"].index(primary[name])] = case
            else:
                candidates.append(case)
    for name in ("passenger-bev", "passenger-liquids", "heavy-trucks"):
        case = deepcopy(primary[name])
        case["id"] = name + "-absolute-age-decay"
        # A fully specified annual-age curve avoids treating all initial cohorts as age zero.
        dest = output / f"{name}-decay-profile.csv"
        pd.DataFrame({"age": range(151), "factor": np.exp(-0.03 * np.arange(151))}).to_csv(
            dest, index=False
        )
        case["service_weighting"] = dict(
            kind="age_profile",
            annual_age_decay=0,
            age_profile_file=str(dest),
            tail_policy="hold_last",
            provenance=(
                "Assumed exp(-0.03*absolute_age) sensitivity; hold age-150 tail; "
                "no empirical claim."
            ),
        )
        candidates.append(case)
    for fuel, name in [
        ("petrol", "passenger-liquids"),
        ("diesel", "passenger-liquids"),
        ("trucks", "heavy-trucks"),
    ]:
        case = deepcopy(primary[name])
        case["id"] = name + "-naei-" + fuel
        case["service_weighting"] = dict(
            kind="age_profile",
            annual_age_decay=0,
            age_profile_file=str(curves[fuel]),
            tail_policy="hold_last",
            provenance=(
                "NAEI Tables 5-2/5-3 historical UK relative mileage. Constant "
                "occupancy/payload by age and time assumed; hold last factor "
                "beyond age 24. Combined Liquids sensitivity only."
            ),
        )
        candidates.append(case)
    config["assets"].extend(candidates)
    dest = output / "remind-npi2025-stock-config.yaml"
    dest.write_text(yaml.safe_dump(config, sort_keys=False))
    save(output / "service-decisions.json", decisions)
    save(
        output / "sector-observation-audit.json",
        dict(primary_assets=list(registry()), evidence_campaign=True),
    )
    return dest


def compare_baseline(files, report, output):
    old = read_frame(files["baseline_output"])
    new = read_frame(report.output_path)
    keys = ["Model", "Scenario", "Region", "Variable", "Unit"]
    a = old.set_index(keys)
    b = new.set_index(keys)
    columns = [c for c in a if c.isdigit()]
    # Every old stock, flow and total service remains identical; only cohort service
    # weights for explicitly promoted primary defaults can change.
    decisions = json.loads((output / "service-decisions.json").read_text())
    promotions = [d["asset"] for d in decisions if d["decision"] == "promote_generation_service"]
    variables = a.index.get_level_values("Variable")
    allowed = np.zeros(len(a), dtype=bool)
    for asset in promotions:
        for family in ("Service", "Service Share"):
            allowed |= variables.str.startswith(f"Stock Vintage|v1|{asset}|{family}|Vintage|")
    ids = a.index[~allowed]
    np.testing.assert_allclose(
        a.loc[ids, columns], b.loc[ids, columns], rtol=1e-12, atol=1e-12, equal_nan=True
    )
    save(
        output / "baseline-invariance.json",
        dict(
            passed=True,
            rows_checked=len(ids),
            values_checked=len(ids) * len(columns),
            rule=(
                "Native scenario rows, all existing stock distributions/flows and "
                "total service unchanged. Cohort service is allowed to change only "
                "for declared promotions."
            ),
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--naei-pdf", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    files = verify_manifest(args.manifest)
    campaign = yaml.safe_load(files["campaign"].read_text())
    curves = naei_profiles(args.naei_pdf, out)
    _, _, decisions = audit_sources(files, out, campaign)
    baseline_report = json.loads(files["baseline_report"].read_text())
    if (
        sha256_file(args.baseline / "remind-npi2025-stock-config.yaml")
        != baseline_report["assumptions"]["config_sha256"]
    ):
        raise ValueError("Baseline configuration changed")
    config = configure(files, args.baseline, out, decisions, curves)
    report = prepare_stock_vintages(files["scenario"], out, config, overwrite=True)
    validate(out / (Path(report.output_path).stem + "_report.json"))
    compare_baseline(files, report, out)
    save(
        out / "campaign-provenance.json",
        dict(
            manifest=str(args.manifest),
            manifest_sha256=sha256_file(args.manifest),
            protocol_sha256=sha256_file(files["protocol"]),
            campaign_sha256=sha256_file(files["campaign"]),
            baseline_config_sha256=sha256_file(args.baseline / "remind-npi2025-stock-config.yaml"),
            implementation={
                p.name: sha256_file(p)
                for p in [Path(__file__), *Path("src/iam_preprocessor").glob("stock_*.py")]
            },
            naei_pdf_sha256=sha256_file(args.naei_pdf),
            output_sha256=report.output_sha256,
        ),
    )
    print(json.dumps(dict(output=report.output_path, cases=len(report.assumptions["assets"]))))


if __name__ == "__main__":
    main()
