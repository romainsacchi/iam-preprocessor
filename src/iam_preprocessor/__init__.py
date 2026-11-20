"""Maintainable preprocessing of IAM scenario data for premise."""

from importlib import import_module

from .crypto import decrypt_file, encrypt_file
from .filtering import filter_variables
from .prepare import prepare_scenarios
from .report import ProcessingReport
from .stock_vintages import calculate_stock_vintages, prepare_stock_vintages
from .stock_workflow import write_stock_config, write_stock_inventory
from .tiam_ucl import prepare_tiam_ucl
from .vintage_inputs import annual_additions, read_iam_series
from .vintage_reconstruction import AssetReconstruction, reconstruct_asset

_COMPATIBILITY_EXPORTS = {
    "SecConfig": ".adapters.image.config",
    "load_sec_config": ".adapters.image.config",
    "derive_bev_truck_variables": ".adapters.image.transport",
    "derive_transport_energy_services": ".adapters.image.transport",
    "prepare_image": ".adapters.image.preparation",
    "prepare_message": ".adapters.message.preparation",
    "prepare_remind": ".adapters.remind.preparation",
    "build_remind_stock_config": ".research.remind.stock_config",
    "write_remind_stock_config": ".research.remind.stock_config",
}


def __getattr__(name):
    module = _COMPATIBILITY_EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module, __name__), name)


__all__ = [
    "AssetReconstruction",
    "ProcessingReport",
    "annual_additions",
    "calculate_stock_vintages",
    "decrypt_file",
    "encrypt_file",
    "filter_variables",
    "prepare_scenarios",
    "prepare_stock_vintages",
    "prepare_tiam_ucl",
    "read_iam_series",
    "reconstruct_asset",
    "write_stock_config",
    "write_stock_inventory",
    *_COMPATIBILITY_EXPORTS,
]

__version__ = "0.1.1"
