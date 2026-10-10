"""Traceable EIA generation matching and conservative cohort service factors."""

from collections import defaultdict
from io import BytesIO
from zipfile import ZipFile

import numpy as np
from openpyxl import load_workbook

from .stock_history import identifier, number, selection_reason

OBSERVED = {"generator_observed", "single_cohort_observed"}


def _records(workbook, sheet):
    rows = workbook[sheet].iter_rows(values_only=True)
    for row_index, values in enumerate(rows, 1):
        header = [" ".join(str(v).split()) if v is not None else "" for v in values]
        if "Plant Id" in header:
            break
        if row_index >= 12:
            raise ValueError("EIA-923 header not found")
    else:
        raise ValueError("Empty EIA-923 sheet")
    for index, values in enumerate(rows, row_index + 1):
        row = dict(zip(header, values, strict=True))
        plant = row.get("Plant Id")
        if not isinstance(plant, (int, float)):
            continue
        if plant != int(plant):
            raise ValueError("Nonintegral generation plant identity")
        row["source_row"] = index
        yield row


def read_generation(path, year=2022):
    """Read raw annual values; preserve missing/negative/zero as distinct states."""
    with ZipFile(path) as archive:
        names = [n for n in archive.namelist() if "Schedules_2_3_4_5" in n and n.endswith(".xlsx")]
        if len(names) != 1 or str(year) not in names[0]:
            raise ValueError("Ambiguous or wrong-year EIA-923 workbook")
        w = load_workbook(BytesIO(archive.read(names[0])), read_only=True, data_only=True)
    try:
        generators = {}
        for r in _records(w, "Page 4 Generator Data"):
            key = (int(r["Plant Id"]), identifier(r["Generator Id"]))
            monthly = [
                number(r.get("Net Generation " + m))
                for m in (
                    "January February March April May June July August September October "
                    "November December"
                ).split()
            ]
            annual = number(r.get("Net Generation Year To Date"))
            if annual is not None and all(v is not None for v in monthly):
                if not np.isclose(sum(monthly), annual, rtol=1e-7, atol=1):
                    raise ValueError("Monthly generation does not reconcile with annual output")
            item = dict(
                generation=annual,
                monthly=monthly,
                prime_mover=r.get("Reported Prime Mover"),
                chp=r.get("Combined Heat And Power Plant"),
                source_row=r["source_row"],
            )
            if key in generators:
                old = generators[key]
                duplicate_rows = old.get("duplicate_rows", [old.copy()])
                duplicate_rows.append(item)
                generators[key] = dict(
                    generation=None, ambiguous=True, duplicate_rows=duplicate_rows
                )
            else:
                generators[key] = item
        plants, seen = {}, set()
        for r in _records(w, "Page 1 Generation and Fuel Data"):
            key = (
                int(r["Plant Id"]),
                r.get("Reported Prime Mover"),
                r.get("Reported Fuel Type Code"),
            )
            unique = (*key, identifier(r.get("Nuclear Unit Id")))
            duplicate = unique in seen
            seen.add(unique)
            value = number(r.get("Net Generation (Megawatthours)"))
            item = plants.setdefault(
                key,
                dict(
                    generation=0.0, missing=False, source_rows=[], raw_annual_records=[], chp=set()
                ),
            )
            if duplicate:
                item["missing"] = True
                item["ambiguous"] = True
            item["source_rows"].append(r["source_row"])
            item["raw_annual_records"].append(
                dict(source_row=r["source_row"], nuclear_unit=unique[-1], generation=value)
            )
            item["chp"].add(r.get("Combined Heat And Power Plant"))
            if value is None:
                item["missing"] = True
            else:
                item["generation"] += value
        for r in plants.values():
            if r["missing"]:
                r["generation"] = None
            r["chp"] = sorted(str(x) for x in r["chp"])
        return generators, plants
    finally:
        w.close()


