"""Command-line interface for IAM preprocessing."""

from __future__ import annotations

from pathlib import Path

import typer

from .config import load_sec_config
from .crypto import decrypt_file, encrypt_file
from .exceptions import IamPreprocessorError
from .filtering import filter_variables
from .image import prepare_image
from .io import discover_inputs, read_frame, write_csv_atomic
from .message import prepare_message
from .remind import prepare_remind
from .remind_stock_config import write_remind_stock_config
from .remind_stock_inventory import write_remind_stock_inventory
from .stock_vintages import prepare_stock_vintages

app = typer.Typer(
    no_args_is_help=True,
    help="Transparent preprocessing of IAM scenario data for premise.",
)


def _show_reports(reports: list) -> None:
    for report in reports:
        typer.echo(f"Wrote {report.output_path} ({report.output_rows} rows)")
        if report.encrypted_output_path:
            typer.echo(f"Encrypted {report.encrypted_output_path}")
        for warning in report.warnings:
            typer.echo(f"Warning: {warning}", err=True)


@app.command("image")
def image_command(
    inputs: list[Path] = typer.Argument(..., exists=True, readable=True),
    output_dir: Path = typer.Option(..., "--output-dir", "-o"),
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
    """Prepare IMAGE Excel/CSV files and derive transport services."""

    config = load_sec_config(
        sec_config,
        medium_bev_sec=medium_bev_sec,
        heavy_bev_sec=heavy_bev_sec,
    )
    reports = prepare_image(
        inputs,
        output_dir,
        config,
        derive_bev=not skip_bev,
        strict=strict,
        filter_output=not no_filter,
        encrypt_to=encrypt_to,
        key_file=key_file,
        overwrite=overwrite,
    )
    _show_reports(reports)


@app.command("message")
def message_command(
    inputs: list[Path] = typer.Argument(..., exists=True, readable=True),
    output_dir: Path = typer.Option(..., "--output-dir", "-o"),
    no_filter: bool = typer.Option(False, "--no-filter"),
    encrypt_to: Path | None = typer.Option(None, "--encrypt-to"),
    key_file: Path | None = typer.Option(None, "--key-file", exists=True, readable=True),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Normalize MESSAGE regions and prepare premise CSV files."""

    _show_reports(
        prepare_message(
            inputs,
            output_dir,
            filter_output=not no_filter,
            encrypt_to=encrypt_to,
            key_file=key_file,
            overwrite=overwrite,
        )
    )


@app.command("remind")
def remind_command(
    inputs: list[Path] = typer.Argument(..., exists=True, readable=True),
    output_dir: Path = typer.Option(..., "--output-dir", "-o"),
    no_filter: bool = typer.Option(False, "--no-filter"),
    encrypt_to: Path | None = typer.Option(None, "--encrypt-to"),
    key_file: Path | None = typer.Option(None, "--key-file", exists=True, readable=True),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Split REMIND cement CCS data and prepare premise CSV files."""

    _show_reports(
        prepare_remind(
            inputs,
            output_dir,
            filter_output=not no_filter,
            encrypt_to=encrypt_to,
            key_file=key_file,
            overwrite=overwrite,
        )
    )


@app.command("stock-vintages")
def stock_vintages_command(
    source: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
    config: Path = typer.Option(..., "--config", exists=True, readable=True, dir_okay=False),
    output_dir: Path = typer.Option(..., "--output-dir", "-o"),
    filter_output: bool = typer.Option(False, "--filter-output"),
    encrypt_to: Path | None = typer.Option(None, "--encrypt-to"),
    key_file: Path | None = typer.Option(None, "--key-file", exists=True, readable=True),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Reconstruct stock vintages and write v2 plus compatible v1 outputs."""
    _show_reports(
        [
            prepare_stock_vintages(
                source,
                output_dir,
                config,
                filter_output=filter_output,
                encrypt_to=encrypt_to,
                key_file=key_file,
                overwrite=overwrite,
            )
        ]
    )


@app.command("remind-stock-config")
def remind_stock_config_command(
    source: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
    destination: Path = typer.Option(..., "--output", "-o", dir_okay=False),
    regions: list[str] | None = typer.Option(None, "--region"),
    reference_year: int | None = typer.Option(None, "--reference-year"),
    end_year: int | None = typer.Option(None, "--end-year"),
    power: bool = typer.Option(True, "--power/--no-power"),
    transport: bool = typer.Option(True, "--transport/--no-transport"),
    conversion: bool = typer.Option(True, "--conversion/--no-conversion"),
    reconciliation: str = typer.Option("strict", "--reconciliation"),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Create per-region REMIND Cap/New Cap and Stock/Sales vintage config."""
    path, config, skipped = write_remind_stock_config(
        source,
        destination,
        regions=regions,
        reference_year=reference_year,
        end_year=end_year,
        include_power=power,
        include_transport=transport,
        include_conversion=conversion,
        reconciliation=reconciliation,
        overwrite=overwrite,
    )
    typer.echo(
        f"Wrote {path} ({len(config['assets'])} region/asset mappings; "
        f"{len(skipped)} unavailable mappings skipped)"
    )
    if skipped:
        typer.echo(
            "Unavailable asset families: " + ", ".join(sorted({s["asset"] for s in skipped}))
        )


@app.command("remind-stock-inventory")
def remind_stock_inventory_command(
    source: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
    destination: Path = typer.Option(..., "--output", "-o", dir_okay=False),
    regions: list[str] | None = typer.Option(None, "--region"),
    end_year: int | None = typer.Option(None, "--end-year"),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Audit all REMIND capacity/addition and vehicle stock/sales pairs."""
    path, inventory = write_remind_stock_inventory(
        source,
        destination,
        regions=regions,
        end_year=end_year,
        overwrite=overwrite,
    )
    counts = inventory["status"].value_counts().to_dict()
    typer.echo(f"Wrote {path} ({len(inventory)} pairs; statuses={counts})")


@app.command("filter")
def filter_command(
    inputs: list[Path] = typer.Argument(..., exists=True, readable=True),
    output_dir: Path = typer.Option(..., "--output-dir", "-o"),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    """Filter IAM files to the premise variable-prefix allowlist."""

    for source in discover_inputs(inputs, suffixes=(".csv", ".xlsx", ".xls")):
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
        raise typer.Exit(code=1) from exc
