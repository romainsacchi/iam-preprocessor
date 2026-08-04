"""Configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from .exceptions import ConfigurationError

BEV_CLASSES = ("Medium Truck", "Heavy Truck")


def _positive_float(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{label} must be a number; got {value!r}.") from exc
    if not number > 0:
        raise ConfigurationError(f"{label} must be greater than zero; got {number}.")
    return number


@dataclass(frozen=True)
class SecConfig:
    """Specific-energy assumptions used to derive transport services.

    Parameters
    ----------
    transport_sec_mj_per_service_km:
        Mapping from the IMAGE variable suffix after ``Passenger`` or ``Freight``
        to specific energy consumption in MJ/pkm or MJ/tkm.
    bev_truck_sec_mj_per_tkm:
        Explicit full-battery-electric SEC values for ``Medium Truck`` and
        ``Heavy Truck``.
    negative_residual_tolerance_ej:
        Magnitude below which a negative BEV residual is treated as numerical noise.
    """

    transport_sec_mj_per_service_km: dict[str, float]
    bev_truck_sec_mj_per_tkm: dict[str, float]
    negative_residual_tolerance_ej: float = 1e-7

    def require_bev_trucks(self) -> None:
        """Raise if either IMAGE BEV-truck SEC assumption is unavailable."""

        missing = [name for name in BEV_CLASSES if name not in self.bev_truck_sec_mj_per_tkm]
        if missing:
            joined = ", ".join(missing)
            raise ConfigurationError(
                "BEV derivation requires explicit SEC values for "
                f"{joined}. Supply an override YAML or the CLI SEC options, "
                "or use --skip-bev."
            )

    def as_public_dict(self) -> dict[str, Any]:
        """Return the non-secret effective assumptions for run reports."""

        return {
            "transport_sec_mj_per_service_km": dict(
                sorted(self.transport_sec_mj_per_service_km.items())
            ),
            "bev_truck_sec_mj_per_tkm": dict(sorted(self.bev_truck_sec_mj_per_tkm.items())),
            "negative_residual_tolerance_ej": self.negative_residual_tolerance_ej,
        }


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ConfigurationError(f"Could not read SEC configuration {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in SEC configuration {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError(f"SEC configuration {path} must contain a YAML mapping.")
    return payload


def load_sec_config(
    override_path: str | Path | None = None,
    *,
    medium_bev_sec: float | None = None,
    heavy_bev_sec: float | None = None,
) -> SecConfig:
    """Load packaged SEC assumptions and merge a user override.

    User mappings replace individual packaged keys. Command-line BEV values take
    precedence over both YAML sources.
    """

    default_path = Path(str(files("iam_preprocessor").joinpath("data/default_sec.yaml")))
    merged = _read_yaml(default_path)
    merged_transport = dict(merged.get("transport_sec_mj_per_service_km", {}))
    merged_bev = dict(merged.get("bev_truck_sec_mj_per_tkm", {}))

    if override_path is not None:
        override = _read_yaml(Path(override_path))
        merged_transport.update(override.get("transport_sec_mj_per_service_km", {}))
        merged_bev.update(override.get("bev_truck_sec_mj_per_tkm", {}))
        if "negative_residual_tolerance_ej" in override:
            merged["negative_residual_tolerance_ej"] = override["negative_residual_tolerance_ej"]

    if medium_bev_sec is not None:
        merged_bev["Medium Truck"] = medium_bev_sec
    if heavy_bev_sec is not None:
        merged_bev["Heavy Truck"] = heavy_bev_sec

    transport = {
        str(key): _positive_float(value, f"SEC for {key}")
        for key, value in merged_transport.items()
    }
    bev = {
        str(key): _positive_float(value, f"BEV SEC for {key}") for key, value in merged_bev.items()
    }
    unsupported = sorted(set(bev) - set(BEV_CLASSES))
    if unsupported:
        raise ConfigurationError(
            "Unsupported BEV truck classes in SEC configuration: " + ", ".join(unsupported)
        )

    tolerance = float(merged.get("negative_residual_tolerance_ej", 1e-7))
    if tolerance < 0:
        raise ConfigurationError("negative_residual_tolerance_ej cannot be negative.")

    return SecConfig(
        transport_sec_mj_per_service_km=transport,
        bev_truck_sec_mj_per_tkm=bev,
        negative_residual_tolerance_ej=tolerance,
    )
