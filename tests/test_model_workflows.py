from __future__ import annotations

import pandas as pd
import pytest

from iam_preprocessor.exceptions import DataValidationError
from iam_preprocessor.message import (
    MESSAGE_DERIVED_DRI_ROUTES,
    MESSAGE_DRI_EAF,
    MESSAGE_H_DRI_EAF,
    MESSAGE_NG_DRI_EAF,
    MESSAGE_NG_DRI_EAF_CCS,
    MESSAGE_SPONGE_IRON_GAS_CCS,
    MESSAGE_SPONGE_IRON_H2,
    prepare_message,
    split_message_dri_routes,
)
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


def test_message_removes_exact_duplicate_rows(tmp_path):
    source = tmp_path / "message.csv"
    row = {
        "Model": "MESSAGE",
        "Scenario": "test",
        "Region": "R12_AFR",
        "Variable": "Final Energy|Industry",
        "Unit": "EJ/yr",
        "2050": 1,
    }
    pd.DataFrame([row, row]).to_csv(source, index=False)

    reports = prepare_message([source], tmp_path / "out")
    output = pd.read_csv(reports[0].output_path, sep=";")

    assert len(output) == 1
    assert reports[0].input_rows == 2
    assert any("exact duplicate" in warning for warning in reports[0].warnings)


def _message_dri_frame(*, include_world: bool = True) -> pd.DataFrame:
    values = {
        "World": {
            MESSAGE_DRI_EAF: 100,
            MESSAGE_SPONGE_IRON_H2: 40,
            MESSAGE_SPONGE_IRON_GAS_CCS: 20,
            "Production|Iron and Steel|Sponge Iron|Gas|w/o CCS": 120,
            "Production|Iron and Steel|Sponge Iron|Coal|w/o CCS": 20,
        },
        "R12_AFR": {
            MESSAGE_DRI_EAF: 60,
            MESSAGE_SPONGE_IRON_H2: 30,
            MESSAGE_SPONGE_IRON_GAS_CCS: 10,
            "Production|Iron and Steel|Sponge Iron|Gas|w/o CCS": 70,
            "Production|Iron and Steel|Sponge Iron|Coal|w/o CCS": 10,
        },
        "R12_WEU": {
            MESSAGE_DRI_EAF: 40,
            MESSAGE_SPONGE_IRON_H2: 10,
            MESSAGE_SPONGE_IRON_GAS_CCS: 10,
            "Production|Iron and Steel|Sponge Iron|Gas|w/o CCS": 50,
            "Production|Iron and Steel|Sponge Iron|Coal|w/o CCS": 10,
        },
    }
    if not include_world:
        values.pop("World")
    return pd.DataFrame(
        [
            {
                "Model": "MESSAGE",
                "Scenario": "test",
                "Region": region,
                "Variable": variable,
                "Unit": "Mt/yr",
                "2050": amount,
            }
            for region, variables in values.items()
            for variable, amount in variables.items()
        ]
    )


def test_message_dri_route_split_closes_and_uses_world_conversion():
    result, warnings = split_message_dri_routes(_message_dri_frame())
    values = result.pivot(index="Region", columns="Variable", values="2050")

    assert values.loc["World", MESSAGE_H_DRI_EAF] == pytest.approx(20)
    assert values.loc["World", MESSAGE_NG_DRI_EAF_CCS] == pytest.approx(10)
    assert values.loc["World", MESSAGE_NG_DRI_EAF] == pytest.approx(70)
    assert values.loc["R12_AFR", MESSAGE_H_DRI_EAF] == pytest.approx(15)
    assert values.loc["R12_AFR", MESSAGE_NG_DRI_EAF_CCS] == pytest.approx(5)
    assert values.loc["R12_AFR", MESSAGE_NG_DRI_EAF] == pytest.approx(40)

    derived_total = values.loc[:, list(MESSAGE_DERIVED_DRI_ROUTES)].sum(axis=1)
    pd.testing.assert_series_equal(
        derived_total,
        values[MESSAGE_DRI_EAF],
        check_names=False,
    )
    assert warnings == []


def test_message_dri_route_split_uses_regional_sums_without_world():
    result, warnings = split_message_dri_routes(_message_dri_frame(include_world=False))
    values = result.pivot(index="Region", columns="Variable", values="2050")

    assert values[MESSAGE_H_DRI_EAF].sum() == pytest.approx(20)
    assert values[MESSAGE_NG_DRI_EAF_CCS].sum() == pytest.approx(10)
    assert values[MESSAGE_NG_DRI_EAF].sum() == pytest.approx(70)
    assert any("used regional sums" in warning for warning in warnings)


def test_message_dri_route_split_treats_omitted_route_region_as_zero():
    frame = _message_dri_frame()
    route = "Production|Iron and Steel|Sponge Iron|Coal|w/o CCS"
    mask = frame["Region"].eq("R12_AFR") & frame["Variable"].eq(route)
    frame.loc[mask, "2050"] = 0
    frame = frame.loc[~mask]

    result, _ = split_message_dri_routes(frame)

    assert MESSAGE_H_DRI_EAF in result["Variable"].values


def test_message_dri_route_split_is_idempotent():
    first, _ = split_message_dri_routes(_message_dri_frame())
    second, _ = split_message_dri_routes(first)

    first = first.sort_values(["Region", "Variable"]).reset_index(drop=True)
    second = second.sort_values(["Region", "Variable"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(first, second)


def test_message_dri_route_split_rejects_negative_residual():
    frame = _message_dri_frame()
    mask = frame["Region"].eq("R12_AFR") & frame["Variable"].eq(MESSAGE_DRI_EAF)
    frame.loc[mask, "2050"] = 1

    with pytest.raises(DataValidationError, match="negative NG-DRI residual"):
        split_message_dri_routes(frame)


def test_message_dri_route_split_rejects_negative_source_production():
    frame = _message_dri_frame()
    mask = frame["Region"].eq("R12_AFR") & frame["Variable"].eq(MESSAGE_SPONGE_IRON_H2)
    frame.loc[mask, "2050"] = -1

    with pytest.raises(DataValidationError, match="non-negative production"):
        split_message_dri_routes(frame)


def test_message_dri_route_split_rejects_inconsistent_world_totals():
    frame = _message_dri_frame()
    mask = frame["Region"].eq("World") & frame["Variable"].eq(MESSAGE_SPONGE_IRON_H2)
    frame.loc[mask, "2050"] = 45

    with pytest.raises(DataValidationError, match="World versus regional totals"):
        split_message_dri_routes(frame)


def test_message_dri_route_split_skips_incomplete_inputs():
    frame = _message_dri_frame().loc[lambda data: ~data["Variable"].eq(MESSAGE_SPONGE_IRON_H2)]
    result, warnings = split_message_dri_routes(frame)

    assert not set(MESSAGE_DERIVED_DRI_ROUTES).intersection(result["Variable"])
    assert any(MESSAGE_SPONGE_IRON_H2 in warning for warning in warnings)


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
