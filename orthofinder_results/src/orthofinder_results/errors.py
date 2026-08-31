"""Controlled exception hierarchy for OrthoFinder result interrogation."""


class OrthoFinderResultsError(Exception):
    """Base class for expected package failures."""


class InputValidationError(OrthoFinderResultsError):
    """Raised when an input result set violates the declared contract."""


class PublicationError(OrthoFinderResultsError):
    """Raised when an output cannot be published atomically or validated."""


class DistanceCalculationError(OrthoFinderResultsError):
    """Raised when an alignment or tree cannot support the requested distance."""
