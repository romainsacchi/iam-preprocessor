"""Generate a ten-page plain-English PDF for a completed REMIND vintage run."""

# ruff: noqa: E501 -- long prose strings are wrapped inside the generated report.

from __future__ import annotations

import argparse
import json
import textwrap
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from iam_preprocessor.io import read_frame
from iam_preprocessor.stock_registry import load_remind_asset_registry

PAGE = (8.27, 11.69)
NAVY = "#17324D"
BLUE = "#247BA0"
TEAL = "#2A9D8F"
GREEN = "#5B8C5A"
GOLD = "#E9C46A"
ORANGE = "#F4A261"
RED = "#D95D39"
PALE = "#F3F6F8"
INK = "#24313A"
MUTED = "#647480"


def wrapped(text, width):
    lines = []
    for paragraph in text.splitlines():
        lines.extend(textwrap.wrap(paragraph, width=width, break_long_words=False) or [""])
    return "\n".join(lines)


def base_page(title, page_number, subtitle=None):
    fig = plt.figure(figsize=PAGE, facecolor="white")
    fig.text(0.07, 0.952, title, color=NAVY, fontsize=20, weight="bold", va="top")
    if subtitle:
        fig.text(0.07, 0.914, subtitle, color=MUTED, fontsize=9.5, va="top")
    fig.lines.append(
        plt.Line2D([0.07, 0.93], [0.895, 0.895], transform=fig.transFigure, color=TEAL, lw=2)
    )
    fig.text(
        0.07,
        0.025,
        "REMIND stock-vintage reconstruction — plain-English run report",
        fontsize=7.5,
        color=MUTED,
    )
    fig.text(0.93, 0.025, f"{page_number} / 10", fontsize=7.5, color=MUTED, ha="right")
    return fig


def box(fig, xywh, title, body, color=BLUE, title_size=12, body_size=9):
    x, y, w, h = xywh
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        transform=fig.transFigure,
        boxstyle="round,pad=0.012,rounding_size=0.012",
        facecolor=PALE,
        edgecolor=color,
        linewidth=1.2,
    )
    fig.patches.append(patch)
    fig.text(
        x + 0.018, y + h - 0.026, title, fontsize=title_size, weight="bold", color=color, va="top"
    )
    fig.text(
        x + 0.018,
        y + h - 0.064,
        wrapped(body, max(24, int(w * 105))),
        fontsize=body_size,
        color=INK,
        va="top",
        linespacing=1.35,
    )


def stat_card(fig, x, y, value, label, color=TEAL):
    patch = FancyBboxPatch(
        (x, y),
        0.19,
        0.105,
        transform=fig.transFigure,
        boxstyle="round,pad=0.01,rounding_size=0.015",
        facecolor=PALE,
        edgecolor="none",
    )
    fig.patches.append(patch)
    fig.text(
        x + 0.095,
        y + 0.064,
        value,
        ha="center",
        va="center",
        fontsize=18,
        weight="bold",
        color=color,
    )
    fig.text(x + 0.095, y + 0.025, label, ha="center", va="center", fontsize=8.5, color=MUTED)


def bullets(fig, items, x, y, width=70, size=9.5, gap=0.07, color=INK):
    current = y
    for item in items:
        lines = wrapped(item, width)
        fig.text(x, current, "•", fontsize=size + 2, color=TEAL, va="top")
        fig.text(x + 0.025, current, lines, fontsize=size, color=color, va="top", linespacing=1.35)
        current -= gap + 0.018 * lines.count("\n")
    return current


def find_single(path, pattern):
    matches = list(Path(path).glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"Expected one {pattern} under {path}; found {len(matches)}")
    return matches[0]


def metric(frame, region, variable, year):
    row = frame.loc[frame["Region"].eq(region) & frame["Variable"].eq(variable)]
    if len(row) != 1:
        raise ValueError(f"Missing unique source row: {region}/{variable}")
    return float(row.iloc[0][str(year)])


