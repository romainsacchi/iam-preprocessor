from __future__ import annotations

import json

import pandas as pd
import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from iam_preprocessor.cli import app
from iam_preprocessor.crypto import decrypt_file, encrypt_file
from iam_preprocessor.exceptions import DataValidationError
from iam_preprocessor.image import prepare_image
from iam_preprocessor.io import read_frame


def test_crypto_roundtrip_uses_runtime_environment(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IAM_PREPROCESSOR_KEY", key)
    source = tmp_path / "plain.txt"
    encrypted = tmp_path / "encrypted.bin"
    recovered = tmp_path / "recovered.txt"
    source.write_text("scenario data", encoding="utf-8")
    encrypt_file(source, encrypted)
    decrypt_file(encrypted, recovered)
    assert recovered.read_text(encoding="utf-8") == "scenario data"
    assert key not in encrypted.read_bytes().decode("latin-1")


def test_crypto_roundtrip_loads_premise_key_from_dotenv(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PREMISE_KEY", raising=False)
    monkeypatch.delenv("IAM_PREPROCESSOR_KEY", raising=False)
    (tmp_path / ".env").write_text(f"PREMISE_KEY={key}\n", encoding="utf-8")
    source = tmp_path / "plain.txt"
    encrypted = tmp_path / "encrypted.bin"
    recovered = tmp_path / "recovered.txt"
    source.write_text("scenario data", encoding="utf-8")

    encrypt_file(source, encrypted)
    decrypt_file(encrypted, recovered)

    assert recovered.read_text(encoding="utf-8") == "scenario data"
    assert key not in encrypted.read_bytes().decode("latin-1")


def test_image_pipeline_writes_report_without_secrets(
    tmp_path, image_frame, sec_config, monkeypatch
):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("IAM_PREPROCESSOR_KEY", key)
    source = tmp_path / "IMAGE_test.csv"
    image_frame.to_csv(source, index=False)
    output = tmp_path / "output"
    encrypted = tmp_path / "encrypted"
    reports = prepare_image([source], output, sec_config, encrypt_to=encrypted)
    report = reports[0]
    payload = json.loads((output / "IMAGE_test_report.json").read_text())
    assert report.output_rows > report.input_rows
    assert payload["assumptions"]["bev_truck_sec_mj_per_tkm"]["Medium Truck"] == 1
    assert key not in json.dumps(payload)
    result = pd.read_csv(report.output_path, sep=";")
    assert (
        "Energy Service|Transportation|Freight|Medium Truck|Battery Electric"
        in result["Variable"].values
    )
    assert (encrypted / "IMAGE_test_filtered.csv").exists()


def test_cli_help_and_image_skip_bev(tmp_path):
    runner = CliRunner()
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    assert "image" in help_result.stdout
    assert "tiam-ucl" in help_result.stdout

    source = tmp_path / "simple.csv"
    pd.DataFrame(
        [
            {
                "Model": "IMAGE 3.4",
                "Scenario": "test",
                "Region": "R1",
                "Variable": "Final Energy|Transportation|Passenger|Bus|Electricity",
                "Unit": "EJ/yr",
                "2050": 1,
            }
        ]
    ).to_csv(source, index=False)
    output = tmp_path / "out"
    result = runner.invoke(
        app,
        ["image", str(source), "--output-dir", str(output), "--skip-bev"],
    )
    assert result.exit_code == 0, result.output
    assert (output / "simple_filtered.csv").exists()


def test_read_frame_preserves_strict_duplicate_identity_default(tmp_path):
    source = tmp_path / "duplicate-identities.csv"
    rows = [
        {
            "Model": "TIAM-UCL 4.1.2",
            "Scenario": "test",
            "Region": "AFR",
            "Variable": "Efficiency|Transport|Truck|Heavy|Diesel",
            "Unit": "Bvkm/PJ",
            "2050": value,
        }
        for value in (0.1, 0.2)
    ]
    pd.DataFrame(rows).to_csv(source, index=False)

    with pytest.raises(DataValidationError, match="Duplicate IAM rows"):
        read_frame(source)

    result = read_frame(source, allow_duplicate_identities=True)
    assert result["2050"].tolist() == [0.1, 0.2]
