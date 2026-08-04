from __future__ import annotations

import pandas as pd
import pytest

from iam_preprocessor.message import prepare_message
from iam_preprocessor.remind import split_cement_ccs


def test_message_region_cleanup(tmp_path):
    source = tmp_path / "message.csv"
    pd.DataFrame(
        [
            {
                "Model": "MESSAGE",
                "Scenario": "test",
                "Region": "R12_AFR",
                "Variable": "Final Energy|Industry",
                "Unit": "EJ/yr",
                "2050": 1,
            },
            {
                "Model": "MESSAGE",
                "Scenario": "test",
                "Region": "GLB",
                "Variable": "Final Energy|Industry",
                "Unit": "EJ/yr",
                "2050": 2,
            },
        ]
    ).to_csv(source, index=False)
    output_dir = tmp_path / "out"
    reports = prepare_message([source], output_dir)
    output = pd.read_csv(reports[0].output_path, sep=";")
    assert output["Region"].tolist() == ["AFR"]
    assert "Unnamed: 0" not in output.columns


def test_remind_cement_ccs_split_closes():
    def row(variable: str, value: float) -> dict:
        return {
            "Model": "REMIND",
            "Scenario": "test",
            "Region": "USA",
            "Variable": variable,
            "Unit": "Mt/yr",
            "2050": value,
        }

    frame = pd.DataFrame(
        [
            row(
                "Carbon Management|Carbon Capture|Industrial Processes|Industry|+|Cement",
                20,
            ),
            row("Emi|CO2|Industrial Processes|Industry|+|Cement", 80),
            row("Production|Industry|Cement", 100),
            row("FE|Industry|+++|Cement", 50),
        ]
    )
    result, warnings = split_cement_ccs(frame)
    values = result.set_index("Variable")["2050"]
    assert values["Production|Industry|Cement"] == pytest.approx(80)
    assert values["Production|Industry|Cement w CCS"] == pytest.approx(20)
    assert values["FE|Industry|+++|Cement"] == pytest.approx(40)
    assert values["FE|Industry|+++|Cement w CCS"] == pytest.approx(10)
    assert warnings == []


def test_remind_zero_denominator_assigns_no_ccs():
    variables = [
        "Carbon Management|Carbon Capture|Industrial Processes|Industry|+|Cement",
        "Emi|CO2|Industrial Processes|Industry|+|Cement",
        "Production|Industry|Cement",
        "FE|Industry|+++|Cement",
    ]
    frame = pd.DataFrame(
        [
            {
                "Model": "REMIND",
                "Scenario": "test",
                "Region": "USA",
                "Variable": variable,
                "Unit": "EJ/yr",
                "2050": 100 if variable in variables[-2:] else 0,
            }
            for variable in variables
        ]
    )
    result, _ = split_cement_ccs(frame)
    values = result.set_index("Variable")["2050"]
    assert values["Production|Industry|Cement"] == pytest.approx(100)
    assert values["Production|Industry|Cement w CCS"] == pytest.approx(0)
