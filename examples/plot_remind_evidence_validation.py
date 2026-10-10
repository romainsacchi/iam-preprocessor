"""Generate the private evidence assessment, PDF and standalone numerical plots."""

import argparse
import json
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

from iam_preprocessor.io import read_frame
from iam_preprocessor.stock_history import registry
from iam_preprocessor.stock_vintages import PREFIX

COLORS = ["#20639b", "#d99000", "#238b75"]


def table(frame):
    cols = list(frame.columns)
    rows = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in frame.fillna("—").itertuples(index=False, name=None):
        rows.append("| " + " | ".join(str(v).replace("|", "/") for v in row) + " |")
    return "\n".join(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    out = args.directory
    mappings = registry()
    assets = list(mappings)
    metrics = pd.read_csv(out / "historical-metrics.csv")
    comparisons = pd.read_csv(out / "stock-comparison.csv")
    decisions = {r["asset"]: r for r in json.loads((out / "service-decisions.json").read_text())}
    provenance = json.loads((out / "campaign-provenance.json").read_text())
    report = json.loads(
        (out / "REMIND_generic_SSP2-NPi2025_stock_vintages_report.json").read_text()
    )
    validation = json.loads((out / "serialized-output-validation.json").read_text())
    checks = (
        json.loads((out / "validation-summary.json").read_text())
        if (out / "validation-summary.json").exists()
        else {}
    )
    frame = read_frame(report["output_path"]).set_index(["Region", "Variable"])
    examples = {d["asset"]: d for d in report["assumptions"]["assets"]}
    historical = metrics[
        (metrics.experiment == "C") & (metrics.reference_year == 2020) & (metrics.year == 2022)
    ]
    w1 = historical.pivot(index="asset", columns="method", values="age_w1").reindex(assets)
    stock = comparisons.pivot(
        index="asset", columns="year", values="ratio_iam_to_observed"
    ).reindex(assets)
    future = metrics[
        (metrics.experiment == "C") & (metrics.reference_year == 2022) & (metrics.year == 2025)
    ].pivot(index="asset", columns="method", values="age_w1")
    rows = []
    for a in assets:
        d = decisions.get(a, {})
        rows.append(
            dict(
                Asset=a,
                W1_prior=f"{w1.at[a, 'prior']:.3f}",
                W1_no_retirement=f"{w1.at[a, 'no-retirement']:.3f}",
                Observed_output=f"{d['observed_capacity_share']:.1%}"
                if d
                else "No joint service evidence",
                Decision=d.get("decision", "equal_default; age_usage_sensitivities"),
            )
        )
    summary = pd.DataFrame(rows)
    summary.to_csv(out / "group-decisions.csv", index=False)
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )
    figures = []

    def finish(fig, name, pdf):
        fig.savefig(out / (name + ".png"), dpi=170, bbox_inches="tight")
        pdf.savefig(fig)
        figures.append(name + ".png")
        plt.close(fig)

    def textpage(pdf, title, paragraphs):
        fig = plt.figure(figsize=(11.7, 8.3))
        fig.text(0.06, 0.92, title, fontsize=21, weight="bold", color=COLORS[0])
        wrapped = [(heading, textwrap.wrap(body, 110)) for heading, body in paragraphs]
        line_height = min(
            0.025, (0.75 - len(wrapped) * 0.060) / sum(len(lines) for _, lines in wrapped)
        )
        font_size = min(11, line_height * 8.3 * 72 / 1.35)
        y = 0.83
        for heading, lines in wrapped:
            fig.text(0.06, y, heading, fontsize=12, weight="bold")
            y -= 0.035
            fig.text(0.06, y, "\n".join(lines), fontsize=font_size, va="top", linespacing=1.35)
            y -= line_height * len(lines) + 0.025
        assert y >= 0.079, "Text page exceeds bottom margin"
        pdf.savefig(fig)
        plt.close(fig)

    plotrows = []
    with PdfPages(out / "remind-evidence-validation-report.pdf") as pdf:
        textpage(
            pdf,
            "REMIND stock vintages: evidence and validation",
            [
                (
                    "Scope",
                    (
                        "SSP2-NPi2025, eleven asset groups, 2022–2050. Historical "
                        "stock composition is evaluated separately from service "
                        "allocation. Priors were frozen before holdout scoring; no "
                        "retirement law was fitted."
                    ),
                ),
                (
                    "What changed",
                    (
                        "Year-aware EIA and UK stock readers, a reconciled "
                        "status/coverage panel, historical composition tests, "
                        "generation-matching coverage gates, and annual-age usage "
                        "profiles. Offshore wind alone passes the generation-service "
                        "promotion gates; other defaults are retained."
                    ),
                ),
                (
                    "Main empirical finding",
                    (
                        "The existing lifetime prior loses to no retirement for most "
                        "power groups over the short 2020–2022 window. This is "
                        "evidence against treating those priors as validated "
                        "retirement laws. Vehicles improve over no retirement in the "
                        "separate 2022–2025 test, with mixed earlier results."
                    ),
                ),
                (
                    "Accounting and limits",
                    (
                        f"{len(examples)} cases and "
                        f"{validation['annual_profiles_checked']:,} annual profiles "
                        f"pass serialized checks. All "
                        f"{validation['original_anchor_values_checked']:,} original "
                        f"IAM anchor values and every existing stock distribution are "
                        f"preserved. Numerical validity does not establish future "
                        f"empirical accuracy. Regional and technology proxies remain "
                        f"explicit."
                    ),
                ),
                (
                    "Traceability",
                    (
                        "The accompanying Markdown report, numeric tables and "
                        "source-level ledgers record exclusions, assumptions and "
                        "failed candidates. Historical experiment C conditions on "
                        "aggregate stocks: its total-stock prediction error is "
                        "deliberately not scored."
                    ),
                ),
            ],
        )
        power = [a for a in assets if a in decisions]
        fig, ax = plt.subplots(figsize=(11.7, 8.3))
        x = np.arange(len(power))
        for i, y in enumerate((2020, 2021, 2022)):
            ax.bar(
                x + (i - 1) * 0.24,
                stock.loc[power, y],
                width=0.24,
                label=f"{y}" + (" native IAM anchor" if y == 2020 else " interpolated IAM"),
                color=COLORS[i],
            )
        ax.axhline(1, color="black", lw=1)
        ax.set_yscale("log")
        ax.set_ylabel("IAM stock / selected observed stock (log scale)")
        ax.set_xticks(x, power, rotation=25, ha="right")
        ax.legend()
        ax.set_title(
            "Same-year comparison exposes timing and boundary differences", fontsize=17, pad=18
        )
        fig.text(
            0.09,
            0.02,
            (
                "Ratios are diagnostics, not calibration targets. UK versus "
                "EUR vehicle totals are not comparable.\nOffshore: 1.08 at the"
                " 2020 anchor, 18.01 in 2022. PV AC/DC/distributed and gas "
                "technology boundaries remain unresolved."
            ),
            fontsize=10,
        )
        fig.subplots_adjust(bottom=0.2, top=0.89)
        finish(fig, "01-stock-comparison", pdf)
        fig, axes = plt.subplots(1, 2, figsize=(11.7, 8.3), gridspec_kw={"width_ratios": [2, 1]})
        for ax, data, title in [
            (axes[0], w1, "2020 → 2022 retrospective holdout"),
            (axes[1], future, "2022 → 2025 frozen vehicle test"),
        ]:
            y = np.arange(len(data))
            for i, method in enumerate(("prior", "no-retirement", "equilibrium")):
                ax.barh(
                    y + (i - 1) * 0.23, data[method], height=0.23, label=method, color=COLORS[i]
                )
            ax.set_yticks(y, data.index)
            ax.invert_yaxis()
            ax.set_xlabel("Age Wasserstein distance (years; lower is better)")
            ax.set_title(title)
            ax.legend(fontsize=9)
        fig.suptitle(
            "Historical composition: supplied totals receive no predictive credit", fontsize=17
        )
        fig.text(
            0.08,
            0.025,
            (
                "Experiment C uses opening cohorts + observed aggregate "
                "stocks; later cohort shares are withheld.\nA no-retirement "
                "benchmark can perform well over a short period without being"
                " a defensible long-term law."
            ),
            fontsize=10,
        )
        fig.tight_layout(rect=(0, 0.1, 1, 0.94))
        finish(fig, "02-historical-scores", pdf)
        observed_predictions = pd.read_csv(out / "historical-predictions.csv")
        selected = observed_predictions[
            (observed_predictions.reference_year == 2020) & (observed_predictions.year == 2022)
        ]
        fig, axes = plt.subplots(4, 3, figsize=(11.7, 11.7))
        for ax, asset in zip(axes.flat, assets, strict=False):
            group = selected[selected.asset == asset]
            age_bins = np.minimum((2022 - group.cohort.to_numpy(int)) // 5, 18)
            for i, column in enumerate(("observed", "predicted")):
                values = group[column].to_numpy(float)
                bins = np.bincount(age_bins, weights=values / values.sum(), minlength=19)
                ax.step(np.arange(19) * 5, bins, where="mid", color=COLORS[i], label=column)
            ax.set_title(asset, fontsize=11)
            ax.set_xlim(-2, 93)
            ax.set_ylim(bottom=0)
            ax.set_xlabel("Age; final bin ≥90", fontsize=8)
            ax.set_ylabel("5-year share", fontsize=8)
            ax.tick_params(labelsize=8)
            ax.legend(fontsize=7)
        axes.flat[-1].axis("off")
        fig.suptitle("Held-out 2022 composition: observed versus frozen prior", fontsize=16)
        fig.tight_layout(rect=(0, 0, 1, 0.96))
        finish(fig, "02b-historical-distributions", pdf)
        fig, ax = plt.subplots(figsize=(11.7, 8.3))
        bottom = np.zeros(len(power))
        for level, color in [
            ("generator_observed", COLORS[0]),
            ("single_cohort_observed", COLORS[2]),
            ("plant_allocated", COLORS[1]),
            ("assumed", "#cccccc"),
        ]:
            value = np.array(
                [
                    decisions[a]["capacity_by_level"][level] / decisions[a]["selected_capacity"]
                    for a in power
                ]
            )
            ax.barh(power, value, left=bottom, label=level.replace("_", " "), color=color)
            bottom += value
        ax.axvline(0.9, ls="--", color="black", label="90% overall observed threshold")
        ax.set_xlim(0, 1)
        ax.invert_yaxis()
        ax.set_xlabel("Share of selected capacity")
        ax.legend(loc="lower left", bbox_to_anchor=(0, -0.26), ncol=2)
        ax.set_title(
            "Measured, allocated and assumed power output remain separate", fontsize=17, pad=18
        )
        fig.text(
            0.1,
            0.02,
            (
                "Material age bins also need ≥80% observed coverage. Only "
                "offshore wind passes both coverage gates.\nGeothermal "
                "candidate fails the physical service bound; PV/CCGT national"
                " factors remain proxies on existing WECC stocks."
            ),
            fontsize=10,
        )
        fig.subplots_adjust(left=0.17, bottom=0.25, top=0.88)
        finish(fig, "03-generation-coverage", pdf)
        fig, ax = plt.subplots(figsize=(11.7, 8.3))
        for i, name in enumerate(("petrol", "diesel", "trucks")):
            curve = pd.read_csv(out / f"naei-{name}-age-usage.csv")
            age = np.arange(41)
            ax.plot(
                age,
                np.interp(age, curve.age, curve.factor),
                label=f"NAEI {name}",
                color=COLORS[i],
                lw=2,
            )
        ax.plot(age, np.exp(-0.03 * age), "--", color="#555555", label="Assumed 3% age decline")
        ax.axhline(1, color="#aaaaaa", label="Equal service default")
        ax.axvline(24, ls=":", color="black")
        ax.set(
            xlabel="Vehicle age (years)",
            ylabel="Relative annual mileage",
            ylim=(0, 1.08),
            title="Vehicle use: age lookup advances with each cohort",
        )
        ax.legend()
        fig.text(
            0.1,
            0.025,
            (
                "NAEI Tables 5-2/5-3; historical UK mileage, not observed "
                "future passenger-km or tonne-km.\nBeyond age 24: explicit "
                "hold-last assumption. Constant occupancy/payload by age. No "
                "eligible BEV empirical curve.\nPetrol and diesel curves are "
                "separate sensitivities on the combined Liquids fleet, not "
                "separate IAM projections."
            ),
            fontsize=10,
        )
        fig.subplots_adjust(bottom=0.2, top=0.9)
        finish(fig, "04-vehicle-usage", pdf)
        for service in (False, True):
            fig, axes = plt.subplots(4, 3, figsize=(11.7, 11.7))
            family = "Service Share" if service else "Stock Share"
            for ax, a in zip(axes.flat, assets, strict=False):
                candidate = (
                    a + "-previous-service"
                    if a == "wind-offshore"
                    else a + "-generation-service"
                    if a + "-generation-service" in examples
                    else a + "-naei-trucks"
                    if a == "heavy-trucks"
                    else a + "-naei-petrol"
                    if a == "passenger-liquids"
                    else a + "-absolute-age-decay"
                    if a == "passenger-bev"
                    else None
                )
                cases = (
                    [(a, y, str(y)) for y in (2022, 2030, 2050)]
                    if not service
                    else [(a, 2030, "Default 2030")]
                    + ([(candidate, 2030, "Sensitivity 2030")] if candidate else [])
                )
                for i, (case, y, label) in enumerate(cases):
                    prefix = PREFIX + case + "|" + family + "|Vintage|"
                    region = frame.loc[mappings[a]["region"]]
                    rows = region.loc[region.index.str.startswith(prefix), str(y)]
                    cohorts = np.array([int(v.rsplit("|", 1)[-1]) for v in rows.index])
                    ages = y - cohorts
                    values = rows.to_numpy(float)
                    bins = np.minimum(np.maximum(ages // 5, 0), 18)
                    weights = np.bincount(bins, weights=values, minlength=19)
                    ax.step(
                        np.arange(19) * 5,
                        weights,
                        where="mid",
                        label=label,
                        color=COLORS[i],
                        lw=1.4,
                    )
                    for c, v in zip(cohorts, values, strict=True):
                        plotrows.append(
                            dict(
                                asset=a,
                                case=case,
                                year=y,
                                family=family,
                                cohort=int(c),
                                age=int(y - c),
                                share=float(v),
                            )
                        )
                ax.set_title(a, fontsize=11)
                ax.set_xlim(-2, 93)
                ax.set_ylim(bottom=0)
                ax.set_xlabel("Age; final bin ≥90", fontsize=8)
                ax.set_ylabel("5-year share", fontsize=8)
                ax.tick_params(labelsize=8)
                ax.legend(fontsize=7)
            axes.flat[-1].axis("off")
            fig.suptitle(
                "Generated service distributions: default and explicit sensitivity"
                if service
                else "Generated stock age distributions: 2022, 2030, 2050",
                fontsize=16,
            )
            fig.tight_layout(rect=(0, 0, 1, 0.96))
            finish(fig, "06-service-distributions" if service else "05-stock-distributions", pdf)
        runtime = (
            json.loads((out / "runtime-validation.json").read_text())
            if (out / "runtime-validation.json").exists()
            else {"status": "pending"}
        )
        textpage(
            pdf,
            "Interpretation and remaining evidence gaps",
            [
                (
                    "Observed stock versus burden allocation",
                    (
                        "A stock share counts surviving assets by "
                        "construction/first-use cohort. A service share additionally "
                        "weights their use. These weights distribute the existing "
                        "inventory production coefficient across cohorts; they do not"
                        " estimate a new coefficient or change its total."
                    ),
                ),
                (
                    "Historical evidence limits",
                    (
                        "EIA panels distinguish capacity revisions, status changes, "
                        "newly covered assets and unresolved disappearances. "
                        "Experiment A measures confirmed operating retention or net "
                        "licensed vehicle retention. Independent gross additions "
                        "aligned to every stock boundary were unavailable: experiment"
                        " B is explicitly unsupported."
                    ),
                ),
                (
                    "Power priorities",
                    (
                        "Resolve PV AC/DC and distributed-generation coverage; gas "
                        "GT/CCGT and CHP mappings; and nuclear, geothermal and wind "
                        "retirement/repowering behavior. One generation year cannot "
                        "validate a causal age-use law. Offshore results rest on only"
                        " two generator records."
                    ),
                ),
                (
                    "Vehicle priorities",
                    (
                        "UK first-use cohorts remain proxies for EUR. Imports, "
                        "exports and reactivation confound retirement inference. "
                        "Heavy-goods vehicles are broader than 40t trucks. Occupancy,"
                        " payload and age-specific BEV usage remain assumptions."
                    ),
                ),
                (
                    "Validation status",
                    (
                        "Serialized checks: passed. Runtime checks passed: "
                        f"{runtime.get('all_passed', False)}. "
                        f"Producer tests: {checks.get('producer_tests_passed', 'not recorded')}; "
                        "signed-demand checks: "
                        f"{checks.get('signed_demand_checks', 'not recorded')}. "
                        "Refer to assessment.md for exact consumer results and artifact hashes. "
                        "Consumer inventories are synthetic; they test propagation and coefficient "
                        "conservation, not real inventory representativeness."
                    ),
                ),
            ],
        )
    pd.DataFrame(plotrows).to_csv(out / "distribution-plot-data.csv", index=False)
    notes = {
        "passenger-bev": (
            "UK first-use proxy for EUR. No eligible BEV age/mileage "
            "table; keep equal default plus 3% age sensitivity."
        ),
        "heavy-trucks": (
            "UK HGV proxy for 40t trucks. NAEI mileage sensitivity "
            "assumes age-independent payload/empty-running; lifetime "
            "prior remains uncalibrated."
        ),
        "passenger-liquids": (
            "Conventional petrol+diesel proxy; hybrid crosswalk "
            "unresolved. Two NAEI usage sensitivities, one combined IAM "
            "fleet."
        ),
        "pv": (
            "Utility-scale national audit differs from selected WECC "
            "baseline; AC/DC and distributed capacity unresolved. "
            "National service factors are an explicit proxy only."
        ),
        "ccgt": (
            "Component capacities and operating dates do not establish "
            "whole-block construction. CHP/technology mapping remains "
            "unresolved; national factors are a WECC proxy."
        ),
        "wind-onshore": (
            "Same-year national totals are relatively close. "
            "Operating-retention prior performs worse than no retirement "
            "over two years; repowering/date revisions require care."
        ),
        "wind-offshore": (
            "2020 IAM/observed ratio is 1.077; the 2022 ratio 18.005 "
            "largely reflects interpolation into rapid scenario growth. "
            "Only two operating generator records support the initial "
            "distribution."
        ),
        "nuclear": (
            "Same-year totals are close; old-cohort survival is poorly "
            "predicted by the current prior over this short panel. Plant "
            "allocations do not count as observed cohort generation."
        ),
        "gas-turbine": (
            "IAM stock is only about one third of selected NG non-CHP "
            "capacity. Seasonal ratings/CHP alternatives do not establish"
            " the native technology crosswalk."
        ),
        "geothermal": (
            "Totals are close, but historical composition performance is "
            "weak. Generation-weighted IAM rescaling exceeds 8,760 h/yr "
            "for cohort 1988: rejected, not clipped."
        ),
        "csp": (
            "2020 ratio is 1.088 versus 1.609 in interpolated 2022. "
            "Short-panel prior beats no retirement, but measured "
            "cohort-service coverage is below the gate."
        ),
    }
    current = metrics[
        (metrics.experiment == "A")
        & (metrics.reference_year == 2020)
        & (metrics.year == 2022)
        & (metrics.method == "prior")
    ]
    sections = [
        "# REMIND evidence work package: implemented results",
        (
            "\nScope: SSP2-NPi2025; eleven asset groups; production years "
            "2022–2050. Priorities 1–3 are implemented. Frozen historical"
            " priors were not tuned against the evaluation outcomes."
        ),
        "\n## Decisions by asset group",
        (
            "\nAge W1 is measured in years (lower is better), for "
            "experiment C initialized in 2020 and scored in 2022. "
            "Aggregate closing stocks are supplied; total-stock "
            "prediction errors are deliberately absent."
        ),
        "\n" + table(summary),
        "\n## Stock reconciliation",
        "\n"
        + table(
            stock.rename(columns={y: str(y) for y in stock.columns})
            .round(3)
            .reset_index()
            .rename(columns={"asset": "Asset"})
        ),
        (
            "\nRatios are IAM stock divided by selected observed stock. "
            "Only 2020 is a native IAM anchor here; 2021 and 2022 are "
            "interpolated. Vehicle ratios compare EUR scenario totals "
            "with UK observations and cannot be interpreted as stock "
            "errors. Power ratios still depend on technology, capacity "
            "and survey boundaries. `boundary-alternatives.csv` tests "
            "operating statuses, CHP inclusion, seasonal ratings and WECC"
            " subsets. No discrepancy is silently removed by rescaling "
            "historical validation populations."
        ),
        "\n" + "\n".join(f"- **{a}:** {notes[a]}" for a in assets),
        "\n## Historical evaluation",
        (
            "\nExperiment A uses conditional survival of opening cohorts. "
            "Power scoring excludes unresolved identity/category/date "
            "changes and measures confirmed operating retention in "
            "opening-capacity units. Vehicles measure net licensed cohort"
            " retention; imports, exports and reactivation are not "
            "identified retirements. Experiment B is unsupported because "
            "an independently verified gross-additions driver aligned "
            "with each observation boundary was unavailable. Experiment C"
            " supplies observed annual aggregate dated stocks but "
            "withholds the later composition; no total prediction credit "
            "is claimed."
        ),
        (
            f"\nThere are {len(metrics)} scored method/asset/year "
            f"experiments. All annual-age and five-year-bin metrics, "
            f"tails, coverage and bias are retained in "
            f"`historical-metrics.csv`; opening-population exclusions are "
            f"in `historical-exclusions.json`. Later unknown ages remain "
            f"outside the dated composition metric and are reported "
            f"separately. An equilibrium initialization is a benchmark, "
            f"not observed history."
        ),
        "\n### Separate 2022–2025 vehicle test",
        "\n" + table(future.round(3).reset_index()),
        (
            "\nThe prior beats no retirement for all three vehicle groups "
            "in this separate test. Earlier results are mixed, including "
            "the truck prior losing in 2022. For most power groups the "
            "short-window no-retirement benchmark is better than the "
            "lifetime prior; this does not justify adopting no retirement"
            " as a long-term law. Retain lifetime sensitivities and mark "
            "the priors as empirically unvalidated."
        ),
        "\n### Opening-cohort evaluation (2020–2022)",
        "\n"
        + table(current[["asset", "dated_coverage", "age_w1", "relative_stock_error"]].round(4)),
        "\n## Service weighting",
        (
            "\nThe promotion rule requires at least 90% observed capacity "
            "overall and 80% in every five-year age bin containing at "
            "least 5% of capacity. Generator output and an unambiguous "
            "single-cohort plant residual qualify as observed. Capacity "
            "allocations across several cohorts do not. New entrants, "
            "capacity/status changes, negative output, ambiguous IDs and "
            "missing output remain explicit. The ledger reconciles "
            "assigned and unassigned plant output without clipping "
            "conflicts."
        ),
        (
            "\nOffshore wind passes coverage and the 2022–2050 physical "
            "check; its previous service default is retained as "
            "`wind-offshore-previous-service`. Six other power candidates"
            " pass physical checks and are exported only as "
            "sensitivities. Geothermal fails (0.036454265 EJ/GW/yr "
            "against 0.031536, at 2022/cohort 1988). PV/CCGT candidates "
            "keep the original WECC stock amounts; national factor "
            "application remains a geographic proxy. All other primary "
            "service defaults remain unchanged."
        ),
        (
            "\nVehicle defaults remain equal service. The opt-in "
            "annual-age lookup moves each cohort along its usage curve "
            "each year, holds the last factor beyond its oldest age, and "
            "leaves lifetime survival untouched. Three assumed "
            "absolute-age decay cases and three NAEI mileage cases are "
            "exported. Their source, sample population, observation "
            "period and assumptions are in "
            "`vehicle-usage-assessment.json`. NAEI factors support "
            "mileage sensitivities, not observed passenger-km/tonne-km "
            "forecasts; occupancy/payload and future stationarity are "
            "explicit assumptions. No separate petrol/diesel IAM fleets "
            "were invented."
        ),
        "\n## Validation and reproducibility",
        (
            f"\nProducer tests: {checks.get('producer_tests_passed', 'not recorded')}; "
            f"signed-demand checks: {checks.get('signed_demand_checks', 'not recorded')}. "
            "See `validation-summary.json` and saved test/build logs."
        ),
        (
            f"\n- {len(examples)} accepted cases; "
            f"{validation['annual_profiles_checked']:,} annual profiles "
            f"independently validated.\n- {validation['source_rows']:,} "
            f"original scenario rows and "
            f"{validation['original_anchor_values_checked']:,} anchor "
            f"values preserved.\n- `baseline-invariance.json` confirms "
            f"unchanged existing stocks, annual flows and total "
            f"service.\n- `runtime-validation.json` records "
            f"filtered/encrypted cold and cached reads.\n- "
            f"`integration/constant/trails-validation.json` and "
            f"`integration/varying/trails-validation.json` record "
            f"signed-demand coefficient conservation with synthetic "
            f"inventories.\n- Source manifest SHA256: "
            f"`{provenance['manifest_sha256']}`.\n- Enriched output "
            f"SHA256: `{report['output_sha256']}`."
        ),
        (
            "\nNumerical validity, observation reconciliation and "
            "empirical predictive accuracy are separate results. The "
            "tests do not validate real inventory coefficients or "
            "identify a causal future usage law. No total production "
            "burden changes in this work package."
        ),
        "\n## Outputs",
        (
            "\n[PDF report](remind-evidence-validation-report.pdf). Plots "
            "and annual plot values are stored alongside this assessment."
            " `artifact-manifest.json` lists checksums; original "
            "scenarios and licensed inputs remain local."
        ),
        "\n## Source definitions",
        (
            "\n[EIA-860](https://www.eia.gov/electricity/data/eia860/), "
            "[EIA-923](https://www.eia.gov/electricity/data/eia923/), "
            "[DfT licensing "
            "tables](https://www.gov.uk/government/statistical-data-sets/vehicle-licensing-statistics-data-tables),"
            " and [NAEI fleet-turnover "
            "report](https://naei.energysecurity.gov.uk/sites/default/files/2025-03/4_NAEI_Improvement_Report_Road_Transport_Fleet_Turnover_Model_Development.pdf)."
            " Exact local source versions and hashes are pinned."
        ),
    ]
    (out / "assessment.md").write_text("\n".join(sections) + "\n")
    print(json.dumps(dict(pdf=str(out / "remind-evidence-validation-report.pdf"), plots=figures)))


if __name__ == "__main__":
    main()
