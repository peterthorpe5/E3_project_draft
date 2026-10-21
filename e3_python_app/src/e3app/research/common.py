"""Validated protein inputs, configuration and atomic research-workspace files."""

from __future__ import annotations

import csv
from dataclasses import dataclass, fields
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import tempfile
import tomllib
from typing import Iterator, Mapping, Sequence

LOGGER = logging.getLogger(__name__)
PROTEIN = re.compile(r"^[ACDEFGHIKLMNPQRSTVWYBXZJUO]+$")


class ResearchError(ValueError):
    """A controlled protein-workflow validation or execution failure."""


@dataclass(frozen=True, kw_only=True)
class ResearchConfig:
    """Operator-controlled data, tool and provider settings.

    Attributes:
        workspace: Writable sidecar, separate from immutable published resources.
        index: Official cluster index Parquet, local or mounted.
        sequences: Official sequence Parquet, local or mounted.
        sequence_map: Sequence-to-cluster Parquet.
        taxonomy: Reviewed sequence taxonomy Parquet/TSV.
        cluster_taxonomy: Precomputed cluster/taxon summary Parquet.
        identifier_bridge: Optional input_id/sequence_id Parquet/TSV bridge.
        identifier_prefixes: Explicit additional source namespaces to test.
        diamond: DIAMOND executable path or name.
        mafft: MAFFT executable path or name.
        fasttree: FastTree executable path or name.
        interproscan: Local InterProScan executable.
        emapper: Local eggNOG-mapper executable.
        eggnog_data: Installed eggNOG database directory.
        threads: Maximum threads per worker job.
        memory_gb: DuckDB and DIAMOND working-memory setting.
        max_sequences: Explicit whole-cluster extraction bound.
        max_alignment_sequences: Maximum explicitly selected alignment size.
        max_alignment_cells: Alignment matrix bound for statistics/viewers.
        command_timeout: Maximum seconds for each external command.
        esm_endpoint: Operator-configured ESMFold/Hugging Face endpoint.
        esm_token_env: Environment variable containing its bearer token.
        esm_model_revision: Hugging Face revision for local inference.
        endpoint_max_length: Configured dedicated endpoint sequence length bound.
        local_fold_max_length: Locally configured sequence length bound.
        email: Contact address required by the optional EBI service.
        auspice_url: Browser-accessible self-hosted Auspice URL.
        centroid_database: Optional DIAMOND database of global representatives.
    """

    workspace: Path = Path.home() / ".local" / "share" / "protein_research"
    index: str = ""
    sequences: str = ""
    sequence_map: str = ""
    taxonomy: str = ""
    cluster_taxonomy: str = ""
    identifier_bridge: str = ""
    identifier_prefixes: tuple[str, ...] = ("UNIPROT_", "NR_")
    diamond: str = "diamond"
    mafft: str = "mafft"
    fasttree: str = "FastTree"
    interproscan: str = "interproscan.sh"
    emapper: str = "emapper.py"
    eggnog_data: str = ""
    threads: int = 4
    memory_gb: int = 4
    max_sequences: int = 8_000_000
    max_alignment_sequences: int = 5_000
    max_alignment_cells: int = 25_000_000
    command_timeout: int = 86_400
    esm_endpoint: str = ""
    esm_token_env: str = "HF_TOKEN"
    esm_model_revision: str = "b76edc1c2b414f99056aff1e5d91d24a3ea8ba86"
    endpoint_max_length: int = 400
    local_fold_max_length: int = 1_024
    email: str = ""
    auspice_url: str = ""
    centroid_database: str = ""


def bounded_number(
    *, value: object, label: str, minimum: float, maximum: float, integer: bool = False
) -> float | int:
    """Validate one finite, optionally integral workflow control.

    Args:
        value: User or configuration value.
        label: Human-readable control name.
        minimum: Inclusive lower bound.
        maximum: Inclusive upper bound.
        integer: Require an integral value.

    Returns:
        Validated numeric value.

    Raises:
        ResearchError: If the value is Boolean, non-finite or outside bounds.
    """
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResearchError(f"{label} must be numeric") from exc
    if isinstance(value, bool) or not math.isfinite(number) or not minimum <= number <= maximum:
        raise ResearchError(f"{label} must be between {minimum} and {maximum}")
    if integer and not number.is_integer():
        raise ResearchError(f"{label} must be an integer")
    return int(number) if integer else number


