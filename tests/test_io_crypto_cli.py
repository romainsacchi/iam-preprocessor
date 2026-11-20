from __future__ import annotations

import json

import pandas as pd
import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from iam_preprocessor.adapters.image.preparation import prepare_image
from iam_preprocessor.cli import app
from iam_preprocessor.crypto import decrypt_file, encrypt_file
from iam_preprocessor.exceptions import DataValidationError
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
    for command in ("prepare", "stock-config", "stock-inventory", "stock-vintages", "tiam-ucl"):
        assert command in help_result.stdout
    for command in ("stock-config", "stock-inventory"):
        command_help = runner.invoke(app, [command, "--help"]).stdout
        assert "preset" not in command_help
        assert "--region" not in command_help
    for old_command in ("remind", "image", "message", "remind-stock-config"):
        assert runner.invoke(app, [old_command, "--help"]).exit_code != 0

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
        ["prepare", str(source), "--output-dir", str(output), "--adapter", "image", "--skip-bev"],
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


def test_prepare_workbook_with_cover_sheet_for_unmapped_model(tmp_path):
    source = tmp_path / "scenario.xlsx"
    with pd.ExcelWriter(source) as workbook:
        pd.DataFrame({"notes": ["Example workbook"]}).to_excel(
            workbook, sheet_name="Read me", index=False
        )
        row = {
            " model ": "Other IAM",
            "scenario": "test",
            "region": "R1",
            "variable": "User-defined stock",
            "unit": "GW",
            2020: 10,
            2025: 12,
        }
        pd.DataFrame([row, {**row, "scenario": "separate run"}]).to_excel(
            workbook, sheet_name="Scenario data", index=False
        )
    runner = CliRunner()
    result = runner.invoke(
        app, ["prepare", str(source), "-o", str(tmp_path), "--scenario", "test", "--no-filter"]
    )
    assert result.exit_code == 0, result.output
    output = pd.read_csv(tmp_path / "scenario_processed.csv", sep=";")
    assert output.loc[0, "Model"] == "Other IAM"
    assert output.loc[0, "Variable"] == "User-defined stock"
    assert output["Scenario"].tolist() == ["test"]
    report = json.loads((tmp_path / "scenario_report.json").read_text())
    assert report["input_rows"] == 2
    assert report["assumptions"]["selection"] == {"model": "Other IAM", "scenario": "test"}

    inventory = tmp_path / "inventory.csv"
    result = runner.invoke(app, ["stock-inventory", str(source), "-o", str(inventory)])
    assert result.exit_code == 0, result.output
    assert set(pd.read_csv(inventory, sep=";")["Scenario"]) == {"test", "separate run"}
