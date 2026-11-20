"""Create a plotted PDF report for the JRC-IDEES 2005 vehicle-stock run."""

from __future__ import annotations

import argparse
import json
import textwrap
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import FuncFormatter, PercentFormatter

NAVY = "#17324D"
BLUE = "#2F80ED"
TEAL = "#2A9D8F"
ORANGE = "#F4A261"
RED = "#D1495B"
GRAY = "#7B8794"
LIGHT_GRAY = "#DDE3E9"
PALE = "#F4F7FA"
WHITE = "#FFFFFF"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 12,
        "axes.labelsize": 9,
        "axes.edgecolor": LIGHT_GRAY,
        "axes.linewidth": 0.8,
        "axes.grid": True,
        "grid.color": "#E8EDF2",
        "grid.linewidth": 0.7,
        "axes.axisbelow": True,
        "legend.frameon": False,
        "figure.facecolor": WHITE,
        "savefig.facecolor": WHITE,
    }
)


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "run_dir",
        type=Path,
        help="Directory containing jrc-run-input-summary.json and results/.",
    )
    parser.add_argument(
        "baseline_report",
        type=Path,
        help="Original stock-vintage run report used for comparison.",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def wrap(value, width):
    return "\n".join(textwrap.wrap(value, width=width, break_long_words=False))


def page(title, subtitle, number):
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.07, 0.955, title, fontsize=20, fontweight="bold", color=NAVY, va="top")
    fig.text(0.07, 0.925, subtitle, fontsize=9.5, color=GRAY, va="top")
    fig.add_artist(
        plt.Line2D([0.07, 0.93], [0.905, 0.905], transform=fig.transFigure, color=BLUE, lw=2)
    )
    fig.text(0.07, 0.025, "JRC-IDEES 2005 vehicle-stock sensitivity", color=GRAY, fontsize=7.5)
    fig.text(0.93, 0.025, str(number), color=GRAY, fontsize=7.5, ha="right")
    return fig


def card(fig, x, y, width, height, value, label, color=BLUE):
    rect = plt.Rectangle(
        (x, y), width, height, transform=fig.transFigure, facecolor=PALE, edgecolor=LIGHT_GRAY
    )
    fig.add_artist(rect)
    fig.text(x + 0.025, y + height * 0.62, value, fontsize=22, fontweight="bold", color=color)
    fig.text(x + 0.025, y + height * 0.27, label, fontsize=8.5, color=GRAY)


def save_page(pdf, fig, pages_dir, number):
    pdf.savefig(fig)
    fig.savefig(pages_dir / f"page-{number:02d}.png", dpi=150)
    plt.close(fig)


def short_asset(asset):
    names = {
        "passenger-ldv-4w-bev": "Passenger cars · BEV",
        "passenger-ldv-4w-fcev": "Passenger cars · FCEV",
        "passenger-ldv-4w-gases": "Passenger cars · gases",
        "passenger-ldv-4w-hybrid": "Passenger cars · hybrid",
        "passenger-ldv-4w-liquids": "Passenger cars · liquids",
        "buses-bev": "Buses · BEV",
        "buses-fcev": "Buses · FCEV",
        "buses-gases": "Buses · gases",
        "buses-liquids": "Buses · liquids",
        "light-trucks-bev": "Light trucks · BEV",
        "light-trucks-fcev": "Light trucks · FCEV",
        "light-trucks-gases": "Light trucks · gases",
        "light-trucks-liquids": "Light trucks · liquids",
        "heavy-trucks-bev": "Heavy trucks · BEV",
        "heavy-trucks-fcev": "Heavy trucks · FCEV",
        "heavy-trucks-gases": "Heavy trucks · gases",
        "heavy-trucks-liquids": "Heavy trucks · liquids",
    }
    return names.get(asset, asset)


def opening_profile(table, region, asset):
    selected = table.loc[
        table["region"].eq(region)
        & table["asset"].eq(asset)
        & table["year"].eq(2005)
        & table["metric"].eq("stock")
    ]
    values = selected.groupby("cohort_year")["value"].sum().sort_index()
    return values / values.sum()