def load_config(*, path: Path | None = None) -> ResearchConfig:
    """Load a strict TOML operator profile; default workflows also accept plain FASTA.

    Args:
        path: Explicit profile, otherwise E3_RESEARCH_CONFIG is used if set.

    Returns:
        Validated generic research configuration.

    Raises:
        ResearchError: If a profile contains unknown or invalid settings.
    """
    selected = path or os.environ.get("E3_RESEARCH_CONFIG", "")
    values: dict[str, object] = {}
    if selected:
        try:
            with Path(selected).expanduser().open("rb") as handle:
                values = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ResearchError(f"Could not read research profile: {selected}") from exc
    allowed = {field.name for field in fields(ResearchConfig)}
    unknown = set(values).difference(allowed)
    if unknown:
        raise ResearchError("Unknown research settings: " + ", ".join(sorted(unknown)))
    numeric_fields = (
        ("threads", 256),
        ("memory_gb", 4_096),
        ("max_sequences", 100_000_000),
        ("max_alignment_sequences", 100_000),
        ("max_alignment_cells", 500_000_000),
        ("command_timeout", 604_800),
        ("local_fold_max_length", 10_000),
        ("endpoint_max_length", 10_000),
    )
    for name, maximum in numeric_fields:
        if name in values:
            values[name] = bounded_number(
                value=values[name],
                label=name,
                minimum=1,
                maximum=maximum,
                integer=True,
            )
    if "identifier_prefixes" in values:
        prefixes = values["identifier_prefixes"]
        if not isinstance(prefixes, list) or any(not isinstance(item, str) for item in prefixes):
            raise ResearchError("identifier_prefixes must be an array of strings")
        values["identifier_prefixes"] = tuple(prefixes)
    numeric_names = {name for name, _ in numeric_fields}
    for name in allowed.difference({"workspace", "identifier_prefixes", *numeric_names}):
        if name in values and not isinstance(values[name], str):
            raise ResearchError(f"Invalid research setting: {name}")
    if "workspace" in values and not isinstance(values["workspace"], str):
        raise ResearchError("workspace must be a path string")
    values["workspace"] = (
        Path(values.get("workspace", ResearchConfig().workspace)).expanduser().resolve()
    )
    LOGGER.info("Loaded protein research profile %s", selected or "defaults")
    return ResearchConfig(**values)


def safe_path(*, root: Path, relative: str) -> Path:
    """Resolve a relative artifact beneath a controlled workspace.

    Args:
        root: Trusted artifact root.
        relative: Untrusted relative path.

    Returns:
        Absolute contained path.

    Raises:
        ResearchError: If the name escapes the workspace or addresses its root.
    """
    target = (root / relative).resolve()
    if (
        Path(relative).is_absolute()
        or target == root.resolve()
        or not target.is_relative_to(root.resolve())
    ):
        raise ResearchError("Artifact path must stay inside its research workspace")
    return target


def atomic_json(*, path: Path, value: object) -> None:
    """Write JSON atomically without exposing an incomplete job state.

    Args:
        path: Destination file.
        value: JSON-serialisable value; NaN/Infinity are rejected.
    """
    text = json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, delete=False, encoding="utf-8", prefix=".write-"
    ) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def file_sha256(*, path: Path) -> str:
    """Hash an artifact without collecting it into memory.

    Args:
        path: Existing artifact.

    Returns:
        SHA-256 hexadecimal digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalise_protein(*, sequence: str, aligned: bool = False) -> str:
    """Normalise a protein while recording stop trimming in the caller's QC output.

    Args:
        sequence: Raw sequence; terminal stop symbols are permitted for FASTA imports.
        aligned: Permit alignment gaps and normalise dot gaps to hyphens.

    Returns:
        Upper-case validated protein sequence.

    Raises:
        ResearchError: If sequence is empty or contains internal stops/invalid symbols.
    """
    value = "".join(sequence.split()).upper()
    if not aligned:
        value = value.rstrip("*")
    else:
        value = value.replace(".", "-")
    letters = value.replace("-", "") if aligned else value
    if not letters or not PROTEIN.fullmatch(letters):
        raise ResearchError("Protein sequence is empty or contains invalid residues/internal stops")
    return value


def iter_fasta(*, path: Path, aligned: bool = False) -> Iterator[tuple[str, str]]:
    """Stream validated FASTA records with whitespace-free exact identifiers.

    Args:
        path: UTF-8 FASTA file.
        aligned: Permit alignment gaps.

    Yields:
        Identifier and normalised sequence; duplicate detection belongs to the input audit.

    Raises:
        ResearchError: If content precedes its header or a header is empty.
    """
    identifier: str | None = None
    chunks: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if identifier is not None:
                    yield identifier, normalise_protein(sequence="".join(chunks), aligned=aligned)
                tokens = line[1:].split()
                if not tokens:
                    raise ResearchError("FASTA headers must contain an identifier")
                identifier, chunks = tokens[0], []
                if any(character in identifier for character in "\t\r\n"):
                    raise ResearchError("FASTA identifiers cannot contain control characters")
            elif identifier is None:
                raise ResearchError("FASTA content occurs before its first header")
            else:
                chunks.append(line)
    if identifier is not None:
        yield identifier, normalise_protein(sequence="".join(chunks), aligned=aligned)


def write_tsv(*, path: Path, rows: Sequence[Mapping[str, object]], columns: Sequence[str]) -> None:
    """Write a deterministic tab-separated table, including an empty result's header.

    Args:
        path: Output file.
        rows: Evidence records.
        columns: Ordered table contract.
    """
    with path.open(mode="w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(columns),
            delimiter="\t",
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def utc_now() -> str:
    """Return the UTC time used for provenance.

    Returns:
        ISO-8601 timestamp including its timezone.
    """
    return datetime.now(tz=timezone.utc).isoformat()
