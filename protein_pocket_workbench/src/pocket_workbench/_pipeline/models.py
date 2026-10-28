"""Keyword-only configuration and input records."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, kw_only=True)
class Sample:
    """One representative structure and its optional sequence metadata.

    Attributes:
        sample_id: Unique filename-safe model identifier.
        model_path: Local PDB or mmCIF input.
        sequence_id: Exact FASTA identifier, if supplied.
        sequence: Ungapped amino acid sequence, if supplied.
        cluster: User's cluster label, not inferred from structure.
        chain: Author chain identifier, or 'all' for explicit complex analysis.
    """

    sample_id: str
    model_path: Path
    sequence_id: str = ""
    sequence: str = ""
    cluster: str = ""
    chain: str = ""

    def __post_init__(self) -> None:
        """Reject unsafe identifiers and missing input structures."""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", self.sample_id):
            raise ValueError(f"Invalid sample_id: {self.sample_id!r}")
        if not self.model_path.is_file() or self.model_path.stat().st_size == 0:
            raise ValueError(f"Missing or empty model: {self.model_path}")
        if self.model_path.suffix.lower() not in {".pdb", ".cif", ".mmcif"}:
            raise ValueError(f"Expected .pdb, .cif or .mmcif: {self.model_path}")


@dataclass(frozen=True, kw_only=True)
class Settings:
    """Explicit analysis choices included in the run fingerprint.

    Attributes:
        confidence: 'plddt' to interpret B fields, or 'none'.
        threads: P2Rank threads; samples run sequentially.
        timeout: Maximum seconds for each external command.
        predict_config: P2Rank prediction profile.
        rescore_config: P2Rank rescoring profile.
        rescore: Whether to rescore the same fpocket cavities.
        allow_fragments: Permit a unique exact FASTA substring.
        high_confidence: Residue pLDDT threshold.
        pocket_fraction: Minimum all-residue high-confidence fraction.
        overlap: Minimum within-model residue Jaccard for a reported match.
        required_p2rank: Required P2Rank version substring.
    """

    confidence: str = "plddt"
    threads: int = 4
    timeout: float = 3600.0
    predict_config: str = "alphafold"
    rescore_config: str = "rescore_2024"
    rescore: bool = True
    allow_fragments: bool = False
    high_confidence: float = 70.0
    pocket_fraction: float = 0.8
    overlap: float = 0.25
    required_p2rank: str = "2.5.1"

    def __post_init__(self) -> None:
        """Validate numeric limits before an output directory is created."""
        if self.confidence not in {"plddt", "none"}:
            raise ValueError("confidence must be plddt or none")
        if (
            isinstance(self.threads, bool)
            or not isinstance(self.threads, int)
            or self.threads < 1
        ):
            raise ValueError("threads must be a positive integer")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if not 0 <= self.high_confidence <= 100:
            raise ValueError("high_confidence must lie between 0 and 100")
        for name, value in (
            ("pocket_fraction", self.pocket_fraction),
            ("overlap", self.overlap),
        ):
            if not 0 < value <= 1:
                raise ValueError(f"{name} must lie in (0, 1]")
        if not self.predict_config or not self.rescore_config:
            raise ValueError("P2Rank profile names must not be empty")
