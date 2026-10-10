"""Create a review PDF and numeric plot tables for the expanded REMIND pilot."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from run_remind_sector_expansion import PRIMARY

from iam_preprocessor.io import read_frame
from iam_preprocessor.stock_vintages import PREFIX


def render(directory):
    report = json.loads(
        (directory / "REMIND_generic_SSP2-NPi2025_stock_vintages_report.json").read_text()
    )
    audit = json.loads((directory / "sector-observation-audit.json").read_text())
    rejected = json.loads((directory / "rejected-sensitivities.json").read_text())
    data = read_frame(report["output_path"]).set_index(["Region", "Variable"])
    first, last = (report["assumptions"][k] for k in ("reference_year", "end_year"))
    years = np.arange(first, last + 1)
    configs = {a["asset"]: a for a in report["assumptions"]["assets"]}
    age_rows, cohort_rows, flow_rows, constraints = [], [], [], []
    for ident, asset in configs.items():
        group = next(
            g
            for g in sorted(PRIMARY, key=len, reverse=True)
            if ident == g or ident.startswith(g + "-")
        )
        case = "primary" if ident == group else ident.removeprefix(group + "-")
        region = data.loc[asset["region"]]
        prefix = PREFIX + ident + "|"
        rows = region.loc[region.index.str.startswith(prefix + "Service Share|Vintage|")]
        cohorts = np.array([int(v.split("|")[-1]) for v in rows.index])
        for year in years:
            weights = rows[str(year)].to_numpy(float)
            age_rows.append(
                dict(asset=group, case=case, year=year, mean_age=np.dot(year - cohorts, weights))
            )
            if case == "primary":
                for c, w in zip(cohorts, weights, strict=True):
                    cohort_rows.append(dict(asset=group, service_year=year, cohort=c, share=w))
                flow_rows.append(
                    dict(
                        asset=group,
                        year=year,
                        inflow=region.loc[prefix + "Inflow", str(year)],
                        stock=region.loc[prefix + "Stock", str(year)],
                    )
                )
        if case == "primary" and "annualisation" in asset:
            for row in asset["annualisation"]["flow_constraints"]:
                constraints.append(dict(asset=group, **row))
    ages, cohorts, flows = (pd.DataFrame(x) for x in (age_rows, cohort_rows, flow_rows))
    ages.to_csv(directory / "sector-mean-ages.csv", index=False)
    cohorts.to_csv(directory / "sector-service-shares.csv", index=False)
    flows.to_csv(directory / "sector-annual-inflows.csv", index=False)
    pd.DataFrame(constraints).to_csv(
        directory / "sector-source-inflow-constraints.csv", index=False
    )
    with PdfPages(directory / "sector-expansion-report.pdf") as pdf:
        fig = plt.figure(figsize=(11.7, 8.3))
        fig.text(0.07, 0.91, "REMIND stock-vintage sector expansion", fontsize=22, weight="bold")
        lines = [
            "SSP2-NPi2025 | EUR vehicles and USA power | 2022–2050 | modelling pilot",
            "",
            "11 asset groups: BEV cars, heavy trucks, PV, CCGT, liquid-fuel cars,",
            "onshore wind, offshore wind, nuclear, gas turbines, geothermal and CSP.",
            "",
            "Annual additions are fitted jointly with survival and native stock anchors.",
            "Power investment rates represent reporting-window means, not point samples.",
            "Incompatible inflow observations are reconciled with explicit residuals.",
            "",
            "UK petrol/diesel first-use cohorts initialize the combined Liquids fleet.",
            "Petrol-only and diesel-only compositions are sensitivities, not separate forecasts.",
            "New power cohorts use operating US EIA-860 generator capacity by operating year.",
            "CHP and non-operating generators are excluded; unknown dates remain audited.",
            "",
            "Power technical lives are Weibull mean priors, not measured retirement laws.",
            "New groups assume equal service per vehicle or GW. Lifetime: ±25% sensitivities.",
            "Composition timestamps existing production burdens; it does not change their total.",
            "",
            f"{len(configs)} accepted cases; {len(years) * len(configs):,} annual profiles.",
            f"{len(rejected['rejected'])} optional cases rejected by the physical service limit.",
            "Offshore initialization has only two generator records (not two turbines).",
            "Historical vehicle tail retained with numerically stable conditional survival.",
            "",
            "Scope limits: regional proxies, native category boundaries, repowering dates,",
            "age-specific use, and within-period investment timing remain assumptions.",
        ]
        fig.text(0.07, 0.85, "\n".join(lines), fontsize=11, va="top", linespacing=1.45)
        pdf.savefig(fig)
        plt.close(fig)
        for kind in ("distributions", "additions", "mean-ages"):
            fig, axes = plt.subplots(4, 3, figsize=(11.7, 13), constrained_layout=True)
            for asset, ax in zip(PRIMARY, axes.flat, strict=False):
                if kind == "distributions":
                    for year in sorted({first, 2030, last}):
                        rows = cohorts.loc[cohorts.asset.eq(asset) & cohorts.service_year.eq(year)]
                        ax.plot(rows.cohort, rows.share, label=str(year), lw=1.4)
                    ax.set(xlabel="Entry / cohort year", ylabel="Service share", xlim=(1970, last))
                    # Full tails are retained in the data; an inset note avoids hiding that fact.
                    tail = cohorts.loc[cohorts.asset.eq(asset) & cohorts.cohort.lt(1970)]
                    if len(tail) and tail.share.max() > 0:
                        ax.text(
                            0.03,
                            0.94,
                            "Pre-1970 tail in CSV",
                            transform=ax.transAxes,
                            fontsize=7,
                            va="top",
                        )
                elif kind == "additions":
                    primary = flows.loc[flows.asset.eq(asset)]
                    ax.plot(primary.year, primary.inflow, label="joint annual fit")
                    a = configs[asset]
                    region = data.loc[a["region"]]
                    ident = asset + "-linear-stock"
                    ax.plot(
                        years,
                        region.loc[PREFIX + ident + "|Inflow", list(map(str, years))],
                        label="linear-stock reconstruction",
                        alpha=0.7,
                        linestyle="--",
                    )
                    native = a["annualisation"]["flow_constraints"]
                    for i, row in enumerate(native):
                        if len(row["years"]) == 1:
                            ax.scatter(
                                row["anchor"],
                                row["target_rate"],
                                marker="x",
                                color="black",
                                label="reported annual sales" if i == 0 else None,
                            )
                        else:
                            ax.hlines(
                                row["target_rate"],
                                min(row["years"]) - 0.5,
                                max(row["years"]) + 0.5,
                                color="black",
                                lw=1,
                                label="reported period mean" if i == 0 else None,
                            )
                    ax.set(
                        xlabel="Year",
                        ylabel=a["configuration"]["inflow"]["unit"],
                        xlim=(first, last),
                    )
                else:
                    cases = ("primary", "short-life", "long-life", "linear-stock")
                    if asset == "passenger-liquids":
                        cases += ("petrol-composition", "diesel-composition")
                    for case in cases:
                        rows = ages.loc[ages.asset.eq(asset) & ages.case.eq(case)]
                        ax.plot(rows.year, rows.mean_age, label=case)
                    ax.set(xlabel="Service year", ylabel="Mean serving-stock age (years)")
                ax.set_title(asset)
                ax.legend(fontsize=6, loc="best")
                ax.grid(alpha=0.15)
            axes.flat[-1].set_visible(False)
            title = {
                "distributions": "Service composition by cohort (no cosmetic smoothing)",
                "additions": "Annual additions and reported source rates",
                "mean-ages": "Lifetime and initial-composition sensitivities",
            }[kind]
            fig.suptitle(title, fontsize=16)
            pdf.savefig(fig)
            fig.savefig(directory / f"sector-{kind}.png", dpi=150)
            plt.close(fig)
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    render(parser.parse_args().directory)
