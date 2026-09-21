"""Package-specific exceptions."""


class ConfigurationError(ValueError):
    """Raised when benchmark configuration is unsafe or inconsistent."""


class ExternalCommandError(RuntimeError):
    """Raised when an external benchmark command fails."""


class DataValidationError(ValueError):
    """Raised when input or output data violate the expected contract."""