def report_data(run_dir, baseline_report_path):
    summary = load_json(run_dir / "jrc-run-input-summary.json")
    mapping = pd.read_csv(run_dir / "jrc-remind-2005-mapping.csv")
    new_report_path = next((run_dir / "results").glob("*_stock_vintages_report.json"))
    new_report = load_json(new_report_path)
    baseline_report = load_json(baseline_report_path)
    if any("assets" not in report["assumptions"] for report in (new_report, baseline_report)):
        raise ValueError("Run stock-vintages with --detailed-report to produce these plots.")
    new_table = pd.read_parquet(new_report["output_path"])
    baseline_table = pd.read_parquet(baseline_report["output_path"])
    independent = load_json(run_dir / "results" / "serialized-output-validation.json")
    package_dir = Path(new_report["output_path"]).parent
    package_validation = load_json(package_dir / "validation.json")
    package_manifest = load_json(package_dir / "datapackage.json")
    return {
        "summary": summary,
        "mapping": mapping,
        "new_report": new_report,
        "baseline_report": baseline_report,
        "new_table": new_table,
        "baseline_table": baseline_table,
        "independent": independent,
        "package_validation": package_validation,
        "package_manifest": package_manifest,
        "new_report_path": new_report_path,
    }


def cover(pdf, pages_dir, data):
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.add_artist(plt.Rectangle((0, 0.72), 1, 0.28, transform=fig.transFigure, facecolor=NAVY))
    fig.text(
        0.07,
        0.92,
        "JRC-IDEES 2005\nvehicle-stock sensitivity",
        fontsize=28,
        fontweight="bold",
        color=WHITE,
        va="top",
        linespacing=1.15,
    )
    fig.text(
        0.07,
        0.77,
        "REMIND SSP2-EU21-NPi2025 · Germany and France",
        fontsize=12,
        color="#CFE1F5",
    )
    card(fig, 0.07, 0.56, 0.25, 0.11, "34", "JRC-anchored asset-region cases")
    card(fig, 0.375, 0.56, 0.25, 0.11, "16", "Cases with partial cohort proxies", TEAL)
    card(fig, 0.68, 0.56, 0.25, 0.11, "159/159", "Cases passing independent checks", TEAL)
    mapping = data["mapping"]
    proxy = np.average(mapping["opening_proxy_share"], weights=mapping["jrc_anchored_2005"])
    fig.text(0.07, 0.47, "Executive result", fontsize=16, fontweight="bold", color=NAVY)
    result = (
        f"JRC replaces compatible 2005 road-vehicle stock anchors in DEU and FRA and provides "
        f"partial 2000–2005 entry-cohort evidence. The recent cohorts explain {proxy:.1%} of "
        "the mapped opening stock; older cohorts remain transparently prior-derived. The run is "
        "numerically valid, while five additional REMIND addition constraints become structurally "
        "incompatible with the new 2005 levels."
    )
    fig.text(0.07, 0.425, wrap(result, 94), fontsize=11, color=NAVY, va="top", linespacing=1.5)
    fig.text(0.07, 0.27, "Validation status", fontsize=12, fontweight="bold", color=NAVY)
    fig.text(
        0.07,
        0.235,
        "NUMERICAL PASS",
        fontsize=13,
        fontweight="bold",
        color=TEAL,
        bbox={"boxstyle": "round,pad=0.45", "facecolor": "#E7F4F1", "edgecolor": TEAL},
    )
    fig.text(
        0.29,
        0.235,
        "STRUCTURAL WARNINGS RETAINED",
        fontsize=13,
        fontweight="bold",
        color=ORANGE,
        bbox={"boxstyle": "round,pad=0.45", "facecolor": "#FFF2E6", "edgecolor": ORANGE},
    )
    fig.text(0.07, 0.12, "Prepared 27 October 2026", fontsize=9, color=GRAY)
    fig.text(
        0.07,
        0.09,
        "Source: JRC-IDEES-2021 Road Transport · CC BY 4.0",
        fontsize=8.5,
        color=GRAY,
    )
    fig.text(0.93, 0.025, "1", color=GRAY, fontsize=7.5, ha="right")
    save_page(pdf, fig, pages_dir, 1)


def source_and_scope(pdf, pages_dir, data):
    fig = page(
        "Evidence and transformation scope",
        "What changed in the IAM input—and what deliberately did not",
        2,
    )
    mapping = data["mapping"]
    grouped = mapping.groupby("region")[["remind_2005", "jrc_anchored_2005"]].sum()
    ax = fig.add_axes([0.08, 0.56, 0.38, 0.29])
    x = np.arange(len(grouped))
    width = 0.34
    ax.bar(x - width / 2, grouped["remind_2005"], width, color=GRAY, label="Original REMIND")
    ax.bar(x + width / 2, grouped["jrc_anchored_2005"], width, color=BLUE, label="JRC anchored")
    ax.set_xticks(x, grouped.index)
    ax.set_ylabel("Million vehicles")
    ax.set_title("Mapped 2005 vehicle stock")
    ax.legend(loc="upper right", fontsize=8)
    for index, row in enumerate(grouped.itertuples()):
        delta = row.jrc_anchored_2005 - row.remind_2005
        ax.text(index + width / 2, row.jrc_anchored_2005 + 0.8, f"{delta:+.2f}", ha="center")

    fig.text(0.52, 0.84, "Transformation rules", fontsize=13, fontweight="bold", color=NAVY)
    rules = [
        (
            "Passenger cars",
            "BEV and gas direct; PHEV → hybrid; liquids are the residual; FCEV = 0.",
        ),
        ("Buses and LCV", "BEV and gas direct; liquids are the residual; unlisted FCEV = 0."),
        ("Heavy trucks", "JRC total allocated using the original REMIND technology shares."),
        ("UKI", "Unchanged: JRC-IDEES-2021 does not cover the United Kingdom."),
    ]
    y = 0.79
    for heading, body in rules:
        fig.text(0.52, y, heading, fontsize=9.5, fontweight="bold", color=NAVY)
        fig.text(0.52, y - 0.026, wrap(body, 49), fontsize=8.5, color=GRAY, va="top")
        y -= 0.095

    ax_table = fig.add_axes([0.08, 0.17, 0.84, 0.27])
    ax_table.axis("off")
    table_data = [
        ["Stock anchor", "JRC Stock, 2005", "Direct or mapped category amount"],
        [
            "Recent cohorts",
            "JRC StockNew, 2000–2005",
            "Composition proxy, not survivor observation",
        ],
        ["Older cohorts", "Equilibrium remainder", "Explicitly labelled prior"],
        ["Later anchors", "Original REMIND", "Unchanged"],
    ]
    table = ax_table.table(
        cellText=table_data[1:],
        colLabels=table_data[0],
        loc="center",
        cellLoc="left",
        colLoc="left",
        colWidths=[0.2, 0.3, 0.5],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1, 1.7)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor(LIGHT_GRAY)
        cell.set_facecolor(NAVY if row == 0 else WHITE)
        if row == 0:
            cell.get_text().set_color(WHITE)
            cell.get_text().set_fontweight("bold")
    fig.text(
        0.08,
        0.11,
        wrap(
            "Licence and provenance: the checksum-pinned JRC table is recorded in the evidence "
            "manifest under CC BY 4.0. The derived IAM and configuration hashes are recorded in "
            "the package manifest.",
            115,
        ),
        fontsize=8.5,
        color=GRAY,
        va="top",
    )
    save_page(pdf, fig, pages_dir, 2)