def grouped_vintage(table, asset):
    subset = table.loc[table["asset"].eq(asset)].copy()
    start = (subset["cohort_year"].astype(int) // 5) * 5
    subset["period"] = start.astype(str) + "–" + (start + 4).astype(str)
    return subset.groupby("period", sort=True)["value"].sum().mul(100)


def generate(args):
    source = read_frame(args.source)
    inventory = pd.read_csv(args.inventory, sep=";")
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    report_path = find_single(args.run_dir, "*_stock_vintages_report.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    package = find_single(args.run_dir, "*_stock_vintages_v2")
    manifest = json.loads((package / "datapackage.json").read_text(encoding="utf-8"))
    validation = json.loads((package / "validation.json").read_text(encoding="utf-8"))
    parquet = package / "vintages.parquet"

    diagnostics = report["assumptions"]["assets"]
    diagnostic = {(item["asset"], item["region"]): item for item in diagnostics}
    annual = [item["annualisation"] for item in diagnostics]
    registry, _ = load_remind_asset_registry()
    sector_by_asset = {
        asset_id: metadata["sector"] for asset_id, metadata in registry["assets"].items()
    }
    asset_ids = sorted({item["id"] for item in config["assets"]})
    sectors = Counter(sector_by_asset[asset_id] for asset_id in asset_ids)
    status_counts = inventory["status"].value_counts()
    parquet_rows = next(
        item["rows"] for item in manifest["resources"] if item["path"] == "vintages.parquet"
    )
    parquet_mb = parquet.stat().st_size / 1e6
    exact_count = sum(item["exact_inflow_constraints_feasible"] for item in annual)
    penalized_count = len(annual) - exact_count
    max_anchor = max(item["stock_anchor_max_absolute_residual"] for item in annual)
    max_balance = max(abs(item["maximum_balance_residual"]) for item in diagnostics)
    max_kkt = max(item["kkt_stationarity_max"] for item in annual)
    solver_counts = Counter(item["solver"] for item in annual)

    pv_stock = {
        year: metric(source, "DEU", "Cap|Electricity|Solar|+|PV", year)
        for year in (2020, 2025, 2030, 2050)
    }
    pv_add = {
        year: metric(source, "DEU", "New Cap|Electricity|Solar|+|PV", year)
        for year in (2020, 2025, 2030, 2050)
    }
    pv_lifetime = metric(source, "DEU", "Tech|Electricity|Solar|PV|Lifetime", 2025)
    interpolation_years = np.arange(2025, 2031)
    interpolation_values = np.interp(
        interpolation_years, [2025, 2030], [pv_add[2025], pv_add[2030]]
    )

    transport_parent = "Stock|Transport|Pass|Road|LDV|Four Wheelers"
    transport_children = ["BEV", "FCEV", "Gases", "Hybrid electric", "Liquids"]
    parent_value = metric(source, "DEU", transport_parent, 2050)
    child_values = {
        child: metric(source, "DEU", transport_parent + "|" + child, 2050)
        for child in transport_children
    }

    opening = pd.read_parquet(
        parquet,
        filters=[
            ("region", "==", "DEU"),
            ("asset", "==", "pv"),
            ("year", "==", 2005),
            ("metric", "==", "stock_share"),
        ],
    ).sort_values("cohort_year")
    vintage_2050 = pd.read_parquet(
        parquet,
        filters=[("region", "==", "DEU"), ("year", "==", 2050), ("metric", "==", "stock_share")],
    )
    grouped_pv = grouped_vintage(vintage_2050, "pv")
    grouped_bev = grouped_vintage(vintage_2050, "passenger-ldv-4w-bev")
    sample = pd.read_parquet(
        parquet,
        filters=[
            ("region", "==", "DEU"),
            ("asset", "==", "pv"),
            ("year", "==", 2050),
            ("cohort_year", "==", 2038),
        ],
    ).set_index("metric")

    pv_diag = diagnostic[("pv", "DEU")]["annualisation"]
    offshore_diag = diagnostic[("wind-offshore", "DEU")]["annualisation"]
    pv_flow = pd.DataFrame(pv_diag["flow_constraints"])
    offshore_flow = pd.DataFrame(offshore_diag["flow_constraints"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(
        args.output,
        metadata={
            "Title": "How the REMIND stock-vintage reconstruction works",
            "Author": "iam-preprocessor",
            "Subject": "Plain-English report based on the DEU/FRA/UKI run",
        },
    ) as pdf:
        # 1 — executive summary
        fig = base_page(
            "How old is the infrastructure in an IAM scenario?",
            1,
            "A ten-page, non-expert guide using the completed REMIND SSP2-EU21-NPi2025 run",
        )
        fig.text(0.07, 0.835, "What this work does", fontsize=15, weight="bold", color=BLUE)
        fig.text(
            0.07,
            0.795,
            wrapped(
                "REMIND tells us how much equipment exists in each model year and how much is added. It does not directly say which construction years are still operating. We reconstruct that missing age mix — called the vintage composition — with an explicit stock-and-flow calculation.",
                92,
            ),
            fontsize=11,
            color=INK,
            va="top",
            linespacing=1.5,
        )
        stat_card(fig, 0.07, 0.62, "3", "regions: DEU, FRA, UKI")
        stat_card(fig, 0.285, 0.62, "53", "non-overlapping asset types", BLUE)
        stat_card(fig, 0.50, 0.62, "159", "region × asset calculations", ORANGE)
        stat_card(fig, 0.715, 0.62, f"{parquet_rows:,}", "long-table output rows", GREEN)
        box(
            fig,
            (0.07, 0.39, 0.40, 0.16),
            "Main result",
            f"The run completed without a numerical failure. Stock anchors were reproduced within {max_anchor:.2e} in their native units, and the largest annual balance error was {max_balance:.2e}.",
            TEAL,
        )
        box(
            fig,
            (0.53, 0.39, 0.40, 0.16),
            "Important caution",
            "The result is a transparent reconstruction, not observed installation history. Opening ages are a prior, and many reported additions must be reconciled with the stock totals.",
            ORANGE,
        )
        fig.text(0.07, 0.31, "The calculation in one line", fontsize=13, weight="bold", color=NAVY)
        steps = ["IAM stocks", "annual additions", "lifetime / survival", "vintage shares"]
        for i, step in enumerate(steps):
            x = 0.07 + i * 0.22
            fig.text(x + 0.085, 0.235, step, ha="center", fontsize=9, weight="bold", color=NAVY)
            patch = FancyBboxPatch(
                (x, 0.20),
                0.17,
                0.075,
                transform=fig.transFigure,
                boxstyle="round,pad=0.01",
                facecolor=PALE,
                edgecolor=TEAL,
            )
            fig.patches.append(patch)
            if i < 3:
                fig.patches.append(
                    FancyArrowPatch(
                        (x + 0.175, 0.238),
                        (x + 0.215, 0.238),
                        transform=fig.transFigure,
                        arrowstyle="->",
                        mutation_scale=12,
                        color=MUTED,
                    )
                )
        fig.text(
            0.07,
            0.115,
            f"Canonical output: {parquet_mb:.2f} MB Parquet package; no large compatibility CSV was needed.",
            fontsize=9.5,
            color=MUTED,
        )
        pdf.savefig(fig)
        plt.close(fig)

        # 2 — stock-flow concept
        fig = base_page("1. The basic idea: assets enter, age and leave", 2)
        fig.text(
            0.07,
            0.84,
            wrapped(
                "Think of the infrastructure stock as a bathtub. New equipment flows in. Retirements flow out. What remains is split by the year in which each cohort entered.",
                90,
            ),
            fontsize=11,
            color=INK,
            va="top",
            linespacing=1.45,
        )
        ax = fig.add_axes([0.08, 0.48, 0.84, 0.27])
        ax.axis("off")
        ax.add_patch(
            FancyBboxPatch(
                (0.30, 0.22),
                0.40,
                0.52,
                boxstyle="round,pad=0.02",
                facecolor="#DDEFF5",
                edgecolor=BLUE,
                linewidth=2,
            )
        )
        ax.text(0.50, 0.60, "Installed stock", ha="center", fontsize=16, weight="bold", color=NAVY)
        ax.text(
            0.50,
            0.42,
            f"DEU solar PV in 2025\n{pv_stock[2025]:.1f} GW",
            ha="center",
            fontsize=12,
            color=INK,
        )
        ax.add_patch(
            FancyArrowPatch(
                (0.02, 0.48),
                (0.29, 0.48),
                arrowstyle="-|>",
                mutation_scale=20,
                color=TEAL,
                linewidth=3,
            )
        )
        ax.text(
            0.14,
            0.58,
            f"New additions\n{pv_add[2025]:.2f} GW/yr",
            ha="center",
            fontsize=11,
            color=TEAL,
        )
        ax.add_patch(
            FancyArrowPatch(
                (0.71, 0.48),
                (0.98, 0.48),
                arrowstyle="-|>",
                mutation_scale=20,
                color=RED,
                linewidth=3,
            )
        )
        ax.text(
            0.85, 0.58, "Retirements\nnatural + additional", ha="center", fontsize=11, color=RED
        )
        fig.text(0.07, 0.40, "The accounting identity", fontsize=13, weight="bold", color=NAVY)
        box(
            fig,
            (0.07, 0.25, 0.86, 0.10),
            "Every year",
            "closing stock = opening stock + additions − natural retirements − any additional retirements",
            BLUE,
            11,
            10,
        )
        bullets(
            fig,
            [
                "A cohort is a group with one entry year, such as all PV capacity added in 2038.",
                "Cohorts are followed separately, but their sum must equal the IAM stock.",
                "At 2050, the 2038 DEU PV cohort contains {:.2f} GW and represents {:.2f}% of PV stock.".format(
                    float(sample.at["stock", "value"]),
                    100 * float(sample.at["stock_share", "value"]),
                ),
            ],
            0.08,
            0.19,
            width=90,
            size=8.8,
            gap=0.035,
        )
        pdf.savefig(fig)
        plt.close(fig)

        # 3 — coverage
        fig = base_page(
            "2. First audit everything in the scenario file",
            3,
            "Coverage is decided before any vintage is calculated",
        )
        fig.text(
            0.07,
            0.84,
            wrapped(
                "The source contains 199 stock-like series. Many are totals, detailed sub-categories, or variables without a usable lifetime. Treating all of them as separate assets would double count infrastructure.",
                92,
            ),
            fontsize=10.5,
            color=INK,
            va="top",
            linespacing=1.4,
        )
        ax1 = fig.add_axes([0.18, 0.46, 0.72, 0.29])
        order = [
            "mapped",
            "mapped_aggregate_fallback",
            "reporting_aggregate",
            "below_selected_layer",
            "ambiguous_lifetime",
            "missing_lifetime",
            "missing_inflow",
        ]
        labels = [
            "mapped",
            "fallback parent",
            "reporting total",
            "finer detail",
            "ambiguous life",
            "missing life",
            "missing additions",
        ]
        values = [int(status_counts.get(item, 0)) for item in order]
        colors = [TEAL, BLUE, GOLD, "#9BB8C7", ORANGE, RED, "#9C6B7C"]
        ax1.barh(labels[::-1], values[::-1], color=colors[::-1])
        for i, value in enumerate(values[::-1]):
            ax1.text(value + 1, i, str(value), va="center", fontsize=9, color=INK)
        ax1.set_title(
            "All 199 stock-like series are classified", loc="left", color=NAVY, weight="bold"
        )
        ax1.spines[["top", "right", "left"]].set_visible(False)
        ax1.tick_params(axis="y", length=0)
        ax1.set_xlabel("number of source series")
        ax2 = fig.add_axes([0.10, 0.16, 0.80, 0.20])
        sector_order = [
            "power",
            "transport",
            "hydrogen",
            "heat",
            "gases",
            "liquids",
            "storage",
            "carbon_management",
        ]
        sector_labels = [
            "electricity",
            "transport",
            "hydrogen",
            "heat",
            "gases",
            "liquids",
            "storage",
            "DAC",
        ]
        sector_values = [sectors.get(item, 0) for item in sector_order]
        ax2.bar(
            sector_labels,
            sector_values,
            color=[BLUE, TEAL, ORANGE, GOLD, GREEN, "#8B6FB3", "#729EA1", RED],
        )
        for i, value in enumerate(sector_values):
            ax2.text(i, value + 0.35, str(value), ha="center", fontsize=9)
        ax2.set_ylim(0, max(sector_values) + 4)
        ax2.set_title(
            "The selected layer has 53 asset types", loc="left", color=NAVY, weight="bold"
        )
        ax2.spines[["top", "right", "left"]].set_visible(False)
        ax2.tick_params(axis="x", rotation=25, length=0)
        ax2.tick_params(axis="y", left=False, labelleft=False)
        pdf.savefig(fig)
        plt.close(fig)

        # 4 — hierarchy
        fig = base_page(
            "3. Choose one non-overlapping level",
            4,
            "Transport provides a clear example of why hierarchy checks matter",
        )
        fig.text(
            0.07,
            0.84,
            wrapped(
                "REMIND reports both a total four-wheel passenger fleet and its powertrain children. We use the children only after checking that they add back to the parent in every source year.",
                90,
            ),
            fontsize=10.5,
            color=INK,
            va="top",
            linespacing=1.4,
        )
        ax = fig.add_axes([0.17, 0.43, 0.72, 0.31])
        labels = list(child_values)
        vals = [child_values[label] for label in labels]
        ax.barh(labels[::-1], vals[::-1], color=[TEAL, "#8EC6C0", GOLD, ORANGE, BLUE][::-1])
        for i, value in enumerate(vals[::-1]):
            ax.text(value + 0.3, i, f"{value:.3f}", va="center", fontsize=9)
        ax.set_xlabel("million vehicles in DEU, 2050")
        ax.set_title(
            "Powertrain children of four-wheel passenger vehicles",
            loc="left",
            color=NAVY,
            weight="bold",
        )
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.tick_params(axis="y", length=0)
        child_sum = sum(child_values.values())
        box(
            fig,
            (0.07, 0.25, 0.40, 0.11),
            "Parent reported by REMIND",
            f"{parent_value:.6f} million vehicles",
            BLUE,
        )
        box(
            fig,
            (0.53, 0.25, 0.40, 0.11),
            "Sum of five children",
            f"{child_sum:.6f} million vehicles; difference = {child_sum - parent_value:+.2e}",
            TEAL,
        )
        fig.text(
            0.07,
            0.17,
            wrapped(
                "Result: the run uses BEV, FCEV, gases, hybrid-electric and liquids as separate assets, and does not add the parent total again. If a future file lacks a complete child set, the parent becomes a documented fallback.",
                94,
            ),
            fontsize=10,
            color=INK,
            va="top",
            linespacing=1.4,
        )
        pdf.savefig(fig)
        plt.close(fig)

        # 5 — interpolation
        fig = base_page("4. Turn five-year observations into annual inputs", 5)
        fig.text(
            0.07,
            0.84,
            wrapped(
                "The source values are annual rates observed at model years. Between those years we draw a straight line. We do not reinterpret a 2030 value as a five-year total.",
                90,
            ),
            fontsize=10.5,
            color=INK,
            va="top",
            linespacing=1.4,
        )
        ax = fig.add_axes([0.10, 0.46, 0.80, 0.29])
        ax.plot(
            interpolation_years,
            interpolation_values,
            color=TEAL,
            lw=2.5,
            marker="o",
            label="linear annual values",
        )
        ax.scatter(
            [2025, 2030],
            [pv_add[2025], pv_add[2030]],
            s=80,
            color=NAVY,
            zorder=4,
            label="REMIND anchors",
        )
        for year, value in zip(interpolation_years, interpolation_values, strict=True):
            ax.text(year, value + 0.16, f"{value:.2f}", ha="center", fontsize=8)
        ax.set_ylabel("DEU PV additions (GW/yr)")
        ax.set_xticks(interpolation_years)
        ax.grid(axis="y", alpha=0.2)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, loc="upper left")
        box(
            fig,
            (0.07, 0.27, 0.86, 0.10),
            "Concrete example",
            f"PV additions rise from {pv_add[2025]:.3f} GW/yr in 2025 to {pv_add[2030]:.3f} GW/yr in 2030. The resulting 2028 value is {interpolation_values[3]:.3f} GW/yr.",
            BLUE,
        )
        bullets(
            fig,
            [
                f"Over the same interval, total DEU PV stock rises from {pv_stock[2025]:.1f} to {pv_stock[2030]:.1f} GW.",
                "Advantage: the annual sequence is reproducible and preserves every source anchor.",
                "Drawback: real construction is lumpy; the straight line adds detail the IAM does not contain.",
            ],
            0.08,
            0.20,
            width=84,
            size=9,
            gap=0.04,
        )
        pdf.savefig(fig)
        plt.close(fig)

        # 6 — survival and opening prior
        fig = base_page("5. Apply lifetime and survival assumptions", 6)
        fig.text(
            0.07,
            0.84,
            wrapped(
                "For energy-conversion equipment, REMIND's lifetime variable is a maximum lifetime, not an average. The documented survival curve declines slowly at first and reaches zero at that maximum.",
                92,
            ),
            fontsize=10.5,
            color=INK,
            va="top",
            linespacing=1.4,
        )
        ages = np.linspace(0, pv_lifetime, 200)
        survival = np.maximum(0, 1 - (ages / pv_lifetime) ** 4)
        ax1 = fig.add_axes([0.09, 0.50, 0.38, 0.25])
        ax1.plot(ages, survival * 100, color=BLUE, lw=2.5)
        for age in (10, 20, 30):
            value = max(0, 1 - (age / pv_lifetime) ** 4) * 100
            ax1.scatter(age, value, color=TEAL)
            ax1.text(age, value + 5, f"{value:.1f}%", ha="center", fontsize=8)
        ax1.set_xlabel("age (years)")
        ax1.set_ylabel("surviving share")
        ax1.set_title(
            f"DEU PV: maximum = {pv_lifetime:.0f} years", loc="left", color=NAVY, weight="bold"
        )
        ax1.spines[["top", "right"]].set_visible(False)
        ax1.grid(alpha=0.15)
        ax2 = fig.add_axes([0.55, 0.50, 0.38, 0.25])
        ax2.plot(opening["cohort_year"], opening["value"] * 100, color=ORANGE, lw=2.2)
        ax2.fill_between(opening["cohort_year"], opening["value"] * 100, color=ORANGE, alpha=0.2)
        ax2.set_xlabel("assumed entry year")
        ax2.set_ylabel("share of 2005 stock")
        ax2.set_title("Opening PV composition is a prior", loc="left", color=NAVY, weight="bold")
        ax2.spines[["top", "right"]].set_visible(False)
        ax2.grid(alpha=0.15)
        box(
            fig,
            (0.07, 0.30, 0.40, 0.12),
            "What the lifetime means",
            f"For a {pv_lifetime:.0f}-year maximum, mean life is 4/5 × {pv_lifetime:.0f} = {0.8 * pv_lifetime:.0f} years. About {100 * (1 - (20 / pv_lifetime) ** 4):.1f}% survives to age 20.",
            BLUE,
        )
        box(
            fig,
            (0.53, 0.30, 0.40, 0.12),
            "What we do not know",
            "REMIND gives the 2005 total stock but not its construction-year mix. A stationary historical-inflow shape initializes that mix and is labelled 'prior' in every output row.",
            ORANGE,
        )
        fig.text(
            0.07,
            0.20,
            wrapped(
                "Vehicles use the supplied REMIND service-life values as fixed retirement ages: 20 years for four-wheel passenger vehicles and 15 years for buses and trucks. This is explicit but less realistic than an observed vehicle survival distribution.",
                94,
            ),
            fontsize=9.7,
            color=INK,
            va="top",
            linespacing=1.4,
        )
        pdf.savefig(fig)
        plt.close(fig)

        # 7 — reconciliation
        fig = base_page("6. Make stocks, additions and retirements agree", 7)
        fig.text(
            0.07,
            0.84,
            wrapped(
                "Sometimes the reported stock path, reported additions and assumed survival cannot all be true at the same time. The run always keeps stock anchors exact. It keeps additions exact when feasible and otherwise reports a penalized adjustment.",
                92,
            ),
            fontsize=10.5,
            color=INK,
            va="top",
            linespacing=1.4,
        )
        ax1 = fig.add_axes([0.09, 0.47, 0.38, 0.28])
        ax1.bar(["exact", "penalized"], [exact_count, penalized_count], color=[TEAL, ORANGE])
        for i, value in enumerate((exact_count, penalized_count)):
            ax1.text(i, value + 3, str(value), ha="center", fontsize=11, weight="bold")
        ax1.set_ylim(0, max(exact_count, penalized_count) + 15)
        ax1.set_title("159 region-assets", loc="left", color=NAVY, weight="bold")
        ax1.spines[["top", "right", "left"]].set_visible(False)
        ax1.tick_params(axis="y", left=False, labelleft=False)
        ax2 = fig.add_axes([0.55, 0.47, 0.38, 0.28])
        years = offshore_flow["anchor"].to_numpy()
        ax2.plot(years, offshore_flow["target_rate"], marker="o", color=NAVY, label="reported")
        ax2.plot(
            years, offshore_flow["reconstructed_rate"], marker="s", color=ORANGE, label="reconciled"
        )
        ax2.set_title("DEU offshore wind additions", loc="left", color=NAVY, weight="bold")
        ax2.set_ylabel("GW/yr")
        ax2.spines[["top", "right"]].set_visible(False)
        ax2.grid(alpha=0.15)
        ax2.legend(frameon=False, fontsize=8)
        box(
            fig,
            (0.07, 0.27, 0.40, 0.12),
            "Exact example: DEU PV",
            f"All sampled additions are feasible. The 2025 rate stays {pv_flow.loc[pv_flow.anchor.eq(2025), 'reconstructed_rate'].iloc[0]:.3f} GW/yr, and the maximum stock-anchor error is {pv_diag['stock_anchor_max_absolute_residual']:.2e} GW.",
            TEAL,
        )
        box(
            fig,
            (0.53, 0.27, 0.40, 0.12),
            "Adjusted example: offshore wind",
            f"At 2010, reported additions are {offshore_flow.loc[offshore_flow.anchor.eq(2010), 'target_rate'].iloc[0]:.3f} GW/yr but the reconciled rate is effectively zero. Total absolute anchor-rate adjustment is {offshore_diag['actual_sum_absolute_rate_residual']:.3f} GW/yr.",
            ORANGE,
        )
        fig.text(
            0.07,
            0.18,
            wrapped(
                f"Across the run, {exact_count} cases preserve both stock and addition constraints exactly; {penalized_count} preserve stock anchors and expose addition discrepancies. The largest KKT optimality residual is {max_kkt:.2e}.",
                94,
            ),
            fontsize=9.8,
            color=INK,
            va="top",
            linespacing=1.4,
        )
        pdf.savefig(fig)
        plt.close(fig)

        # 8 — output vintages
        fig = base_page("7. Read the resulting vintage composition", 8)
        fig.text(
            0.07,
            0.84,
            wrapped(
                "The final product says how much of an asset operating in a given year belongs to each entry-year cohort. Below, five-year cohort groups make the detailed annual output easier to read.",
                92,
            ),
            fontsize=10.5,
            color=INK,
            va="top",
            linespacing=1.4,
        )
        ax = fig.add_axes([0.10, 0.43, 0.80, 0.32])
        all_periods = sorted(set(grouped_pv.index) | set(grouped_bev.index))
        x = np.arange(len(all_periods))
        width = 0.37
        pv_values = [grouped_pv.get(period, 0) for period in all_periods]
        bev_values = [grouped_bev.get(period, 0) for period in all_periods]
        ax.bar(x - width / 2, pv_values, width, label="solar PV", color=BLUE)
        ax.bar(x + width / 2, bev_values, width, label="passenger BEV", color=TEAL)
        ax.set_xticks(x, all_periods, rotation=35, ha="right")
        ax.set_ylabel("share of 2050 stock (%)")
        ax.set_title("DEU vintage mix in 2050", loc="left", color=NAVY, weight="bold")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.15)
        ax.legend(frameon=False)
        box(
            fig,
            (0.07, 0.24, 0.40, 0.12),
            "PV example",
            f"Cohorts from 2035–2039 provide {grouped_pv.get('2035–2039', 0):.1f}% of 2050 PV stock. The single 2038 cohort is {float(sample.at['stock_share', 'value']) * 100:.2f}% or {float(sample.at['stock', 'value']):.2f} GW.",
            BLUE,
        )
        box(
            fig,
            (0.53, 0.24, 0.40, 0.12),
            "BEV example",
            f"Passenger-BEV cohorts from 2035–2039 provide {grouped_bev.get('2035–2039', 0):.1f}% of the 2050 fleet. Fixed 20-year retirement means no pre-2030 cohort survives here.",
            TEAL,
        )
        fig.text(
            0.07,
            0.16,
            wrapped(
                "The Parquet table stores annual rows for stock, stock share, service share, additions, natural retirements and additional retirements. Each row also says whether its cohort comes from an IAM addition, an observation, or an opening prior.",
                94,
            ),
            fontsize=9.6,
            color=INK,
            va="top",
            linespacing=1.4,
        )
        pdf.savefig(fig)
        plt.close(fig)

        # 9 — pros and cons
        fig = base_page(
            "8. Advantages and inconveniences",
            9,
            "The method is useful precisely because its strengths and limitations are visible",
        )
        box(
            fig,
            (0.07, 0.50, 0.40, 0.30),
            "Advantages",
            "• Converts existing IAM outputs into a cohort structure without inventing a separate scenario.\n\n• Prevents parent/child double counting.\n\n• Preserves stock anchors and records every adjusted addition constraint.\n\n• Produces a sparse, checksum-bound file that premise can consume separately.\n\n• Makes assumptions and solver residuals auditable.",
            TEAL,
            14,
            9.5,
        )
        box(
            fig,
            (0.53, 0.50, 0.40, 0.30),
            "Inconveniences / drawbacks",
            "• Opening vintages are priors, not measurements.\n\n• Straight-line interpolation hides real year-to-year construction volatility.\n\n• Lifetime rules omit refurbishment and component replacement.\n\n• Penalized cases do not preserve reported additions exactly.\n\n• Proportional additional retirement is a modelling choice, not observed scrappage.",
            ORANGE,
            14,
            9.5,
        )
        fig.text(
            0.07, 0.42, "What the validation result means", fontsize=13, weight="bold", color=NAVY
        )
        stat_card(fig, 0.07, 0.28, "0", "numerical failures", TEAL)
        stat_card(fig, 0.285, 0.28, "159", "assets with warning status", ORANGE)
        stat_card(fig, 0.50, 0.28, str(len(report["warnings"])), "explicit run warnings", RED)
        stat_card(fig, 0.715, 0.28, f"{max_balance:.1e}", "largest balance residual", BLUE)
        fig.text(
            0.07,
            0.19,
            wrapped(
                "All 159 assets are marked 'warning' because source precision and opening-prior dependence are scientific cautions. This is different from a failed stock balance: numerical checks passed.",
                94,
            ),
            fontsize=10,
            color=INK,
            va="top",
            linespacing=1.4,
        )
        fallback_count = sum(
            "SLSQP" in name for name in solver_counts for _ in range(solver_counts[name])
        )
        fig.text(
            0.07,
            0.11,
            f"Solver note: {len(annual) - fallback_count} fits used OSQP; {fallback_count} penalized fits used the independently checked SLSQP fallback.",
            fontsize=8.8,
            color=MUTED,
        )
        pdf.savefig(fig)
        plt.close(fig)

        # 10 — practical use
        fig = base_page("9. What is ready now — and what comes next?", 10)
        fig.text(0.07, 0.84, "Safe interpretation", fontsize=14, weight="bold", color=TEAL)
        bullets(
            fig,
            [
                "Use the output as a transparent estimate of the age composition implied by REMIND stocks, additions, lifetimes and the declared opening prior.",
                "Use it to vary infrastructure burdens by construction year in premise, while keeping each asset, region and scenario explicit.",
                "Use validation.json and the processing report to screen penalized additions and prior-dependent results before downstream analysis.",
            ],
            0.08,
            0.80,
            width=83,
            gap=0.06,
        )
        fig.text(0.07, 0.57, "Do not claim", fontsize=14, weight="bold", color=RED)
        bullets(
            fig,
            [
                "Do not describe these cohorts as observed historical installations.",
                "Do not combine reporting totals with their mapped children, and do not silently assign a lifetime to the five ambiguous or five missing-lifetime capacity series.",
                "Do not hide the 85 penalized stock/addition cases or treat proportional early retirement as measured disposal.",
            ],
            0.08,
            0.53,
            width=83,
            size=9,
            gap=0.04,
        )
        box(
            fig,
            (0.07, 0.17, 0.86, 0.12),
            "Recommended next improvements",
            "1) add observed opening-vintage evidence where available; 2) resolve the ten ambiguous or missing lifetime mappings; 3) review the largest addition residuals; 4) define explicit premise asset-to-inventory bindings; 5) run sensitivity cases for lifetime and early-retirement assumptions.",
            ORANGE,
            12,
            9.5,
        )
        box(
            fig,
            (0.07, 0.05, 0.86, 0.09),
            "Delivered files",
            f"{parquet_rows:,} rows in vintages.parquet ({parquet_mb:.2f} MB), with datapackage.json and validation.json. The inventory classifies {len(inventory)} source series. Overall status: {validation['status'].upper()} for evidence and precision cautions, with no numerical failure.",
            BLUE,
            12,
            8.8,
        )
        pdf.savefig(fig)
        plt.close(fig)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    generate(parse_args())
