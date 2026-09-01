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
from iam_preprocessor.tiam_ucl import (
    TIAM_DEFAULT_H_DRI_HYDROGEN_KG_PER_TONNE_STEEL,
    TIAM_H_DRI_HYDROGEN,
    TIAM_H_DRI_PRODUCTION,
    TIAM_H_DRI_PRODUCTION_PRODUCT,
    derive_tiam_h_dri_hydrogen,
    prepare_tiam_ucl,
)


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


def _tiam_h_dri_frame(*, include_product_alias: bool = True) -> pd.DataFrame:
    values = {"World": 10.0, "AFR": 4.0, "WEU": 6.0}
    variables = [TIAM_H_DRI_PRODUCTION]
    if include_product_alias:
        variables.append(TIAM_H_DRI_PRODUCTION_PRODUCT)
    return pd.DataFrame(
        [
            {
                "Model": "TIAM-UCL 4.1.2",
                "Scenario": "SSP2-RCP19",
                "Region": region,
                "Variable": variable,
                "Unit": "Mt/yr",
                "2050": amount,
            }
            for variable in variables
            for region, amount in values.items()
        ]
    )


def test_tiam_h_dri_hydrogen_uses_inventory_consistent_default():
    result, warnings = derive_tiam_h_dri_hydrogen(_tiam_h_dri_frame())
    derived = result.loc[result["Variable"].eq(TIAM_H_DRI_HYDROGEN)].set_index("Region")
    pj_per_mt = TIAM_DEFAULT_H_DRI_HYDROGEN_KG_PER_TONNE_STEEL * 0.12

    assert derived.loc["World", "2050"] == pytest.approx(10 * pj_per_mt)
    assert derived.loc["AFR", "2050"] == pytest.approx(4 * pj_per_mt)
    assert derived["Unit"].unique().tolist() == ["PJ/yr"]
    assert derived.loc[["AFR", "WEU"], "2050"].sum() == pytest.approx(derived.loc["World", "2050"])
    assert warnings == []


def test_tiam_h_dri_hydrogen_accepts_explicit_intensity():
    result, _ = derive_tiam_h_dri_hydrogen(_tiam_h_dri_frame(), hydrogen_kg_per_tonne_steel=50)
    world = result.loc[
        result["Variable"].eq(TIAM_H_DRI_HYDROGEN) & result["Region"].eq("World"),
        "2050",
    ].item()

    assert world == pytest.approx(60)


def test_tiam_h_dri_hydrogen_is_idempotent():
    first, _ = derive_tiam_h_dri_hydrogen(_tiam_h_dri_frame())
    second, _ = derive_tiam_h_dri_hydrogen(first)

    first = first.sort_values(["Region", "Variable"]).reset_index(drop=True)
    second = second.sort_values(["Region", "Variable"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(first, second)


def test_tiam_h_dri_hydrogen_rejects_inconsistent_production_aliases():
    frame = _tiam_h_dri_frame()
    mask = frame["Variable"].eq(TIAM_H_DRI_PRODUCTION_PRODUCT) & frame["Region"].eq("AFR")
    frame.loc[mask, "2050"] = 5

    with pytest.raises(DataValidationError, match="production aliases disagree"):
        derive_tiam_h_dri_hydrogen(frame)


def test_tiam_h_dri_hydrogen_rejects_invalid_alias_unit():
    frame = _tiam_h_dri_frame()
    frame.loc[frame["Variable"].eq(TIAM_H_DRI_PRODUCTION_PRODUCT), "Unit"] = "PJ/yr"

    with pytest.raises(DataValidationError, match="aliases must use Mt/yr"):
        derive_tiam_h_dri_hydrogen(frame)


def test_tiam_h_dri_hydrogen_rejects_inconsistent_world_total():
    frame = _tiam_h_dri_frame(include_product_alias=False)
    frame.loc[frame["Region"].eq("World"), "2050"] = 11

    with pytest.raises(DataValidationError, match="World versus regional totals"):
        derive_tiam_h_dri_hydrogen(frame)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("2050", -1, "must be non-negative"),
        ("Unit", "EJ/yr", "production in Mt/yr"),
    ],
)
def test_tiam_h_dri_hydrogen_rejects_invalid_production(column, value, message):
    frame = _tiam_h_dri_frame(include_product_alias=False)
    frame.loc[frame["Region"].eq("AFR"), column] = value

    with pytest.raises(DataValidationError, match=message):
        derive_tiam_h_dri_hydrogen(frame)


@pytest.mark.parametrize("intensity", [0, -1, float("nan"), float("inf")])
def test_tiam_h_dri_hydrogen_rejects_invalid_intensity(intensity):
    with pytest.raises(DataValidationError, match="positive finite"):
        derive_tiam_h_dri_hydrogen(_tiam_h_dri_frame(), hydrogen_kg_per_tonne_steel=intensity)


def test_tiam_h_dri_hydrogen_skips_missing_production():
    frame = _tiam_h_dri_frame().loc[lambda data: data["Variable"].eq("missing")]
    result, warnings = derive_tiam_h_dri_hydrogen(frame)

    assert result.empty
    assert any("no H-DRI/EAF production" in warning for warning in warnings)


def test_tiam_pipeline_reports_derivation_assumptions(tmp_path):
    source = tmp_path / "tiam-ucl_SSP2-RCP19.csv"
    frame = _tiam_h_dri_frame()
    efficiency_variants = pd.DataFrame(
        [
            {
                "Model": "TIAM-UCL 4.1.2",
                "Scenario": "SSP2-RCP19",
                "Region": "AFR",
                "Variable": "Efficiency|Transport|Truck|Heavy|Diesel",
                "Unit": "Bvkm/PJ",
                "2050": value,
            }
            for value in (0.1, 0.2, 0.2)
        ]
    )
    pd.concat([frame, efficiency_variants], ignore_index=True).to_csv(source, index=False)

    reports = prepare_tiam_ucl([source], tmp_path / "out")
    output = pd.read_csv(reports[0].output_path, sep=";")
    assumptions = reports[0].assumptions["tiam_ucl_h_dri_hydrogen"]
    efficiency = output.loc[output["Variable"].eq("Efficiency|Transport|Truck|Heavy|Diesel")]

    assert TIAM_H_DRI_HYDROGEN in output["Variable"].values
    assert efficiency["2050"].tolist() == [0.1, 0.2, 0.2]
    assert reports[0].derived_variables == [TIAM_H_DRI_HYDROGEN]
    assert reports[0].input_rows == len(frame) + 3
    assert any("non-unique IAM identities" in warning for warning in reports[0].warnings)
    assert assumptions["hydrogen_kg_per_tonne_steel"] == pytest.approx(
        TIAM_DEFAULT_H_DRI_HYDROGEN_KG_PER_TONNE_STEEL
    )
    assert assumptions["intensity_source"] == "premise H2-DRI/EAF inventory"
    assert "not an original TIAM-UCL" in assumptions["interpretation"]


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