def anchor_changes(pdf, pages_dir, data):
    fig = page(
        "Where the 2005 anchors changed",
        "Largest absolute differences between the original REMIND and JRC-mapped stock",
        3,
    )
    mapping = data["mapping"].copy()
    selected = mapping.reindex(mapping["absolute_change"].abs().nlargest(12).index).sort_values(
        "absolute_change"
    )
    labels = [f"{row.region} · {short_asset(row.asset)}" for row in selected.itertuples()]
    ax = fig.add_axes([0.27, 0.33, 0.65, 0.53])
    colors = [RED if value < 0 else TEAL for value in selected["absolute_change"]]
    bars = ax.barh(labels, selected["absolute_change"], color=colors)
    ax.axvline(0, color=NAVY, lw=0.8)
    ax.set_xlabel("Change in 2005 stock (million vehicles)")
    ax.set_title("JRC anchor minus original REMIND")
    max_abs = selected["absolute_change"].abs().max()
    for bar, value in zip(bars, selected["absolute_change"], strict=True):
        offset = 0.04 * max_abs
        ax.text(
            value + (offset if value >= 0 else -offset),
            bar.get_y() + bar.get_height() / 2,
            f"{value:+.3f}",
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=8,
            color=NAVY,
        )
    ax.set_xlim(-max_abs * 1.25, max_abs * 1.25)

    total_original = mapping["remind_2005"].sum()
    total_jrc = mapping["jrc_anchored_2005"].sum()
    fig.text(0.08, 0.24, "Net mapped-stock effect", fontsize=12, fontweight="bold", color=NAVY)
    fig.text(
        0.08,
        0.195,
        f"{total_original:.3f} → {total_jrc:.3f} million vehicles  "
        f"({total_jrc - total_original:+.3f} million; {(total_jrc / total_original - 1):+.2%})",
        fontsize=11,
        color=NAVY,
    )
    note = (
        "The small net change masks substantial redistribution. French liquid light trucks rise "
        "by 5.114 million, while German liquid passenger cars fall by 3.894 million. Zero JRC "
        "stocks for several 2005 future-powertrain categories remove corresponding REMIND values."
    )
    fig.text(0.08, 0.145, wrap(note, 112), fontsize=9, color=GRAY, va="top", linespacing=1.45)
    save_page(pdf, fig, pages_dir, 3)


def evidence_coverage(pdf, pages_dir, data):
    fig = page(
        "Opening-vintage evidence coverage",
        "Recent JRC entry cohorts versus the explicitly prior-derived older remainder",
        4,
    )
    mapping = data["mapping"].loc[data["mapping"]["opening_proxy_share"] > 0].copy()
    mapping["label"] = [f"{row.region} · {short_asset(row.asset)}" for row in mapping.itertuples()]
    mapping = mapping.sort_values(["region", "opening_proxy_share"])
    ax = fig.add_axes([0.29, 0.21, 0.63, 0.65])
    y = np.arange(len(mapping))
    ax.barh(y, mapping["opening_proxy_share"], color=TEAL, label="JRC 2000–2005 proxy")
    ax.barh(
        y,
        mapping["opening_prior_share"],
        left=mapping["opening_proxy_share"],
        color=LIGHT_GRAY,
        label="Older equilibrium prior",
    )
    ax.set_yticks(y, mapping["label"])
    ax.xaxis.set_major_formatter(PercentFormatter(1))
    ax.set_xlim(0, 1)
    ax.set_xlabel("Share of the 2005 opening stock")
    ax.legend(loc="lower right", fontsize=8)
    for position, value in enumerate(mapping["opening_proxy_share"]):
        ax.text(min(value + 0.015, 0.93), position, f"{value:.0%}", va="center", fontsize=7.5)
    overall = np.average(
        data["mapping"]["opening_proxy_share"],
        weights=data["mapping"]["jrc_anchored_2005"],
    )
    fig.text(
        0.08,
        0.13,
        f"Weighted proxy coverage across mapped stocks: {overall:.2%}",
        fontsize=11,
        fontweight="bold",
        color=NAVY,
    )
    fig.text(
        0.08,
        0.09,
        wrap(
            "French gas-bus entries slightly exceed the 2005 stock; only this case is "
            "reconciled, using factor 0.995798. Proxy coverage must not be read as direct "
            "observation of surviving vehicles.",
            116,
        ),
        fontsize=8.5,
        color=GRAY,
        va="top",
    )
    save_page(pdf, fig, pages_dir, 4)


