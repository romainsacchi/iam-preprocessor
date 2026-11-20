"""Immutable evidence manifests and observation-to-IAM harmonization."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .exceptions import DataValidationError
from .io import sha256_file

MANIFEST_FIELDS = {
    "source_id",
    "url",
    "version",
    "observation_year",
    "downloaded_at",
    "sha256",
    "license",
    "adapter_version",
    "path",
}
OBSERVATION_FIELDS = {
    "stable_id",
    "asset",
    "country",
    "observation_year",
    "cohort_year",
    "value",
    "unit",
    "quantity_basis",
}


def load_evidence_manifest(path):
    """Validate an evidence manifest and every immutable local raw file."""
    source = Path(path).resolve()
    try:
        if source.suffix.lower() == ".json":
            manifest = json.loads(source.read_text(encoding="utf-8"))
        else:
            manifest = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise DataValidationError(f"Cannot read evidence manifest: {source}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise DataValidationError("Only evidence manifest schema_version 1 is supported.")
    records = manifest.get("sources")
    if not isinstance(records, list) or not records:
        raise DataValidationError("Evidence manifest must contain source records.")
    identifiers = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != MANIFEST_FIELDS:
            raise DataValidationError(
                f"Evidence source fields must be exactly {sorted(MANIFEST_FIELDS)}."
            )
        if record["source_id"] in identifiers:
            raise DataValidationError(f"Duplicate evidence source_id: {record['source_id']}")
        identifiers.add(record["source_id"])
        if not all(
            isinstance(record[field], str) and record[field].strip()
            for field in MANIFEST_FIELDS - {"observation_year"}
        ):
            raise DataValidationError("Evidence manifest text fields cannot be empty.")
        if not isinstance(record["observation_year"], int):
            raise DataValidationError("Evidence observation_year must be an integer.")
        local = (source.parent / record["path"]).resolve()
        if not local.is_relative_to(source.parent):
            raise DataValidationError("Evidence paths must remain inside the manifest directory.")
        if not local.is_file() or sha256_file(local) != record["sha256"]:
            raise DataValidationError(
                f"Missing or checksum-mismatched evidence source: {record['source_id']}"
            )
    return manifest


def evidence_descriptor(path):
    """Return package-safe provenance after validating all evidence bytes."""
    if path is None:
        return None
    manifest = load_evidence_manifest(path)
    return {
        "manifest_sha256": sha256_file(path),
        "sources": [
            {key: value for key, value in record.items() if key not in {"path"}}
            for record in manifest["sources"]
        ],
    }


def harmonize_observations(
    records,
    *,
    asset,
    countries,
    observation_year,
    iam_stock,
    unit,
    quantity_basis,
    mode,
    ratio_bounds=(0.5, 2.0),
):
    """Reconcile standardized source records to one IAM opening stock.

    ``composition_proxy`` rescales the observed composition to the IAM total.
    ``partial_observation`` retains observed amounts and assigns the uncovered
    IAM remainder to a dedicated undated legacy row.
    """
    frame = pd.DataFrame(records).copy()
    missing = OBSERVATION_FIELDS - set(frame.columns)
    if missing:
        raise DataValidationError(f"Observation records are missing fields: {sorted(missing)}")
    if mode not in {"composition_proxy", "partial_observation"}:
        raise DataValidationError(
            "Observation mode must be composition_proxy or partial_observation."
        )
    if not np.isfinite(iam_stock) or iam_stock < 0:
        raise DataValidationError("IAM opening stock must be finite and nonnegative.")
    selected = frame.loc[frame["asset"].eq(asset) & frame["country"].isin(set(countries))].copy()
    if selected.empty:
        raise DataValidationError("No evidence records match the requested asset and countries.")
    if selected["stable_id"].isna().any() or selected.duplicated("stable_id").any():
        raise DataValidationError("Evidence records require unique stable identifiers.")
    if set(selected["observation_year"]) != {observation_year}:
        raise DataValidationError("Evidence observation year does not match the requested year.")
    if set(selected["unit"]) != {unit} or set(selected["quantity_basis"]) != {quantity_basis}:
        raise DataValidationError("Evidence unit or gross/net capacity basis does not match.")
    values = pd.to_numeric(selected["value"], errors="coerce").to_numpy(float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise DataValidationError("Evidence values must be finite and nonnegative.")
    cohort = pd.to_numeric(selected["cohort_year"], errors="coerce")
    if (cohort.dropna() > observation_year).any():
        raise DataValidationError("Observed cohorts cannot be in the future.")
    observed_total = float(values.sum())
    ratio = observed_total / iam_stock if iam_stock else (1.0 if observed_total == 0 else np.inf)
    low, high = ratio_bounds
    if not 0 < low <= high or not low <= ratio <= high:
        raise DataValidationError(
            f"Observed/IAM stock ratio {ratio:.6g} is outside approved bounds [{low}, {high}]."
        )
    if mode == "partial_observation" and observed_total > iam_stock * (1 + 1e-10):
        raise DataValidationError("Partial observations exceed the IAM opening stock.")
    # A proxy supplies an age mix that is scaled to the IAM total.
    scale = iam_stock / observed_total if mode == "composition_proxy" and observed_total else 1.0
    selected["amount"] = values * scale
    dated = selected["cohort_year"].notna()
    rows = [
        {
            "cohort_year": int(row.cohort_year) if pd.notna(row.cohort_year) else None,
            "amount": float(row.amount),
            "evidence_basis": "observed" if pd.notna(row.cohort_year) else "legacy_unallocated",
        }
        for row in selected.itertuples()
        if row.amount > 0
    ]
    if mode == "partial_observation" and iam_stock > observed_total:
        # Keep uncovered stock visible even though it has no known build year.
        rows.append(
            {
                "cohort_year": None,
                "amount": float(iam_stock - observed_total),
                "evidence_basis": "legacy_unallocated",
            }
        )
    dated_amount = float(selected.loc[dated, "amount"].sum())
    return rows, {
        "mode": mode,
        "countries": sorted(set(countries)),
        "observation_year": observation_year,
        "observed_total": observed_total,
        "iam_stock": float(iam_stock),
        "observed_to_iam_ratio": float(ratio),
        "scaling_factor": float(scale),
        "known_vintage_share": dated_amount / iam_stock if iam_stock else 0.0,
        "unallocated_legacy_share": 1 - dated_amount / iam_stock if iam_stock else 0.0,
        "stable_identifiers": len(selected),
    }
