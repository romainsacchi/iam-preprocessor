"""Exercise all eleven real profiles with explicit synthetic consumer inventories.

Use the paired premise feature checkout. Coefficients for the additional groups
are illustrative test constants, not recommended ecoinvent inventory bindings.
"""

import argparse
import importlib.util
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--premise-checkout", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    fixture_path = args.premise_checkout / "dev/stock_vintage/export_iam_enrichment_fixture.py"
    spec = importlib.util.spec_from_file_location("premise_fixture", fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    directory = args.directory.resolve()
    audit = json.loads((directory / "sector-observation-audit.json").read_text())
    fixture.ASSETS["passenger-liquids"] = ("EUR", "unit", "kilometer", 1 / 150000, 1000.0)
    for asset in audit["primary_assets"]:
        if asset not in fixture.ASSETS:
            fixture.ASSETS[asset] = ("USA", "unit", "kilowatt hour", 1e-8, 1000.0)
    if set(fixture.ASSETS) != set(audit["primary_assets"]):
        raise ValueError("Fixture registry does not match the reviewed asset catalogue")
    for varying in (False, True):
        result = fixture.export(
            directory / "runtime/plain",
            directory / "runtime/plain/REMIND_generic_SSP2-NPi2025_stock_vintages_report.json",
            directory / "integration" / ("varying" if varying else "constant"),
            varying=varying,
        )
        print(json.dumps({k: result[k] for k in ("package", "sha256", "varying_background")}))


if __name__ == "__main__":
    main()