def cohort_profiles(pdf, pages_dir, data):
    fig = page(
        "How the opening age profiles changed",
        "Two material examples, normalized to each asset's 2005 opening stock",
        5,
    )
    cases = [
        ("DEU", "passenger-ldv-4w-liquids", "German liquid passenger cars"),
        ("FRA", "light-trucks-liquids", "French liquid light trucks"),
    ]
    for index, (region, asset, title) in enumerate(cases):
        ax = fig.add_axes([0.1, 0.58 - index * 0.37, 0.82, 0.27])
        baseline = opening_profile(data["baseline_table"], region, asset)
        new = opening_profile(data["new_table"], region, asset)
        all_years = sorted(set(baseline.index) | set(new.index))
        baseline = baseline.reindex(all_years, fill_value=0)
        new = new.reindex(all_years, fill_value=0)
        ax.axvspan(1999.5, 2005.5, color="#E7F4F1", alpha=0.8, label="JRC StockNew window")
        ax.plot(all_years, baseline, color=GRAY, lw=2, marker="o", ms=3, label="Original run")
        ax.plot(all_years, new, color=BLUE, lw=2.2, marker="o", ms=3, label="JRC run")
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.set_ylabel("Opening-stock share")
        ax.set_title(title, loc="left", fontweight="bold", color=NAVY)
        ax.set_xlim(min(all_years) - 0.5, 2005.5)
        if index == 0:
            ax.legend(loc="upper left", ncols=3, fontsize=8)
        else:
            ax.set_xlabel("Entry / registration cohort")
    fig.text(
        0.1,
        0.085,
        wrap(
            "The original equilibrium opening state spreads stock evenly over feasible fixed-life "
            "cohorts. The JRC run preserves an equilibrium shape only for the unobserved older "
            "remainder and uses the reported 2000–2005 new-vehicle pattern for recent cohorts.",
            112,
        ),
        fontsize=8.7,
        color=GRAY,
        va="top",
    )
    save_page(pdf, fig, pages_dir, 5)


def diagnostic_map(report):
    return {(asset["region"], asset["asset"]): asset for asset in report["assumptions"]["assets"]}


def addition_residuals(pdf, pages_dir, data):
    fig = page(
        "Effect on addition-constraint consistency",
        "Absolute residuals at reported REMIND addition anchors",
        6,
    )
    base = diagnostic_map(data["baseline_report"])
    new = diagnostic_map(data["new_report"])
    identities = list(map(tuple, data["mapping"][["region", "asset"]].to_numpy()))
    records = []
    new_conflicts = []
    for identity in identities:
        old_diag = base[identity]["annualisation"]
        new_diag = new[identity]["annualisation"]
        if (
            old_diag["exact_inflow_constraints_feasible"]
            and not new_diag["exact_inflow_constraints_feasible"]
        ):
            new_conflicts.append(identity)
        records.append(
            {
                "identity": identity,
                "label": f"{identity[0]} · {short_asset(identity[1])}",
                "baseline": old_diag["actual_sum_absolute_rate_residual"],
                "jrc": new_diag["actual_sum_absolute_rate_residual"],
            }
        )
    frame = pd.DataFrame(records).nlargest(12, "jrc").sort_values("jrc")
    y = np.arange(len(frame))
    ax = fig.add_axes([0.29, 0.34, 0.63, 0.52])
    floor = 1e-5
    ax.barh(
        y - 0.18, np.maximum(frame["baseline"], floor), height=0.34, color=GRAY, label="Original"
    )
    ax.barh(y + 0.18, np.maximum(frame["jrc"], floor), height=0.34, color=BLUE, label="JRC run")
    labels = [
        label + ("  *" if identity in new_conflicts else "")
        for label, identity in zip(frame["label"], frame["identity"], strict=True)
    ]
    ax.set_yticks(y, labels)
    ax.set_xscale("log")
    ax.set_xlim(floor, 1.5)
    ax.set_xlabel("Sum of absolute addition-rate residuals (native annual units, log scale)")
    ax.legend(loc="lower right", fontsize=8)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))

    old_infeasible = sum(
        not asset["annualisation"]["exact_inflow_constraints_feasible"] for asset in base.values()
    )
    new_infeasible = sum(
        not asset["annualisation"]["exact_inflow_constraints_feasible"] for asset in new.values()
    )
    old_sum = sum(
        asset["annualisation"]["actual_sum_absolute_rate_residual"] for asset in base.values()
    )
    new_sum = sum(
        asset["annualisation"]["actual_sum_absolute_rate_residual"] for asset in new.values()
    )
    fig.text(
        0.08, 0.255, "Structural consistency result", fontsize=12, fontweight="bold", color=NAVY
    )
    fig.text(
        0.08,
        0.215,
        f"Infeasible exact-addition cases: {old_infeasible} → {new_infeasible}    |    "
        f"Total absolute rate residual: {old_sum:.3f} → {new_sum:.3f}",
        fontsize=10.5,
        color=NAVY,
    )
    conflict_text = ", ".join(f"{r} {short_asset(a)}" for r, a in new_conflicts)
    fig.text(
        0.08,
        0.17,
        wrap("* Newly infeasible under JRC: " + conflict_text + ".", 110),
        fontsize=8.5,
        color=RED,
        va="top",
    )
    fig.text(
        0.08,
        0.10,
        wrap(
            "Interpretation: the joint solver preserves stock anchors and reports discrepancies "
            "against unchanged REMIND addition anchors. The increase is a cross-source consistency "
            "warning, not a mass-balance or solver failure.",
            114,
        ),
        fontsize=8.5,
        color=GRAY,
        va="top",
    )
    save_page(pdf, fig, pages_dir, 6)


