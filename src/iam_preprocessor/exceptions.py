"""Application-specific exceptions."""


class IamPreprocessorError(Exception):
    """Base exception for expected preprocessing failures."""


class DataValidationError(IamPreprocessorError):
    """Raised when an IAM input violates the expected tabular schema."""


class ConfigurationError(IamPreprocessorError):
    """Raised when required scientific or security configuration is absent."""
