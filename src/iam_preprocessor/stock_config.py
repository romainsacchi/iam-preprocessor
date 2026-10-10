"""Strict, opt-in configuration for reconstructed IAM stock vintages."""

from __future__ import annotations

import math
import re
from pathlib import Path

import yaml

from .exceptions import DataValidationError


def fields(obj, required, optional=()):
    """Reject missing or misspelled configuration fields."""
    if not isinstance(obj, dict):
        raise DataValidationError("Expected a configuration mapping.")
    missing, extra = set(required) - obj.keys(), obj.keys() - set(required) - set(optional)
    if missing or extra:
        raise DataValidationError(
            f"Configuration fields: missing={sorted(missing)}, extra={sorted(extra)}"
        )


def positive(value, name, *, zero=False):
    """Validate numeric parameters without accepting YAML booleans."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or (value < 0 if zero else value <= 0)
    ):
        raise DataValidationError(
            f"{name} must be finite and {'nonnegative' if zero else 'positive'}."
        )


def calendar_year(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1000 <= value <= 2200:
        raise DataValidationError(f"Invalid calendar year: {value!r}")
    return value


def nonempty(value, name):
    if not isinstance(value, str) or not value.strip():
        raise DataValidationError(f"{name} must be a nonempty string.")


def selector(value):
    fields(value, ("variable", "unit"))
    for key in value:
        nonempty(value[key], key)


def load_stock_config(path):
    """Load a versioned YAML config; resolve observation paths relative to it."""
    source = Path(path).resolve()
    try:
        config = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise DataValidationError(f"Cannot read stock configuration: {source}") from exc
    fields(config, ("schema_version", "model", "scenario", "reference_year", "end_year", "assets"))
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise DataValidationError("Only stock configuration schema_version 1 is supported.")
    for key in ("model", "scenario"):
        nonempty(config[key], key)
    ref, end = (calendar_year(config[k]) for k in ("reference_year", "end_year"))
    if not 2005 <= ref < end <= 2100:
        raise DataValidationError("Require 2005 <= reference_year < end_year <= 2100 for premise.")
    if not isinstance(config["assets"], list) or not config["assets"]:
        raise DataValidationError("Configure at least one stock asset.")
    identities = set()
    units_by_id = {}
    for asset in config["assets"]:
        fields(
            asset,
            (
                "id",
                "region",
                "stock",
                "inflow",
                "inflow_timing",
                "lifetime",
                "initial",
                "mode",
                "exit_policy",
                "service_weighting",
            ),
            ("service", "annualisation"),
        )
        if not isinstance(asset["id"], str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]*", asset["id"]
        ):
            raise DataValidationError("Asset ids must contain lowercase letters, digits, _ or -.")
        nonempty(asset["region"], "region")
        key = asset["id"], asset["region"]
        if key in identities:
            raise DataValidationError(f"Duplicate asset/region: {key}")
        identities.add(key)
        for key in ("stock", "inflow", "service"):
            if key in asset:
                selector(asset[key])
        units = (asset["stock"]["unit"], asset.get("service", {}).get("unit"))
        if asset["id"] in units_by_id and units_by_id[asset["id"]] != units:
            raise DataValidationError(
                "One asset id must have consistent units/service availability across regions."
            )
        units_by_id[asset["id"]] = units
        if asset["inflow"]["unit"] not in {asset["stock"]["unit"], asset["stock"]["unit"] + "/yr"}:
            raise DataValidationError("Stock and inflow units must use the same quantity scale.")
        if asset["mode"] not in ("stock", "inflow", "joint"):
            raise DataValidationError("mode must be stock, inflow or joint.")
        if asset["mode"] == "joint":
            annual = asset.get("annualisation")
            fields(
                annual, ("inflow_constraints", "reference_weight", "inflow_weight", "provenance")
            )
            if annual["inflow_constraints"] not in ("strict", "penalized"):
                raise DataValidationError("Choose strict or penalized inflow constraints.")
            positive(annual["reference_weight"], "annualisation reference_weight")
            positive(annual["inflow_weight"], "annualisation inflow_weight")
            nonempty(annual["provenance"], "annualisation provenance")
        elif "annualisation" in asset:
            raise DataValidationError("annualisation configuration requires joint mode.")
        if asset["exit_policy"] not in ("error", "proportional"):
            raise DataValidationError("exit_policy must be error or proportional.")
        if asset["mode"] == "inflow" and asset["exit_policy"] != "error":
            raise DataValidationError(
                "Inflow mode has no inferred additional exits; use exit_policy: error."
            )
        timing = asset["inflow_timing"]
        fields(timing, ("kind", "provenance"), ("periods",))
        nonempty(timing["provenance"], "inflow timing provenance")
        if timing["kind"] == "reported_periods":
            if not isinstance(timing.get("periods"), list) or not timing["periods"]:
                raise DataValidationError(
                    "reported_periods requires explicit annual reporting windows."
                )
            for period in timing["periods"]:
                fields(period, ("anchor", "start", "end"))
                for value in period.values():
                    calendar_year(value)
                if period["start"] > period["end"]:
                    raise DataValidationError("Reporting period start must precede its end.")
        elif timing["kind"] != "sampled_annual" or "periods" in timing:
            raise DataValidationError("Choose sampled_annual or reported_periods inflow timing.")
        lifetime = asset["lifetime"]
        fields(
            lifetime,
            ("distribution", "initial_mean", "interpretation", "provenance"),
            ("mean", "source", "shape"),
        )
        if ("mean" in lifetime) == ("source" in lifetime):
            raise DataValidationError("Choose exactly one lifetime mean or IAM source.")
        for key in ("interpretation", "provenance"):
            nonempty(lifetime[key], key)
        positive(lifetime["initial_mean"], "initial_mean")
        if "mean" in lifetime:
            positive(lifetime["mean"], "mean")
        else:
            selector(lifetime["source"])
            if lifetime["source"]["unit"] != "years":
                raise DataValidationError("Lifetime source units must be years.")
        if lifetime["distribution"] == "weibull":
            positive(lifetime.get("shape"), "Weibull shape")
        elif lifetime["distribution"] != "fixed" or "shape" in lifetime:
            raise DataValidationError("Choose fixed lifetime or Weibull with an explicit shape.")
        initial = asset["initial"]
        fields(initial, ("kind", "provenance"), ("file", "maximum_age"))
        nonempty(initial["provenance"], "initial stock provenance")
        if initial["kind"] == "observed_shares":
            if "file" not in initial or "maximum_age" in initial:
                raise DataValidationError("observed_shares requires an observation CSV file.")
            nonempty(initial["file"], "observation file")
            initial["file"] = str((source.parent / initial["file"]).resolve())
        elif initial["kind"] == "equilibrium":
            age = initial.get("maximum_age")
            if type(age) is not int or not 1 <= age <= 150 or "file" in initial:
                raise DataValidationError(
                    "Equilibrium initialization needs maximum_age from 1 to 150."
                )
        else:
            raise DataValidationError("Initial stock must use observed_shares or equilibrium.")
        service = asset["service_weighting"]
        fields(
            service,
            ("kind", "annual_age_decay", "provenance"),
            (
                "future_factor",
                "new_cohort_exposure",
                "maximum_service_per_stock",
                "age_profile_file",
                "tail_policy",
            ),
        )
        positive(service["annual_age_decay"], "annual_age_decay", zero=True)
        positive(service.get("new_cohort_exposure", 1.0), "new_cohort_exposure", zero=True)
        if service.get("new_cohort_exposure", 1.0) > 1:
            raise DataValidationError("new_cohort_exposure must be between zero and one.")
        if "maximum_service_per_stock" in service:
            positive(service["maximum_service_per_stock"], "maximum_service_per_stock")
            if "service" not in asset:
                raise DataValidationError("Service bounds require an IAM service target.")
        nonempty(service["provenance"], "service weighting provenance")
        if service["kind"] == "observed_factors":
            positive(service.get("future_factor"), "future_factor")
            if initial["kind"] != "observed_shares":
                raise DataValidationError(
                    "Observed service factors require observed initial cohorts."
                )
        elif service["kind"] == "age_profile":
            nonempty(service.get("age_profile_file"), "age profile file")
            if (
                service.get("tail_policy") != "hold_last"
                or "future_factor" in service
                or service["annual_age_decay"] != 0
            ):
                raise DataValidationError(
                    "Age profiles require explicit hold_last tails and zero extra decay."
                )
            service["age_profile_file"] = str(
                (source.parent / service["age_profile_file"]).resolve()
            )
            from .stock_usage import read_age_profile

            read_age_profile(service["age_profile_file"])
        elif service["kind"] != "equal" or "future_factor" in service:
            raise DataValidationError(
                "Service weighting must be equal, observed_factors or age_profile."
            )
        if service["kind"] != "age_profile" and (
            "age_profile_file" in service or "tail_policy" in service
        ):
            raise DataValidationError(
                "Age profile fields are only valid with age_profile weighting."
            )
    return config