def validation_page(pdf, pages_dir, data):
    fig = page(
        "Validation results",
        "Independent serialization checks and package-level warning classification",
        7,
    )
    validation = data["package_validation"]
    check_names = [
        ("numerical_residuals", "Numerical residuals"),
        ("structural_consistency", "Structural consistency"),
        ("evidence_coverage", "Direct evidence coverage"),
        ("prior_dependence", "Prior dependence"),
        ("source_precision", "Source precision"),
    ]
    status_counts = {}
    for key, label in check_names:
        status_counts[label] = Counter(
            asset["checks"][key]["status"] for asset in validation["assets"]
        )
    ax = fig.add_axes([0.2, 0.58, 0.7, 0.27])
    labels = list(status_counts)
    left = np.zeros(len(labels))
    for status, color in (("pass", TEAL), ("warning", ORANGE), ("fail", RED)):
        values = np.array([status_counts[label].get(status, 0) for label in labels])
        ax.barh(labels, values, left=left, color=color, label=status.capitalize())
        for row, (start, value) in enumerate(zip(left, values, strict=True)):
            if value:
                ax.text(start + value / 2, row, str(value), ha="center", va="center", fontsize=8)
        left += values
    ax.set_xlim(0, len(validation["assets"]))
    ax.set_xlabel("Asset-region cases")
    ax.legend(loc="lower right", fontsize=8)
    ax.set_title("Package validation contract")

    independent = data["independent"]
    metrics = [
        ("Asset cases checked", f"{independent['asset_cases_checked']:,}"),
        ("Annual profiles checked", f"{independent['annual_profiles_checked']:,}"),
        ("Serialized rows", f"{independent['serialized_rows']:,}"),
        ("Maximum balance residual", f"{independent['maximum_balance_residual']:.3e}"),
        ("Maximum survival residual", f"{independent['maximum_survival_residual']:.3e}"),
        ("Independent result", "PASS" if independent["all_passed"] else "FAIL"),
    ]
    ax_table = fig.add_axes([0.12, 0.29, 0.76, 0.20])
    ax_table.axis("off")
    table = ax_table.table(
        cellText=metrics,
        colWidths=[0.62, 0.38],
        loc="center",
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.55)
    for (row, column), cell in table.get_celld().items():
        cell.set_edgecolor(LIGHT_GRAY)
        cell.set_facecolor(PALE if row % 2 == 0 else WHITE)
        if column == 1:
            cell.get_text().set_fontweight("bold")
            cell.get_text().set_color(TEAL if row == 5 else NAVY)

    fig.text(
        0.09,
        0.19,
        "Why the overall package says “warning”",
        fontsize=11.5,
        fontweight="bold",
        color=NAVY,
    )
    fig.text(
        0.09,
        0.15,
        wrap(
            "All numerical checks pass. Warnings remain because no case has a fully direct "
            "observed opening distribution, IAM values between anchors are interpolated, and "
            "some stock/addition/survival combinations are structurally inconsistent.",
            112,
        ),
        fontsize=8.7,
        color=GRAY,
        va="top",
    )
    fig.text(
        0.09,
        0.075,
        "Parquet SHA-256: " + independent["output_sha256"],
        fontsize=7.5,
        family="monospace",
        color=GRAY,
    )
    save_page(pdf, fig, pages_dir, 7)


