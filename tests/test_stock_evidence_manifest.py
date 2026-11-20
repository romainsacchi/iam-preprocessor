import hashlib

import pandas as pd
import pytest
import yaml

from iam_preprocessor.exceptions import DataValidationError
from iam_preprocessor.stock_evidence import harmonize_observations, load_evidence_manifest


def evidence_manifest(tmp_path):
    raw = tmp_path / "raw.csv"
    raw.write_text("id,value\na,1\n")
    manifest = {
        "schema_version": 1,
        "sources": [
            {
                "source_id": "example-2020",
                "url": "https://example.org/archive/1",
                "version": "1",
                "observation_year": 2020,
                "downloaded_at": "2026-10-27",
                "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                "license": "CC-BY-4.0",
                "adapter_version": "1",
                "path": "raw.csv",
            }
        ],
    }
    path = tmp_path / "evidence.yaml"
    path.write_text(yaml.safe_dump(manifest))
    return path, raw


def observations():
    return pd.DataFrame(
        [
            {
                "stable_id": "DE-a",
                "asset": "pv",
                "country": "DEU",
                "observation_year": 2020,
                "cohort_year": 2010,
                "value": 4,
                "unit": "GW",
                "quantity_basis": "nameplate",
            },
            {
                "stable_id": "DE-b",
                "asset": "pv",
                "country": "DEU",
                "observation_year": 2020,
                "cohort_year": None,
                "value": 1,
                "unit": "GW",
                "quantity_basis": "nameplate",
            },
        ]
    )


def harmonize(frame, **changes):
    options = dict(
        asset="pv",
        countries=["DEU"],
        observation_year=2020,
        iam_stock=10,
        unit="GW",
        quantity_basis="nameplate",
        mode="composition_proxy",
    )
    options.update(changes)
    return harmonize_observations(frame, **options)


def test_manifest_verifies_exact_raw_bytes(tmp_path):
    manifest, raw = evidence_manifest(tmp_path)
    assert load_evidence_manifest(manifest)["sources"][0]["source_id"] == "example-2020"
    raw.write_text("changed")
    with pytest.raises(DataValidationError, match="checksum"):
        load_evidence_manifest(manifest)


def test_composition_proxy_reports_scaling_and_keeps_unknown_vintage_explicit():
    rows, diagnostics = harmonize(observations())
    assert sum(row["amount"] for row in rows) == 10
    assert diagnostics["observed_to_iam_ratio"] == 0.5
    assert diagnostics["scaling_factor"] == 2
    assert diagnostics["known_vintage_share"] == 0.8
    assert any(row["cohort_year"] is None for row in rows)


def test_partial_observation_adds_unallocated_iam_remainder():
    rows, diagnostics = harmonize(observations(), mode="partial_observation")
    assert sum(row["amount"] for row in rows) == 10
    assert diagnostics["scaling_factor"] == 1
    assert sum(row["amount"] for row in rows if row["cohort_year"] is None) == 6


@pytest.mark.parametrize("problem", ["duplicate", "year", "basis", "ratio"])
def test_harmonization_rejects_ambiguous_or_incommensurate_evidence(problem):
    frame = observations()
    options = {}
    if problem == "duplicate":
        frame.loc[1, "stable_id"] = frame.loc[0, "stable_id"]
    elif problem == "year":
        frame.loc[1, "observation_year"] = 2019
    elif problem == "basis":
        frame.loc[1, "quantity_basis"] = "net"
    else:
        options["iam_stock"] = 100
    with pytest.raises(DataValidationError):
        harmonize(frame, **options)
