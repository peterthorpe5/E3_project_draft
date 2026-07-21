"""Package-specific exceptions."""


class WorkflowError(RuntimeError):
    """Raised when a workflow contract cannot be satisfied."""


class ConfigurationError(WorkflowError):
    """Raised when configuration is missing, malformed, or unsafe."""


class ManifestError(WorkflowError):
    """Raised when a controlled input manifest fails validation."""


class StageError(WorkflowError):
    """Raised when a stage fails or publishes invalid output."""

