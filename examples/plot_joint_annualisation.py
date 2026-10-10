"""Compare actual fitted annual paths and cohorts; no display smoothing."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D

from iam_preprocessor.io import read_frame
from iam_preprocessor.stock_vintages import PREFIX

ASSETS = {
    "passenger-bev": "Passenger BEVs",
    "heavy-trucks": "Heavy trucks",
    "pv": "PV",
    "ccgt": "CCGT",
}


def plot(report_path):
    report = json.loads(report_path.read_text())
    output = report_path.parent
    frame = read_frame(report["output_path"]).set_index(["Region", "Variable"])
    metadata = report["assumptions"]
    years = np.arange(metadata["reference_year"], metadata["end_year"] + 1)
    labels = list(map(str, years))
    diagnostics = {a["asset"]: a for a in metadata["assets"]}
    summary = []
    curves = []
    with PdfPages(output / "annualisation-comparison.pdf") as pdf:
        fig, axes = plt.subplots(4, 2, figsize=(12, 13), constrained_layout=True)
        fig.suptitle("REMIND SSP2-NPi2025: constrained annual reconstruction", fontsize=15)
        for (asset, title), pair in zip(ASSETS.items(), axes, strict=True):
            diag = diagnostics[asset]
            joint = diag["annualisation"]
            region = frame.loc[diag["region"]]
            unit = diag["configuration"]["stock"]["unit"]
            for family, ax in zip(("Stock", "Inflow"), pair, strict=True):
                current = region.loc[PREFIX + asset + "|" + family, labels].to_numpy(float)
                baseline = region.loc[PREFIX + asset + "-linear-stock|" + family, labels].to_numpy(
                    float
                )
                ax.plot(
                    years, baseline, color="0.5", ls="--", lw=1.4, label="Linear-stock baseline"
                )
                ax.plot(years, current, color="#1764a0", lw=2, label="Joint annual fit")
                if family == "Stock":
                    a = [v for v in joint["stock_anchors"] if v["year"] <= years[-1]]
                    ax.scatter(
                        [v["year"] for v in a],
                        [v["target"] for v in a],
                        color="black",
                        s=20,
                        zorder=4,
                        label="IAM stock anchors",
                    )
                else:
                    for i, record in enumerate(joint["flow_constraints"]):
                        label = "IAM sampled rate / window mean" if i == 0 else None
                        if record["kind"] == "sampled_annual":
                            ax.scatter(
                                record["anchor"],
                                record["target_rate"],
                                color="#d56c12",
                                s=24,
                                zorder=4,
                                label=label,
                            )
                        else:
                            ax.hlines(
                                record["target_rate"],
                                min(record["years"]) - 0.5,
                                max(record["years"]) + 0.5,
                                colors="#d56c12",
                                label=label,
                            )
                    for suffix, linestyle in (("low", ":"), ("high", "-.")):
                        variable = PREFIX + asset + "-inflow-penalty-" + suffix + "|Inflow"
                        if variable in region.index:
                            ax.plot(
                                years,
                                region.loc[variable, labels].to_numpy(float),
                                color="#278643",
                                lw=1,
                                ls=linestyle,
                                label=f"{suffix.title()} inflow penalty",
                            )
                quantity_label = "stock / capacity" if family == "Stock" else "annual additions"
                ax.set(
                    title=f"{title}: {quantity_label}",
                    xlabel="Year",
                    ylabel=unit + ("/yr" if family == "Inflow" else ""),
                    xlim=(years[0], years[-1]),
                )
                ax.set_ylim(bottom=0)
                ax.grid(alpha=0.15)
                ax.legend(fontsize=7, frameon=False)
                curves.extend(
                    {
                        "asset": asset,
                        "family": family,
                        "year": int(y),
                        "baseline": float(b),
                        "joint": float(v),
                    }
                    for y, b, v in zip(years, baseline, current, strict=True)
                )
            summary.append(
                {
                    "asset": asset,
                    "exact_inflows_feasible": joint["exact_inflow_constraints_feasible"],
                    "maximum_stock_anchor_error": joint["stock_anchor_max_absolute_residual"],
                    "baseline_curvature_l2": joint["baseline_curvature_l2"],
                    "joint_curvature_l2": joint["fitted_curvature_l2"],
                    "minimum_sum_absolute_rate_error": joint["minimum_sum_absolute_rate_residual"],
                    "actual_sum_absolute_rate_error": joint["actual_sum_absolute_rate_residual"],
                    "maximum_absolute_period_rate_error": max(
                        abs(c["rate_residual"]) for c in joint["flow_constraints"]
                    ),
                }
            )
        pdf.savefig(fig)
        fig.savefig(output / "annual-additions-comparison.png", dpi=160)
        plt.close(fig)
        fig, axes = plt.subplots(2, 2, figsize=(12, 8))
        for (asset, title), ax in zip(ASSETS.items(), axes.flat, strict=True):
            region = frame.loc[diagnostics[asset]["region"]]
            for year, color in zip(
                (2022, 2030, 2050), ("#1764a0", "#d56c12", "#278643"), strict=True
            ):
                if year > years[-1]:
                    continue
                for suffix, style, width in (("-linear-stock", "--", 1), ("", "-", 1.8)):
                    rows = region.loc[
                        region.index.str.startswith(
                            PREFIX + asset + suffix + "|Service Share|Vintage|"
                        )
                    ]
                    cohorts = np.array([int(v.split("|")[-1]) for v in rows.index])
                    select = cohorts <= year
                    ax.plot(
                        cohorts[select],
                        rows[str(year)].to_numpy(float)[select],
                        color=color,
                        ls=style,
                        lw=width,
                        alpha=0.6 if suffix else 1,
                        label=str(year) if not suffix else None,
                    )
            ax.set(title=title, xlabel="Entry / cohort year", ylabel="Annual service share")
            ax.set_ylim(bottom=0)
            ax.grid(alpha=0.15)
            ax.legend(frameon=False)
        fig.suptitle("Recomputed service composition: annual cohorts, without display smoothing")
        fig.legend(
            handles=[
                Line2D([0], [0], color="0.4", ls="--", label="Linear-stock baseline"),
                Line2D([0], [0], color="0.2", label="Joint annual fit"),
            ],
            loc="upper center",
            bbox_to_anchor=(0.5, 0.95),
            ncol=2,
            frameon=False,
        )
        fig.tight_layout(rect=(0, 0, 1, 0.9))
        pdf.savefig(fig)
        fig.savefig(output / "cohort-comparison.png", dpi=180)
        plt.close(fig)
    pd.DataFrame(summary).to_csv(output / "comparison-summary.csv", index=False)
    pd.DataFrame(curves).to_csv(output / "annual-path-comparison.csv", index=False)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    plot(parser.parse_args().report)
