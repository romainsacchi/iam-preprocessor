"""Strict, opt-in configuration for reconstructed IAM stock vintages."""

from __future__ import annotations

import math
import re
from pathlib import Path

import yaml

from .exceptions import DataValidationError
from .lifetime import canonical_distribution, lifetime_parameter


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
    """Return a valid calendar year from a YAML integer."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1000 <= value <= 2200:
        raise DataValidationError(f"Invalid calendar year: {value!r}")
    return value


def nonempty(value, name):
    """Check that a named text field contains more than whitespace."""
    if not isinstance(value, str) or not value.strip():
        raise DataValidationError(f"{name} must be a nonempty string.")


def selector(value):
    """Validate the exact variable name and unit used to find an IAM row."""
    fields(value, ("variable", "unit"))
    for key in value:
        nonempty(value[key], key)


def load_stock_config(path):
    """Load a YAML file and resolve any input paths relative to its directory."""
    source = Path(path).resolve()
    try:
        config = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise DataValidationError(f"Cannot read stock configuration: {source}") from exc
    return validate_stock_config(config, source=source)


def validate_stock_config(config, *, source):
    """Check the settings and replace relative input paths with absolute paths."""
    source = Path(source).resolve()
    fields(
        config,
        ("schema_version", "model", "scenario", "reference_year", "end_year", "assets"),
        ("registries", "evidence_manifest"),
    )
    if type(config["schema_version"]) is not int or config["schema_version"] not in (1, 2):
        raise DataValidationError("Only stock configuration schema_version 1 or 2 is supported.")
    for key in ("model", "scenario"):
        nonempty(config[key], key)
    ref, end = (calendar_year(config[k]) for k in ("reference_year", "end_year"))
    if not 2005 <= ref < end <= 2100:
        raise DataValidationError("Require 2005 <= reference_year < end_year <= 2100 for premise.")
    if not isinstance(config["assets"], list) or not config["assets"]:
        raise DataValidationError("Configure at least one stock asset.")
    if "registries" in config:
        from .registry_provenance import verify_registry_provenance

        verify_registry_provenance(config["registries"])
    if "evidence_manifest" in config:
        nonempty(config["evidence_manifest"], "evidence_manifest")
        config["evidence_manifest"] = str((source.parent / config["evidence_manifest"]).resolve())
        from .stock_evidence import load_evidence_manifest

        load_evidence_manifest(config["evidence_manifest"])
    # The output groups regional results by asset ID, so their units must agree.
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
        _validate_reconstruction(asset)
        _validate_inflow_timing(asset["inflow_timing"])
        _validate_lifetime(asset["lifetime"])
        _validate_initial_stock(asset["initial"], source, ref, config["schema_version"])
        _validate_service_weighting(asset, source)
    return config


def _validate_reconstruction(asset):
    """Validate which IAM values guide the fit and how extra exits are assigned."""
    if asset["mode"] not in ("stock", "inflow", "stock_flow", "joint"):
        raise DataValidationError("mode must be stock, inflow, stock_flow or joint.")
    if asset["mode"] == "joint":
        if asset["exit_policy"] not in {"error", "proportional"}:
            raise DataValidationError(
                "Joint mode supports only error or proportional exit allocation."
            )
        annual = asset.get("annualisation")
        fields(annual, ("inflow_constraints", "reference_weight", "inflow_weight", "provenance"))
        if annual["inflow_constraints"] not in ("strict", "penalized"):
            raise DataValidationError("Choose strict or penalized inflow constraints.")
        positive(annual["reference_weight"], "annualisation reference_weight")
        positive(annual["inflow_weight"], "annualisation inflow_weight")
        nonempty(annual["provenance"], "annualisation provenance")
    elif "annualisation" in asset:
        raise DataValidationError("annualisation configuration requires joint mode.")
    if asset["exit_policy"] not in (
        "error",
        "proportional",
        "oldest_first",
        "remove_by_hazard",
    ):
        raise DataValidationError(
            "exit_policy must be error, proportional, oldest_first or remove_by_hazard."
        )
    if asset["mode"] == "inflow" and asset["exit_policy"] != "error":
        raise DataValidationError(
            "Inflow mode has no inferred additional exits; use exit_policy: error."
        )


def _validate_inflow_timing(timing):
    """Check how the IAM reports additions and which years each value covers."""
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


def _validate_lifetime(lifetime):
    """Check that the chosen lifetime curve has the parameters it needs."""
    fields(
        lifetime,
        ("distribution", "interpretation", "provenance"),
        ("initial_mean", "mean", "initial_maximum", "maximum", "source", "shape"),
    )
    for key in ("interpretation", "provenance"):
        nonempty(lifetime[key], key)
    distribution = canonical_distribution(lifetime["distribution"])
    # The quartic curve stops at a specified age. The other curves use a mean.
    if lifetime_parameter(distribution) == "maximum":
        if "initial_maximum" not in lifetime or any(
            key in lifetime for key in ("initial_mean", "mean", "shape")
        ):
            raise DataValidationError(
                "Quartic lifetimes require initial_maximum and do not accept mean or shape."
            )
        if ("maximum" in lifetime) == ("source" in lifetime):
            raise DataValidationError("Choose exactly one maximum lifetime or IAM source.")
        positive(lifetime["initial_maximum"], "initial_maximum")
        if "maximum" in lifetime:
            positive(lifetime["maximum"], "maximum")
    else:
        if "initial_mean" not in lifetime or any(
            key in lifetime for key in ("initial_maximum", "maximum")
        ):
            raise DataValidationError(
                "Fixed and Weibull lifetimes require initial_mean and do not accept maximum."
            )
        if ("mean" in lifetime) == ("source" in lifetime):
            raise DataValidationError("Choose exactly one lifetime mean or IAM source.")
        positive(lifetime["initial_mean"], "initial_mean")
        if "mean" in lifetime:
            positive(lifetime["mean"], "mean")
    if "source" in lifetime:
        selector(lifetime["source"])
        if lifetime["source"]["unit"] != "years":
            raise DataValidationError("Lifetime source units must be years.")
    if distribution == "weibull":
        positive(lifetime.get("shape"), "Weibull shape")
    elif "shape" in lifetime:
        raise DataValidationError("The shape parameter is used only for Weibull lifetimes.")


def _validate_initial_stock(initial, source, reference_year, schema_version):
    """Check the evidence or assumptions used for the opening stock."""
    fields(
        initial,
        ("kind", "provenance"),
        (
            "file",
            "maximum_age",
            "base_year",
            "base_kind",
            "acknowledge_prior",
            "evidence_kind",
        ),
    )
    nonempty(initial["provenance"], "initial stock provenance")
    # Observed shares supply the age mix directly. Both other methods assume a mix.
    if initial["kind"] == "observed_shares":
        if "file" not in initial or "maximum_age" in initial:
            raise DataValidationError("observed_shares requires an observation CSV file.")
        evidence_kind = initial.get("evidence_kind", "direct_observation")
        if evidence_kind not in {"direct_observation", "composition_proxy"}:
            raise DataValidationError(
                "Observed initial shares require evidence_kind direct_observation or "
                "composition_proxy."
            )
        nonempty(initial["file"], "observation file")
        initial["file"] = str((source.parent / initial["file"]).resolve())
    elif initial["kind"] == "equilibrium":
        if "evidence_kind" in initial:
            raise DataValidationError("evidence_kind is only valid for observed initial shares.")
        age = initial.get("maximum_age")
        if type(age) is not int or not 1 <= age <= 150 or "file" in initial:
            raise DataValidationError("Equilibrium initialization needs maximum_age from 1 to 150.")
        if schema_version >= 2 and initial.get("acknowledge_prior") is not True:
            raise DataValidationError(
                "Schema v2 equilibrium initialization requires acknowledge_prior: true."
            )
    elif initial["kind"] == "warm_start":
        if "evidence_kind" in initial:
            raise DataValidationError("evidence_kind is only valid for observed initial shares.")
        age, base = initial.get("maximum_age"), initial.get("base_year")
        if (
            initial.get("base_kind") != "equilibrium"
            or type(age) is not int
            or not 1 <= age <= 150
            or type(base) is not int
            or not 2005 <= base < reference_year
            or initial.get("acknowledge_prior") is not True
            or "file" in initial
        ):
            raise DataValidationError(
                "warm_start requires an acknowledged equilibrium base prior, maximum_age, "
                "and 2005 <= base_year < reference_year."
            )
    else:
        raise DataValidationError(
            "Initial stock must use observed_shares, equilibrium or warm_start."
        )


def _validate_service_weighting(asset, source):
    """Check how stock is converted into shares of service."""
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
        if asset["initial"]["kind"] != "observed_shares":
            raise DataValidationError("Observed service factors require observed initial cohorts.")
    elif service["kind"] == "age_profile":
        # The age profile already describes how service changes as the asset ages.
        nonempty(service.get("age_profile_file"), "age profile file")
        if (
            service.get("tail_policy") != "hold_last"
            or "future_factor" in service
            or service["annual_age_decay"] != 0
        ):
            raise DataValidationError(
                "Age profiles require explicit hold_last tails and zero extra decay."
            )
        service["age_profile_file"] = str((source.parent / service["age_profile_file"]).resolve())
        from .stock_usage import read_age_profile

        read_age_profile(service["age_profile_file"])
    elif service["kind"] != "equal" or "future_factor" in service:
        raise DataValidationError(
            "Service weighting must be equal, observed_factors or age_profile."
        )
    if service["kind"] != "age_profile" and (
        "age_profile_file" in service or "tail_policy" in service
    ):
        raise DataValidationError("Age profile fields are only valid with age_profile weighting.")
