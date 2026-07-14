"""Custom exceptions used by the E3 discovery workflow."""


class E3DiscoveryError(RuntimeError):
    """Represent an expected failure raised by the E3 discovery workflow.
    """


class ConfigurationError(E3DiscoveryError):
    """Report missing, inconsistent or unsupported workflow configuration.
    """


class DataValidationError(E3DiscoveryError):
    """Report invalid input data or an invalid generated workflow dataset.
    """


class ExternalToolError(E3DiscoveryError):
    """Report unsuccessful execution or interrogation of an external program.
    """
