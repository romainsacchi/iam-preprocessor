"""Fernet encryption without persistent or command-line secrets."""

from __future__ import annotations

import os
import stat
import warnings
from pathlib import Path

from cryptography.fernet import Fernet

from .exceptions import ConfigurationError, IamPreprocessorError

KEY_ENVIRONMENT_VARIABLE = "IAM_PREPROCESSOR_KEY"


def load_fernet_key(key_file: str | Path | None = None) -> bytes:
    """Load and validate a Fernet key from a file or environment variable.

    A supplied key file takes precedence. Raw keys are intentionally not accepted
    as CLI options, which avoids shell history exposure.
    """

    if key_file is not None:
        path = Path(key_file)
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                warnings.warn(
                    f"Key file {path} is accessible by group or other users.",
                    stacklevel=2,
                )
            key = path.read_bytes().strip()
        except OSError as exc:
            raise ConfigurationError(f"Could not read Fernet key file {path}: {exc}") from exc
    else:
        value = os.environ.get(KEY_ENVIRONMENT_VARIABLE)
        if not value:
            raise ConfigurationError(
                f"Set {KEY_ENVIRONMENT_VARIABLE} or provide --key-file for encryption."
            )
        key = value.encode("ascii").strip()
    try:
        Fernet(key)
    except (ValueError, TypeError) as exc:
        raise ConfigurationError("The supplied Fernet key is invalid.") from exc
    return key


def _write_bytes_atomic(payload: bytes, destination: Path, overwrite: bool) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        raise IamPreprocessorError(
            f"Output already exists: {destination}. Use --overwrite to replace it."
        )
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def encrypt_file(
    source: str | Path,
    destination: str | Path,
    *,
    key_file: str | Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Encrypt a file with a runtime Fernet key."""

    source_path = Path(source)
    payload = Fernet(load_fernet_key(key_file)).encrypt(source_path.read_bytes())
    return _write_bytes_atomic(payload, Path(destination), overwrite)


def decrypt_file(
    source: str | Path,
    destination: str | Path,
    *,
    key_file: str | Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Decrypt a Fernet file with a runtime key."""

    source_path = Path(source)
    payload = Fernet(load_fernet_key(key_file)).decrypt(source_path.read_bytes())
    return _write_bytes_atomic(payload, Path(destination), overwrite)
