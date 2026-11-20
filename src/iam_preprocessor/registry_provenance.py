"""Verify references to the mapping files used by older configurations."""

from hashlib import sha256
from importlib.resources import files

import yaml

from .exceptions import DataValidationError
from .variable_maps import variable_map


def verify_registry_provenance(record):
    """Verify a recorded bundle against packaged files by content."""
    for bundle in variable_map("registry_sources.yaml")["bundles"]:
        provenance = {}
        for role, source in bundle.items():
            content = files(__package__).joinpath(source["file"]).read_bytes()
            metadata = yaml.safe_load(content)
            provenance[role] = {key: metadata[key] for key in source["metadata"]}
            provenance[role]["sha256"] = sha256(content).hexdigest()
        if record == provenance:
            return
    raise DataValidationError(
        "Configuration registry checksums do not match this software version."
    )
