"""Package-specific exception hierarchy."""


class OrthologyIntegrationError(RuntimeError):
    """Base exception for expected workflow failures."""


class ConfigurationError(OrthologyIntegrationError):
    """Raised when configuration is incomplete or internally inconsistent."""


class InputValidationError(OrthologyIntegrationError):
    """Raised when a formal input is missing, malformed or scientifically invalid."""


class StageStateError(OrthologyIntegrationError):
    """Raised when stage state cannot be reused or safely replaced."""


class ScientificValidationError(OrthologyIntegrationError):
    """Raised when a required scientific regression or invariant fails."""
