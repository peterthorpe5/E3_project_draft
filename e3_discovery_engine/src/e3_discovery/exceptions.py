"""Custom exceptions used by the E3 discovery workflow."""


class E3DiscoveryError(RuntimeError):
    """Base exception for expected workflow failures."""


class ConfigurationError(E3DiscoveryError):
    """Raised when configuration values are missing or inconsistent."""


class DataValidationError(E3DiscoveryError):
    """Raised when an input or generated dataset fails validation."""


class ExternalToolError(E3DiscoveryError):
    """Raised when an external command exits unsuccessfully."""
