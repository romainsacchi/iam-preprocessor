"""Shared scenario preparation with opt-in model adapters."""

from pathlib import Path

from .crypto import encrypt_file
from .exceptions import DataValidationError
from .filtering import filter_variables
from .io import (
    IAM_SUFFIXES,
    discover_inputs,
    read_frame,
    scenario_identity,
    sha256_file,
    write_csv_atomic,
)
from .report import ProcessingReport


def prepare_scenarios(
    inputs,
    output_dir,
    *,
    adapter=None,
    model=None,
    scenario=None,
    sec_config=None,
    medium_bev_sec=None,
    heavy_bev_sec=None,
    skip_bev=False,
    strict=False,
    filter_output=True,
    encrypt_to=None,
    key_file=None,
    overwrite=False,
):
    """Prepare standard IAM tables with optional documented model-specific transformations."""
    selecting = scenario is not None or model is not None
    if adapter is not None and selecting:
        raise DataValidationError(
            "Select a scenario first, then apply an adapter in a separate run."
        )
    if (
        adapter is not None
        or skip_bev
        or strict
        or any(value is not None for value in (sec_config, medium_bev_sec, heavy_bev_sec))
    ):
        # Optional input corrections have their own settings and processing steps.
        from .adapters import prepare_with_adapter

        return prepare_with_adapter(
            adapter,
            inputs,
            output_dir,
            sec_config=sec_config,
            medium_bev_sec=medium_bev_sec,
            heavy_bev_sec=heavy_bev_sec,
            skip_bev=skip_bev,
            strict=strict,
            filter_output=filter_output,
            encrypt_to=encrypt_to,
            key_file=key_file,
            overwrite=overwrite,
        )

    output_dir = Path(output_dir)
    reports = []
    for source in discover_inputs(inputs, suffixes=IAM_SUFFIXES):
        frame = read_frame(source)
        input_rows = len(frame)
        selection = {}
        if selecting:
            # Keep the matching rows, then check that one model and scenario remain.
            if model is not None:
                frame = frame.loc[frame["Model"].eq(model)]
            if scenario is not None:
                frame = frame.loc[frame["Scenario"].eq(scenario)]
            if frame.empty:
                raise DataValidationError(f"No rows match the scenario selection in {source.name}.")
            selected_model, selected_scenario = scenario_identity(frame)
            selection = {"model": selected_model, "scenario": selected_scenario}
        models = frame["Model"].drop_duplicates().astype(str).tolist()
        report = ProcessingReport(
            model=models[0] if len(models) == 1 else "multiple",
            input_path=str(source),
            input_sha256=sha256_file(source),
            input_rows=input_rows,
            assumptions={"selection": selection} if selecting else {},
        )
        output = filter_variables(frame) if filter_output else frame
        suffix = "_filtered.csv" if filter_output else "_processed.csv"
        destination = output_dir / f"{source.stem}{suffix}"
        write_csv_atomic(output, destination, overwrite=overwrite)
        report.output_path = str(destination)
        report.output_sha256 = sha256_file(destination)
        report.output_rows = len(output)
        if encrypt_to is not None:
            encrypted = Path(encrypt_to) / destination.name
            encrypt_file(destination, encrypted, key_file=key_file, overwrite=overwrite)
            report.encrypted_output_path = str(encrypted)
            report.encrypted_output_sha256 = sha256_file(encrypted)
        report.write(output_dir / f"{source.stem}_report.json", overwrite=overwrite)
        reports.append(report)
    return reports