def match_ids(stock, generation):
    """Identity only; accept zero padding after a unique one-to-one proof."""

    def alias(key):
        return (key[0], str(int(key[1])) if key[1].isdigit() else key[1])

    source, target = defaultdict(list), defaultdict(list)
    for key in generation:
        source[alias(key)].append(key)
    for r in stock:
        key = (r["plant_id"], r["generator_id"])
        target[alias(key)].append(key)
    result = {}
    for r in stock:
        key = (r["plant_id"], r["generator_id"])
        if key in generation:
            result[key] = (
                (None, "ambiguous_source_identity")
                if generation[key].get("ambiguous")
                else (key, "exact")
            )
        elif source[alias(key)]:
            if len(source[alias(key)]) != 1 or len(target[alias(key)]) != 1:
                result[key] = (None, "ambiguous_alias")
            else:
                candidate = source[alias(key)][0]
                result[key] = (
                    (None, "ambiguous_source_identity")
                    if generation[candidate].get("ambiguous")
                    else (candidate, "numeric_padding_alias")
                )
        else:
            result[key] = (None, "missing_generation")
    # A source may never be consumed through both an exact and alias match.
    used = defaultdict(list)
    for key, (matched, _) in result.items():
        if matched is not None:
            used[matched].append(key)
    for keys in used.values():
        if len(keys) > 1:
            for key in keys:
                result[key] = (None, "ambiguous_alias")
    return result