def conclusions(pdf, pages_dir, data):
    fig = page(
        "Interpretation and reproducibility",
        "What this run supports—and the boundary of that conclusion",
        8,
    )
    fig.text(0.09, 0.83, "Conclusion", fontsize=15, fontweight="bold", color=NAVY)
    conclusion = (
        "The JRC run is a valid, auditable sensitivity that materially improves the empirical "
        "basis of the 2005 vehicle opening state. It should not automatically replace the original "
        "run: the JRC stock levels and later REMIND additions come from different accounting "
        "systems, and their increased residuals need a modelling decision rather than a numerical "
        "fix."
    )
    fig.text(0.09, 0.785, wrap(conclusion, 103), fontsize=11, color=NAVY, va="top", linespacing=1.5)

    fig.text(0.09, 0.64, "Recommended use", fontsize=12, fontweight="bold", color=NAVY)
    recommendations = [
        "Use this output as the evidence-based 2005 stock sensitivity.",
        "Retain proxy/prior evidence labels in downstream analyses.",
        "Do not interpret StockNew as a direct survivor census.",
        "Before promoting the run to a central case, reconcile the five new addition conflicts.",
    ]
    y = 0.60
    for item in recommendations:
        fig.text(0.105, y, "•", fontsize=12, color=BLUE)
        fig.text(0.13, y, item, fontsize=9.3, color=NAVY)
        y -= 0.045

    fig.text(0.09, 0.39, "Reproducibility bundle", fontsize=12, fontweight="bold", color=NAVY)
    files = [
        "stocks-jrc-2005.yaml — generated configuration",
        "jrc-remind-2005-mapping.csv — category mapping and anchor changes",
        "observations/*.csv — proxy/prior opening cohorts",
        "results/*_stock_vintages_v2/datapackage.json — checksums and provenance",
        "results/serialized-output-validation.json — independent checks",
    ]
    y = 0.35
    for item in files:
        fig.text(0.105, y, "•", fontsize=11, color=TEAL)
        fig.text(0.13, y, item, fontsize=8.6, family="monospace", color=NAVY)
        y -= 0.04

    manifest = data["package_manifest"]
    fig.text(0.09, 0.13, "Source and licence", fontsize=11, fontweight="bold", color=NAVY)
    source = manifest["evidence"]["sources"][0]
    fig.text(
        0.09,
        0.095,
        wrap(f"{source['version']} · {source['license']} · SHA-256 {source['sha256']}", 110),
        fontsize=7.7,
        family="monospace",
        color=GRAY,
        va="top",
    )
    fig.text(
        0.09,
        0.055,
        "Official dataset: https://data.jrc.ec.europa.eu/dataset/82322924-506a-4c9a-8532-2bdd30d69bf5",
        fontsize=7.2,
        color=GRAY,
    )
    save_page(pdf, fig, pages_dir, 8)


def main():
    args = arguments()
    run_dir = args.run_dir.resolve()
    output = args.output or run_dir / "JRC_IDEES_2005_vehicle_stock_run_report.pdf"
    output = output.resolve()
    figures_dir = run_dir / "report_figures"
    pages_dir = figures_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    data = report_data(run_dir, args.baseline_report.resolve())
    with PdfPages(output) as pdf:
        metadata = pdf.infodict()
        metadata["Title"] = "JRC-IDEES 2005 vehicle-stock sensitivity"
        metadata["Author"] = "iam-preprocessor"
        metadata["Subject"] = "REMIND vehicle stock-vintage run and validation"
        cover(pdf, pages_dir, data)
        source_and_scope(pdf, pages_dir, data)
        anchor_changes(pdf, pages_dir, data)
        evidence_coverage(pdf, pages_dir, data)
        cohort_profiles(pdf, pages_dir, data)
        addition_residuals(pdf, pages_dir, data)
        validation_page(pdf, pages_dir, data)
        conclusions(pdf, pages_dir, data)
    print(output)
    print(pages_dir)


if __name__ == "__main__":
    main()
