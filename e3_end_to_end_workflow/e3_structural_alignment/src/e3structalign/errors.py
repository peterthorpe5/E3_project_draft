"""Expected package exceptions."""


class StructuralAlignmentError(RuntimeError):
    """Base exception for controlled structural-alignment failures."""


class InputValidationError(StructuralAlignmentError):
    """Raised when controlled input tables or structure files are invalid."""


class ToolExecutionError(StructuralAlignmentError):
    """Raised when a structural aligner cannot execute or returns invalid output."""
