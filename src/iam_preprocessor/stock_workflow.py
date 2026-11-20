"""List scenario variables and check the rows selected in the stock settings."""

from __future__ import annotations

from os.path import relpath
from pathlib import Path

import pandas as pd
import yaml

from .exceptions import DataValidationError, IamPreprocessorError
from .io import read_frame, scenario_identity, write_csv_atomic, year_columns
from .stock_config import load_stock_config, validate_stock_config
from .vintage_inputs import read_iam_series


def _years(frame, end_year):
    """List reported years up to the requested end year."""
    years = list(map(int, year_columns(frame)))
    if end_year is not None and not years[0] <= end_year <= years[-1]:
        raise DataValidationError("End year is outside the input time horizon.")
    return [year for year in years if end_year is None or year <= end_year]


def _mapped_inputs(frame, config, regions):
    """Check whether each configured stock input is present for its region."""
    rows = []
    by_region = dict(tuple(frame.groupby("Region", sort=False)))
    for asset in config["assets"]:
        region = asset["region"]
        if regions is not None and region not in regions:
            continue
        region_frame = by_region.get(region, frame.iloc[:0])
        selectors = {key: asset[key] for key in ("stock", "inflow", "service") if key in asset}
        if "source" in asset["lifetime"]:
            selectors["lifetime"] = asset["lifetime"]["source"]
        for role, selector in selectors.items():
            try:
                read_iam_series(region_frame, region, selector)
                status, detail = "available", ""
            except DataValidationError as exc:
                status, detail = "invalid", str(exc)
            rows.append(
                dict(
                    asset=asset["id"],
                    region=region,
                    role=role,
                    **selector,
                    status=status,
                    detail=detail,
                )
            )
    if not rows:
        raise DataValidationError("No configured stock assets match the requested regions.")
    return pd.DataFrame(rows)


def write_stock_inventory(
    source,
    destination,
    *,
    config_path=None,
    regions=None,
    end_year=None,
    overwrite=False,
):
    """List reported variables or check the selected rows in the stock settings."""
    frame = read_frame(source)
    if regions is not None:
        missing = set(regions) - set(frame["Region"])
        if missing:
            raise DataValidationError(f"Regions are absent from the scenario: {sorted(missing)}")
    if config_path is None:
        years = _years(frame, end_year)
        selected = frame if regions is None else frame.loc[frame["Region"].isin(regions)]
        inventory = selected[["Model", "Scenario", "Region", "Variable", "Unit"]].copy()
        inventory = inventory.assign(first_year=years[0], last_year=years[-1], status="reported")
    else:
        if end_year is not None:
            raise DataValidationError("Set the end year in the configuration for a mapped audit.")
        config = load_stock_config(config_path)
        if scenario_identity(frame) != (config["model"], config["scenario"]):
            raise DataValidationError("Configuration model and scenario do not match the input.")
        inventory = _mapped_inputs(frame, config, regions)
    return write_csv_atomic(inventory, destination, overwrite=overwrite), inventory


def write_stock_config(
    source,
    destination,
    *,
    mapping,
    regions=None,
    reference_year=None,
    end_year=None,
    overwrite=False,
):
    """Fill in IAM scenario details in the YAML and check the selected rows.

    Templates may omit model, scenario, schema version and years. The input table
    supplies the labels and default horizon. Each asset specifies its exact rows
    and scientific assumptions with the same fields as a stock configuration.
    """
    frame = read_frame(source)
    model, scenario = scenario_identity(frame)
    mapping, destination = Path(mapping), Path(destination)
    try:
        config = yaml.safe_load(mapping.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise DataValidationError(f"Cannot read stock mapping: {mapping}") from exc
    if not isinstance(config, dict):
        raise DataValidationError("A stock mapping must be a YAML mapping.")
    for key, value in (("model", model), ("scenario", scenario)):
        if config.setdefault(key, value) != value:
            raise DataValidationError(f"Stock mapping {key} does not match the input: {value!r}.")
    years = _years(frame, None)
    config.setdefault("schema_version", 2)
    config.setdefault("reference_year", max(2005, years[0]))
    config.setdefault("end_year", min(2100, years[-1]))
    if reference_year is not None:
        config["reference_year"] = reference_year
    if end_year is not None:
        config["end_year"] = end_year
    config = validate_stock_config(config, source=mapping)
    if config["reference_year"] < years[0] or config["end_year"] > years[-1]:
        raise DataValidationError("The configured years are outside the input time horizon.")
    if regions is not None:
        missing = set(regions) - {asset["region"] for asset in config["assets"]}
        if missing:
            raise DataValidationError(f"No asset mappings for regions: {sorted(missing)}")
        config["assets"] = [asset for asset in config["assets"] if asset["region"] in regions]
    audit = _mapped_inputs(frame, config, None)
    errors = audit.loc[audit["status"].eq("invalid"), "detail"]
    if not errors.empty:
        raise DataValidationError(f"Invalid stock mapping ({len(errors)} inputs). {errors.iloc[0]}")
    if destination.exists() and not overwrite:
        raise IamPreprocessorError(
            f"Output already exists: {destination}. Use --overwrite to replace it."
        )

    # Relative paths continue pointing at the same files when the YAML is moved.
    def rebase(item, key):
        """Make a configured input path relative to the new YAML file."""
        if key in item:
            item[key] = relpath(item[key], destination.resolve().parent)

    rebase(config, "evidence_manifest")
    for asset in config["assets"]:
        rebase(asset["initial"], "file")
        rebase(asset["service_weighting"], "age_profile_file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return destination, config
