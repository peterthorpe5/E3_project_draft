"""Version-aware discovery of OrthoFinder result layouts."""

from __future__ import annotations

import re
from pathlib import Path

from .errors import InputValidationError
from .models import ResultCapabilities, ResultLayout

_VERSION_PATTERNS = (
    re.compile(r"OrthoFinder\s+version\s+([0-9]+(?:\.[0-9A-Za-z]+)+)", re.IGNORECASE),
    re.compile(r"Version\s*[:=]\s*([0-9]+(?:\.[0-9A-Za-z]+)+)", re.IGNORECASE),
)


def discover_layout(*, results_dir: Path) -> ResultLayout:
    """Discover and validate one OrthoFinder result directory.

    OrthoFinder 2 may expose both legacy MCL orthogroups and phylogenetic
    hierarchical orthogroups. OrthoFinder 3 is treated as HOG-primary and is
    not required to retain the deprecated ``Orthogroups.tsv`` table.

    Args:
        results_dir: Completed OrthoFinder result directory.

    Returns:
        Version-aware resolved result layout.

    Raises:
        InputValidationError: If the directory or its core authorities are invalid.
    """

    root = Path(results_dir).expanduser().resolve()
    if not root.is_dir():
        raise InputValidationError(f"OrthoFinder results directory does not exist: {root}")
    log_path = _required_file(root / "Log.txt", role="OrthoFinder Log.txt")
    version = detect_version(log_path=log_path)
    major = _major_version(version=version)
    if major not in {2, 3}:
        raise InputValidationError(
            f"Unsupported OrthoFinder major version {major} from {log_path}; "
            "supported major versions are 2 and 3."
        )

    working = root / "WorkingDirectory"
    species_ids = _optional_file(working / "SpeciesIDs.txt")
    sequence_ids = _optional_file(working / "SequenceIDs.txt")
    orthogroups = _optional_file(root / "Orthogroups" / "Orthogroups.tsv")
    hog_dir = root / "Phylogenetic_Hierarchical_Orthogroups"
    hog_paths = tuple(
        sorted(
            (
                path.resolve()
                for path in hog_dir.glob("N*.tsv")
                if path.is_file() and not path.name.startswith("._")
            ),
            key=_hog_sort_key,
        )
    )
    if not hog_paths and orthogroups is None:
        raise InputValidationError(f"No HOG tables or legacy Orthogroups.tsv were found in {root}.")

    species_tree = _first_existing_file(
        root / "Species_Tree",
        names=("SpeciesTree_rooted_node_labels.txt", "SpeciesTree_rooted.txt"),
    )
    sequence_dir = _optional_directory(root / "Orthogroup_Sequences")
    alignment_dir = _first_existing_directory(
        root,
        names=("MultipleSequenceAlignments", "Alignments"),
    )
    gene_trees = _optional_directory(root / "Gene_Trees")
    resolved_trees = _optional_directory(root / "Resolved_Gene_Trees")
    capabilities = ResultCapabilities(
        has_species_ids=species_ids is not None,
        has_sequence_ids=sequence_ids is not None,
        has_legacy_orthogroups=orthogroups is not None,
        has_hog_tables=bool(hog_paths),
        has_orthogroup_sequences=sequence_dir is not None,
        has_alignments=alignment_dir is not None,
        has_gene_trees=gene_trees is not None,
        has_resolved_gene_trees=resolved_trees is not None,
        has_species_tree=species_tree is not None,
    )
    return ResultLayout(
        results_dir=root,
        orthofinder_version=version,
        adapter_name=f"orthofinder_{major}",
        primary_group_authority=("HOG" if major == 3 or hog_paths else "LEGACY_ORTHOGROUP"),
        log_path=log_path,
        species_ids_path=species_ids,
        sequence_ids_path=sequence_ids,
        orthogroups_path=orthogroups,
        hog_paths=hog_paths,
        species_tree_path=species_tree,
        orthogroup_sequences_dir=sequence_dir,
        alignments_dir=alignment_dir,
        gene_trees_dir=gene_trees,
        resolved_gene_trees_dir=resolved_trees,
        capabilities=capabilities,
    )


def detect_version(*, log_path: Path) -> str:
    """Extract the OrthoFinder version from a log.

    Args:
        log_path: OrthoFinder ``Log.txt`` path.

    Returns:
        Exact detected version string.

    Raises:
        InputValidationError: If no supported version declaration is present.
    """

    source = _required_file(Path(log_path), role="OrthoFinder Log.txt")
    with source.open(mode="r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number > 500:
                break
            for pattern in _VERSION_PATTERNS:
                match = pattern.search(line)
                if match:
                    return match.group(1)
    raise InputValidationError(f"Could not detect an OrthoFinder version in {source}.")


def _major_version(*, version: str) -> int:
    """Return the numeric major component of a version.

    Args:
        version: Version string beginning with an integer.

    Returns:
        Major version number.

    Raises:
        InputValidationError: If the version lacks a numeric major component.
    """

    match = re.match(r"^(\d+)", version)
    if match is None:
        raise InputValidationError(f"Invalid OrthoFinder version string: {version!r}")
    return int(match.group(1))


def _hog_sort_key(path: Path) -> tuple[int, str]:
    """Sort HOG files numerically by their species-tree node.

    Args:
        path: Candidate HOG table path.

    Returns:
        Numeric node and filename fallback.
    """

    match = re.fullmatch(r"N(\d+)\.tsv", path.name)
    return (int(match.group(1)) if match else 2**31, path.name)


def _required_file(path: Path, *, role: str) -> Path:
    """Validate a required readable regular file.

    Args:
        path: Candidate file path.
        role: Human-readable file role.

    Returns:
        Resolved path.

    Raises:
        InputValidationError: If the file is missing or empty.
    """

    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise InputValidationError(f"Missing or empty {role}: {resolved}")
    return resolved


def _optional_file(path: Path) -> Path | None:
    """Return a resolved non-empty file when present.

    Args:
        path: Candidate file path.

    Returns:
        Resolved file or ``None``.
    """

    resolved = path.expanduser().resolve()
    return resolved if resolved.is_file() and resolved.stat().st_size > 0 else None


def _optional_directory(path: Path) -> Path | None:
    """Return a resolved directory when present.

    Args:
        path: Candidate directory path.

    Returns:
        Resolved directory or ``None``.
    """

    resolved = path.expanduser().resolve()
    return resolved if resolved.is_dir() else None


def _first_existing_file(directory: Path, *, names: tuple[str, ...]) -> Path | None:
    """Return the first named non-empty file in a directory.

    Args:
        directory: Parent directory.
        names: Ordered candidate names.

    Returns:
        First matching path or ``None``.
    """

    for name in names:
        found = _optional_file(directory / name)
        if found is not None:
            return found
    return None


def _first_existing_directory(directory: Path, *, names: tuple[str, ...]) -> Path | None:
    """Return the first named directory.

    Args:
        directory: Parent directory.
        names: Ordered candidate names.

    Returns:
        First matching directory or ``None``.
    """

    for name in names:
        found = _optional_directory(directory / name)
        if found is not None:
            return found
    return None
