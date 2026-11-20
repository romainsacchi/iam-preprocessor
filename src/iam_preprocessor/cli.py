"""Command-line interface for IAM preprocessing."""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from .crypto import decrypt_file, encrypt_file
from .exceptions import IamPreprocessorError
from .filtering import filter_variables
from .io import IAM_SUFFIXES, discover_inputs, read_frame, write_csv_atomic
from .prepare import prepare_scenarios
from .stock_vintages import prepare_stock_vintages
from .stock_workflow import write_stock_config, write_stock_inventory

app = typer.Typer(
    no_args_is_help=True,
    help="Prepare IAM scenario files for premise and reconstruct stock by build year for TRAILS.",
)


def _show_reports(reports: list) -> None:
    """Print processing warnings and the paths of the files written."""
    for report in reports:
        typer.echo(f"Wrote {report.output_path} ({report.output_rows} rows)")
        if report.encrypted_output_path:
            typer.echo(f"Encrypted {report.encrypted_output_path}")
        for warning in report.warnings:
            typer.echo(f"Warning: {warning}", err=True)


@app.command("prepare")
def prepare_command(
    inputs: list[Path] = typer.Argument(..., exists=True, readable=True),
    output_dir: Path = typer.Option(..., "--output-dir", "-o"),
    adapter: str | None = typer.Option(None, "--adapter", help="Optional model-specific adapter."),
    model: str | None = typer.Option(None, "--model", help="Select an exact model label."),
    scenario: str | None = typer.Option(None, "--scenario", help="Select an exact scenario label."),
    sec_config: Path | None = typer.Option(None, "--sec-config", exists=True, readable=True),
    medium_bev_sec: float | None = typer.Option(None, "--medium-bev-sec", min=0),
    heavy_bev_sec: float | None = typer.Option(None, "--heavy-bev-sec", min=0),
    skip_bev: bool = typer.Option(False, "--skip-bev"),
    strict: bool = typer.Option(False, "--strict"),
    no_filter: bool = typer.Option(False, "--no-filter"),
    encrypt_to: Path | None = typer.Option(None, "--encrypt-to"),
    key_file: Path | None = typer.Option(None, "--key-file", exists=True, readable=True),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Normalize and optionally filter or encrypt IAM scenario files."""

    reports = prepare_scenarios(
        inputs,
        output_dir,
        adapter=adapter,
        model=model,
        scenario=scenario,
        sec_config=sec_config,
        medium_bev_sec=medium_bev_sec,
        heavy_bev_sec=heavy_bev_sec,
        skip_bev=skip_bev,
        strict=strict,
        filter_output=not no_filter,
        encrypt_to=encrypt_to,
        key_file=key_file,
        overwrite=overwrite,
    )
    _show_reports(reports)


def _keep_stock_message(record: logging.LogRecord) -> bool:
    """Keep FLODyM warnings other than expected stock-driven behaviour."""
    message = record.getMessage()
    routine_retirement = message.startswith("Modified the lifetime model of stock ") and (
        message.endswith(" time step(s) to avoid negative inflow.")
    )
    zero_stock = message == "Stock is zero. This will lead to a zero inflow and outflow."
    return record.levelno != logging.WARNING or not (routine_retirement or zero_stock)


@app.command("stock-vintages")
def stock_vintages_command(
    source: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
    config: Path = typer.Option(..., "--config", exists=True, readable=True, dir_okay=False),
    output_dir: Path = typer.Option(..., "--output-dir", "-o"),
    overwrite: bool = typer.Option(False, "--overwrite"),
    detailed_report: bool = typer.Option(
        False, "--detailed-report", help="Include results and checks for every asset and region."
    ),
) -> None:
    """Calculate stock by build year and save it in a separate Parquet file."""
    stock_logger = logging.getLogger("flodym.stocks")
    stock_logger.addFilter(_keep_stock_message)
    try:
        report = prepare_stock_vintages(
            source, output_dir, config, overwrite=overwrite, detailed_report=detailed_report
        )
    finally:
        stock_logger.removeFilter(_keep_stock_message)
    _show_reports([report])


@app.command("stock-config")
def stock_config_command(
    source: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
    destination: Path = typer.Option(..., "--output", "-o", dir_okay=False),
    mapping: Path = typer.Option(..., "--mapping", exists=True, readable=True, dir_okay=False),
    reference_year: int | None = typer.Option(None, "--reference-year"),
    end_year: int | None = typer.Option(None, "--end-year"),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Write stock settings for the regions in an IAM scenario."""
    path, config = write_stock_config(
        source,
        destination,
        mapping=mapping,
        reference_year=reference_year,
        end_year=end_year,
        overwrite=overwrite,
    )
    typer.echo(f"Wrote {path} ({len(config['assets'])} region/asset mappings)")


@app.command("stock-inventory")
def stock_inventory_command(
    source: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
    destination: Path = typer.Option(..., "--output", "-o", dir_okay=False),
    config: Path | None = typer.Option(
        None, "--config", exists=True, readable=True, dir_okay=False
    ),
    end_year: int | None = typer.Option(None, "--end-year"),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """List IAM variables or check whether the selected input rows are present."""
    path, inventory = write_stock_inventory(
        source,
        destination,
        config_path=config,
        end_year=end_year,
        overwrite=overwrite,
    )
    counts = inventory["status"].value_counts().to_dict() if not inventory.empty else {}
    typer.echo(f"Wrote {path} ({len(inventory)} rows; statuses={counts})")


@app.command("filter")
def filter_command(
    inputs: list[Path] = typer.Argument(..., exists=True, readable=True),
    output_dir: Path = typer.Option(..., "--output-dir", "-o"),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Filter IAM files to the premise variable-prefix allowlist."""

    for source in discover_inputs(inputs, suffixes=IAM_SUFFIXES):
        destination = output_dir / f"{source.stem}_filtered.csv"
        write_csv_atomic(filter_variables(read_frame(source)), destination, overwrite=overwrite)
        typer.echo(f"Wrote {destination}")


@app.command("encrypt")
def encrypt_command(
    source: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
    destination: Path = typer.Argument(...),
    key_file: Path | None = typer.Option(None, "--key-file", exists=True, readable=True),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Encrypt a file using a key file, environment, or local .env file."""

    typer.echo(str(encrypt_file(source, destination, key_file=key_file, overwrite=overwrite)))


@app.command("decrypt")
def decrypt_command(
    source: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
    destination: Path = typer.Argument(...),
    key_file: Path | None = typer.Option(None, "--key-file", exists=True, readable=True),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Decrypt a file using a key file, environment, or local .env file."""

    typer.echo(str(decrypt_file(source, destination, key_file=key_file, overwrite=overwrite)))


def main() -> None:
    """Run the Typer application with concise expected-error handling."""

    try:
        app()
    except IamPreprocessorError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc
