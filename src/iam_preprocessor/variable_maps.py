"""Read packaged IAM variable definitions and output labels."""

from functools import cache
from importlib.resources import files

import yaml


@cache
def variable_map(name, *, package=__package__):
    """Load a packaged YAML mapping. Callers treat the returned data as read-only."""
    return yaml.safe_load(files(package).joinpath("data", name).read_text("utf-8"))


def vintage_suffix(metric, cohort=None):
    """Return the v1 output label for an aggregate metric or for a cohort."""
    output = variable_map("vintage_output_variables.yaml")
    if cohort is None:
        return output["total"][metric]
    return output["cohort"][metric].format(year=cohort)
