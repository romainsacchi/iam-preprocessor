"""Names and parameters for the supported stock survival curves."""

from .exceptions import DataValidationError

_PARAMETERS = {"fixed": "mean", "weibull": "mean", "quartic": "maximum"}


def canonical_distribution(distribution):
    """Normalize the legacy name of the quartic lifetime curve."""
    return "quartic" if distribution == "remind" else distribution


def lifetime_parameter(distribution):
    """Return the configured lifetime parameter for a supported distribution."""
    try:
        return _PARAMETERS[canonical_distribution(distribution)]
    except (KeyError, TypeError) as exc:
        raise DataValidationError(
            "Lifetime distribution must be fixed, weibull or quartic."
        ) from exc
