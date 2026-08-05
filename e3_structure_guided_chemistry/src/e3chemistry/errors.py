"""Package-specific exception types."""


class ChemistryError(RuntimeError):
    """Base class for controlled structure-guided chemistry failures."""


class ConfigurationError(ChemistryError):
    """Raised when a configuration is unsafe or internally inconsistent."""


class InputValidationError(ChemistryError):
    """Raised when a scientific input is missing, ambiguous or malformed."""


class DependencyError(ChemistryError):
    """Raised when a declared open-source runtime dependency is unavailable."""
