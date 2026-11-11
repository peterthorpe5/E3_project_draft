"""Validate standalone viewer uploads and prepare jobs for another machine."""

from __future__ import annotations

import csv
from io import BytesIO, StringIO
import json
import logging
import math
from typing import Mapping, Sequence
from zipfile import ZIP_DEFLATED, ZipFile

from Bio import Phylo
from Bio.Phylo.NewickIO import NewickError

from .common import ResearchError, fasta_records

LOGGER = logging.getLogger(__name__)
UPLOAD_BYTES = 20_000_000
TREE_BYTES = 2_000_000


def uploaded_proteins(
    *, text: str, aligned: bool = False, maximum_records: int = 5_000,
    maximum_cells: int = 25_000_000,
) -> dict[str, str]:
    """Read bounded FASTA records with unique IDs and, for an MSA, equal widths.

    Args:
        text: UTF-8 protein FASTA.
        aligned: Interpret input as an existing alignment.
        maximum_records: Maximum number of records accepted.
        maximum_cells: Maximum total residues and gap characters.

    Returns:
        Exact ID-to-sequence mapping in input order.

    Raises:
        ResearchError: For invalid, empty, ambiguous or oversized input.
    """
    if len(text.encode()) > UPLOAD_BYTES:
        raise ResearchError("Protein FASTA exceeds 20 MB")
    result = {}
    cells = 0
    width = None
    for identifier, sequence in fasta_records(lines=StringIO(text), aligned=aligned):
        if identifier in result:
            raise ResearchError(f"Duplicate FASTA identifier: {identifier}")
        if aligned and width is not None and len(sequence) != width:
            raise ResearchError("Aligned FASTA rows must have equal lengths, including gaps")
        width = len(sequence)
        cells += width
        if len(result) >= maximum_records or cells > maximum_cells:
            raise ResearchError("FASTA exceeds the allowed sequence or residue count")
        result[identifier] = sequence
    if not result:
        raise ResearchError("Supply at least one protein FASTA record")
    LOGGER.info("Validated %d uploaded proteins, aligned=%s", len(result), aligned)
    return result


def validate_protein_tree(*, newick: str, identifiers: Sequence[str]) -> str:
    """Check that a supplied protein tree has exactly the alignment's unique tip IDs.

    Args:
        newick: Complete Newick tree text.
        identifiers: Exact aligned protein identifiers.

    Returns:
        Validated Newick text for display.

    Raises:
        ResearchError: If topology text, tip names or branch lengths are invalid.
    """
    if len(newick.encode()) > TREE_BYTES or not newick.strip().endswith(";"):
        raise ResearchError("Supply a complete protein Newick tree of at most 2 MB")
    try:
        tree = Phylo.read(file=StringIO(newick), format="newick")
        labels = [tip.name for tip in tree.get_terminals()]
    except (ValueError, TypeError, NewickError, RecursionError) as exc:
        raise ResearchError("Could not parse the protein Newick tree") from exc
    if len(labels) != len(identifiers) or set(labels) != set(identifiers):
        raise ResearchError("Protein-tree tips must match the aligned FASTA IDs exactly")
    if any(branch.branch_length is not None and (
        not math.isfinite(branch.branch_length) or branch.branch_length < 0
    ) for branch in tree.find_clades()):
        raise ResearchError("Protein-tree branch lengths must be finite and non-negative")
    return newick.strip()


def read_species_mapping(*, text: str) -> dict[str, dict[str, str]]:
    """Read one reviewed species and taxon assignment per exact protein ID.

    Args:
        text: Tab-separated sequence_id, species and taxon_id columns.

    Returns:
        Metadata indexed by the exact sequence ID.

    Raises:
        ResearchError: For absent columns, duplicate IDs or empty assignments.
    """
    reader = csv.DictReader(StringIO(text), delimiter="\t")
    if not {"sequence_id", "species", "taxon_id"}.issubset(reader.fieldnames or ()):
        raise ResearchError("Species mapping requires sequence_id, species and taxon_id columns")
    metadata = {}
    for row in reader:
        identifier = (row["sequence_id"] or "").strip()
        species = (row["species"] or "").strip()
        taxon_id = (row["taxon_id"] or "").strip()
        if not identifier or identifier in metadata or not (species or taxon_id):
            raise ResearchError("Each protein needs one non-empty, unique species mapping")
        metadata[identifier] = {"species": species, "taxon_id": taxon_id}
    return metadata


def portable_job_archive(
    *, operation: str, parameters: Mapping[str, object], fasta: str,
) -> bytes:
    """Package a FASTA-based request for the installed research CLI on another machine.

    Args:
        operation: Alignment, annotation or prediction operation.
        parameters: Named scientific settings for the selected operation.
        fasta: Complete input FASTA, independent of the submitting workspace.

    Returns:
        ZIP containing FASTA, JSON parameters and CLI instructions.

    Raises:
        ResearchError: If the request depends on a local job or has invalid input.
    """
    if operation not in {"align", "annotate", "predict"} or any(
        parameters.get(key) for key in ("source_job", "source_artifact", "subcluster_id")
    ):
        raise ResearchError("Use a standalone FASTA for an alignment, annotation or model job")
    records = uploaded_proteins(text=fasta, maximum_records=100_000)
    sequence_ids = parameters.get("sequence_ids", [])
    if not isinstance(sequence_ids, list) or any(
        not isinstance(value, str) for value in sequence_ids
    ):
        raise ResearchError("Choose an explicit list of exact protein IDs")
    requested = set(sequence_ids)
    missing = requested.difference(records)
    if missing:
        raise ResearchError(f"Requested protein is absent from the FASTA: {min(missing)}")
    if operation == "predict" and len(requested or records) > 100:
        raise ResearchError("Select at most 100 proteins for ESMFold")
    instructions = (
        "Run on the machine with the required tools and your research profile.\n"
        "Set E3_RESEARCH_CONFIG to the absolute path of that machine's research.toml.\n"
        "Run these commands from the directory containing input.fasta and parameters.json.\n\n"
        'protein-research-workbench --config "$E3_RESEARCH_CONFIG" doctor\n'
        'JOB_ID=$(protein-research-workbench --config "$E3_RESEARCH_CONFIG" submit \\\n'
        f"  --operation {operation} --parameters parameters.json --fasta input.fasta) &&\n"
        '  protein-research-workbench --config "$E3_RESEARCH_CONFIG" worker --once '
        '--job-id "$JOB_ID"\n\n'
        "Results are under jobs/$JOB_ID in the worker profile's workspace.\n"
        "Alignment: open alignment.fasta and optional tree.nwk in JBrowse MSA.\n"
        "Annotation: open annotation_input.fasta and annotations.tsv in Nightingale.\n"
        "Model: open the model PDB with its original protein FASTA in ESMFold & models.\n"
    )
    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("input.fasta", fasta)
        archive.writestr("parameters.json", json.dumps(dict(parameters), indent=2, allow_nan=False))
        archive.writestr("READ_ME.txt", instructions)
    LOGGER.info("Prepared portable %s job for %d FASTA records", operation, len(records))
    return buffer.getvalue()