def audit_service(
    selected,
    all_records,
    previous,
    generators,
    plants,
    mapping,
    asset,
    *,
    year=2022,
    minimum=0.9,
    bin_minimum=0.8,
    material_bin=0.05,
):
    """Return raw matching ledger, completed factors and a coverage decision."""
    before = {(r["plant_id"], r["generator_id"]): r for r in previous}
    selected_keys = {(r["plant_id"], r["generator_id"]) for r in selected}
    matches = match_ids(all_records, generators)
    all_groups = defaultdict(list)
    for r in all_records:
        # Proposed/cancelled assets cannot have annual operating output. Historical
        # retirees are excluded only when their retirement predates this year.
        active = r["status"] in {"OP", "OS", "SB", "OA"} or (
            r["status"] == "RE"
            and (r.get("retirement_year") is None or r["retirement_year"] >= year)
        )
        if active:
            all_groups[(r["plant_id"], r["prime_mover"], r["fuel"])].append(r)
    ledger = {}
    hours = 8784 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 8760

    def eligible(r):
        old = before.get((r["plant_id"], r["generator_id"]))
        return (
            r["cohort"] is not None
            and r["cohort"] < year
            and old is not None
            and selection_reason(old, mapping) == "included"
            and old["cohort"] == r["cohort"]
            and old["capacity"] is not None
            and np.isclose(old["capacity"], r["capacity"], rtol=1e-8)
            and r.get("uprate_derate") != "Y"
        )

    for r in selected:
        key = (r["plant_id"], r["generator_id"])
        matched, reason = matches[key]
        raw = generators.get(matched, {})
        value = raw.get("generation")
        row = dict(
            asset=asset,
            plant_id=key[0],
            generator_id=key[1],
            cohort=r["cohort"],
            capacity=r["capacity"],
            raw_generation=value,
            assigned_generation=None,
            evidence="assumed",
            reason=reason,
            matched_id=matched[1] if matched else None,
            source_row=raw.get("source_row"),
            full_year_eligible=eligible(r),
        )
        if not eligible(r):
            row["reason"] = "partial_year_or_status_capacity_change"
        elif matched is not None:
            if raw["prime_mover"] != r["prime_mover"] or raw["chp"] != "N":
                row["reason"] = "generation_scope_mismatch"
            elif value is None:
                row["reason"] = "missing_generation"
            elif value < 0:
                row["reason"] = "negative_net_generation"
            elif value > r["capacity"] * hours * (1 + 1e-8):
                row["reason"] = "physical_bound"
            else:
                row.update(evidence="generator_observed", assigned_generation=value, reason=reason)
        ledger[key] = row
    reconciliation = []
    for group, members in all_groups.items():
        chosen = [r for r in members if (r["plant_id"], r["generator_id"]) in selected_keys]
        if not chosen:
            continue
        plant = plants.get(group, {})
        total = plant.get("generation")
        entries = [ledger[(r["plant_id"], r["generator_id"])] for r in chosen]
        full_membership = len(chosen) == len(members) and all(eligible(r) for r in members)
        direct = sum(
            r["assigned_generation"] or 0.0
            for r in entries
            if r["evidence"] == "generator_observed"
        )
        residual = None if total is None else total - direct
        issue = "eligible" if full_membership else "incomplete_or_partial_year_membership"
        valid_total = total is not None and total >= 0 and plant.get("chp") == ["N"]
        if valid_total and full_membership and residual < -max(1.0, abs(total) * 1e-6):
            issue = "negative_plant_residual"
            for r in entries:
                r.update(evidence="assumed", assigned_generation=None, reason=issue)
        elif valid_total and full_membership:
            missing = [r for r in entries if r["evidence"] != "generator_observed"]
            eligible_missing = all(r["reason"] == "missing_generation" for r in missing)
            if not missing and abs(residual) > max(1.0, abs(total) * 1e-6):
                issue = "direct_plant_total_conflict"
                for r in entries:
                    r.update(evidence="assumed", assigned_generation=None, reason=issue)
            elif missing and eligible_missing and residual >= 0:
                denom = sum(r["capacity"] for r in missing)
                level = (
                    "single_cohort_observed"
                    if len({r["cohort"] for r in members}) == 1
                    else "plant_allocated"
                )
                if denom <= 0 or residual / denom > hours * (1 + 1e-8):
                    issue = "allocated_physical_bound"
                else:
                    for r in missing:
                        r.update(
                            assigned_generation=residual * r["capacity"] / denom,
                            evidence=level,
                            reason="plant_residual_capacity_allocation",
                            source_row=",".join(map(str, plant["source_rows"])),
                        )
        elif not valid_total:
            issue = "missing_negative_or_incompatible_plant_total"
        assigned = sum(r["assigned_generation"] or 0.0 for r in entries)
        reconciliation.append(
            dict(
                asset=asset,
                plant_id=group[0],
                prime_mover=group[1],
                fuel=group[2],
                reported_generation=total,
                direct_generation=direct,
                assigned_generation=assigned,
                unassigned_generation=None if total is None else total - assigned,
                membership_complete=full_membership,
                issue=issue,
                source_rows=",".join(map(str, plant.get("source_rows", []))),
            )
        )
    rows = list(ledger.values())
    total = sum(r["capacity"] for r in rows)
    known = [r for r in rows if r["evidence"] in OBSERVED]
    usable = [r for r in rows if r["assigned_generation"] is not None]
    if not total:
        raise ValueError("Empty power service population")
    # Allocated values contribute only to a labelled candidate. They never improve
    # the observed-coverage measure used for selecting a default.
    average = (
        sum(r["assigned_generation"] for r in usable) / sum(r["capacity"] for r in usable)
        if usable
        else 0
    )
    if average <= 0:
        average = 1.0
        for r in rows:
            r.update(
                assigned_generation=None,
                evidence="assumed",
                calibration_reason="no_positive_calibration_mean",
            )
        known = []
    cohorts = defaultdict(lambda: [0.0, 0.0])
    bins = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        if r["cohort"] is None:
            raise ValueError("Service factor needs dated stock")
        q = r["capacity"]
        gen = r["assigned_generation"] if r["assigned_generation"] is not None else q * average
        r["completed_generation_proxy"] = gen
        r["relative_factor"] = gen / q / average
        cohorts[r["cohort"]][0] += q
        cohorts[r["cohort"]][1] += gen
        bins[(year - r["cohort"]) // 5][0] += q
        if r["evidence"] in OBSERVED:
            bins[(year - r["cohort"]) // 5][1] += q
    mean = sum(v[1] for v in cohorts.values()) / sum(v[0] for v in cohorts.values())
    factors = [
        dict(cohort=c, amount=q, service_factor=g / q / mean)
        for c, (q, g) in sorted(cohorts.items())
    ]
    coverage = sum(r["capacity"] for r in known) / total
    bin_rows = [
        dict(
            asset=asset,
            age_bin_start=b * 5,
            capacity=q,
            capacity_share=q / total,
            observed_capacity=known_q,
            observed_share=known_q / q,
        )
        for b, (q, known_q) in sorted(bins.items())
    ]
    passed = coverage >= minimum and all(
        r["observed_share"] >= bin_minimum for r in bin_rows if r["capacity_share"] >= material_bin
    )
    by_level = {
        level: sum(r["capacity"] for r in rows if r["evidence"] == level)
        for level in (*sorted(OBSERVED), "plant_allocated", "assumed")
    }
    if not np.isclose(sum(by_level.values()), total):
        raise ValueError("Coverage does not close")
    decision = dict(
        asset=asset,
        selected_capacity=total,
        generator_records=len(rows),
        observed_capacity_share=coverage,
        coverage_passed=passed,
        capacity_by_level=by_level,
        age_bins=bin_rows,
        default_eligible_by_coverage=passed,
        future_factor=1.0,
        physical_check_pending=True,
        factor_interpretation="2022 cross-sectional output/capacity; not a causal age law",
        observation_geography="USA",
        predictive_service_validation="unavailable_one_generation_year",
    )
    return rows, reconciliation, factors, decision
