"""Fernet encryption without persistent or command-line secrets."""

from __future__ import annotations

import os
import stat
import warnings
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import find_dotenv, load_dotenv

from .exceptions import ConfigurationError, IamPreprocessorError

KEY_ENVIRONMENT_VARIABLES = ("PREMISE_KEY", "IAM_PREPROCESSOR_KEY")


def _key_from_environment() -> str | None:
    """Return a key from the process environment or the nearest ``.env`` file.

    Values already present in the process environment take precedence. Dotenv
    discovery starts in the current working directory and walks up through its
    parents; loaded values never overwrite existing environment variables.
    """

    value = next(
        (os.environ.get(name) for name in KEY_ENVIRONMENT_VARIABLES if os.environ.get(name)), None
    )
    if value:
        return value

    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path=dotenv_path, override=False)
    return next(
        (os.environ.get(name) for name in KEY_ENVIRONMENT_VARIABLES if os.environ.get(name)), None
    )


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
        value = _key_from_environment()
        if not value:
            raise ConfigurationError(
                "Set PREMISE_KEY (optionally in .env), set IAM_PREPROCESSOR_KEY, "
                "or provide --key-file for encryption."
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
