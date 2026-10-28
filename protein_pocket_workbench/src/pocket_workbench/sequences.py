"""Reproducible multiple sequence alignments and exploratory phylogenies."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import logging
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import numpy as np
import pyfamsa
from Bio import Phylo
from Bio.Phylo.TreeConstruction import DistanceMatrix, DistanceTreeConstructor

from .core import (
    WorkbenchError,
    digest_file,
    load_project,
    utc_now,
    write_json,
    write_tsv,
)
from .database import save_project
from .importing import read_fasta

LOGGER = logging.getLogger(__name__)
CANONICAL = set("ACDEFGHIKLMNPQRSTVWY")


def fasta_text(*, records: dict[str, str]) -> str:
    """Encode exact first-token identifiers as FASTA.

    Args:
        records: Identifiers and sequences.

    Returns:
        FASTA text.
    """
    if any(
        not name or any(character.isspace() for character in name) for name in records
    ):
        raise WorkbenchError("FASTA identifiers must be non-empty first tokens")
    return "".join(f">{name}\n{sequence}\n" for name, sequence in records.items())


def infer_tree(
    *, records: dict[str, str], max_gap: float, bootstrap: int, seed: int
) -> tuple[str, str, dict]:
    """Infer an unrooted neighbour-joining p-distance tree from retained columns.

    Args:
        records: Equal-length aligned protein records.
        max_gap: Maximum fraction of non-canonical symbols in a retained column.
        bootstrap: Number of column-resampling replicates, 0–200.
        seed: Random generator seed.

    Returns:
        Raw Newick, display Newick and explicit filtering/support metadata.
    """
    if len(records) < 3 or len(records) > 200:
        raise WorkbenchError("Tree inference needs 3–200 sequences")
    if (
        not np.isfinite(max_gap)
        or not 0 <= max_gap < 1
        or type(bootstrap) is not int
        or not 0 <= bootstrap <= 200
    ):
        raise WorkbenchError("Choose max_gap in [0, 1) and 0–200 bootstrap replicates")
    lengths = {len(value) for value in records.values()}
    if len(lengths) != 1 or not next(iter(lengths)):
        raise WorkbenchError("Tree input must be a non-empty rectangular alignment")
    names = list(records)
    matrix = np.asarray([list(records[name]) for name in names])
    valid = np.isin(matrix, list(CANONICAL))
    retained = np.flatnonzero((1 - valid.mean(axis=0)) <= max_gap)
    if len(retained) < 3:
        raise WorkbenchError("Too few comparable columns remain for a tree")
    matrix = matrix[:, retained]

    def construct(columns: np.ndarray):
        """Build one NJ tree for the provided resampled alignment columns.

        Args:
            columns: Equal-length canonical/gapped rows.

        Returns:
            An unrooted Bio.Phylo tree.
        """
        distance_rows = []
        for i in range(len(names)):
            values = []
            for j in range(i):
                mask = np.isin(columns[i], list(CANONICAL)) & np.isin(
                    columns[j], list(CANONICAL)
                )
                if int(mask.sum()) < min(20, max(3, len(retained) // 10)):
                    raise WorkbenchError(
                        f"Insufficient comparable sites between {names[i]} and"
                        f" {names[j]}"
                    )
                values.append(float(np.mean(columns[i, mask] != columns[j, mask])))
            distance_rows.append(values + [0.0])
        return DistanceTreeConstructor().nj(
            DistanceMatrix(names=names, matrix=distance_rows)
        )

    tree = construct(matrix)
    all_names = frozenset(names)

    def split(clade) -> tuple[str, ...]:
        """Canonicalise an unrooted bipartition independently of root placement.

        Args:
            clade: Bio.Phylo clade.

        Returns:
            The smaller partition, with a deterministic tie break.
        """
        first = frozenset(tip.name for tip in clade.get_terminals())
        second = all_names - first
        return min(
            (tuple(sorted(first)), tuple(sorted(second))),
            key=lambda item: (len(item), item),
        )

    if bootstrap:
        counts: Counter = Counter()
        generator = np.random.default_rng(seed)
        for index in range(bootstrap):
            sampled = matrix[
                :, generator.integers(0, matrix.shape[1], size=matrix.shape[1])
            ]
            replicate = construct(sampled)
            counts.update(
                {
                    split(clade)
                    for clade in replicate.get_nonterminals()
                    if 1 < len(split(clade)) < len(names) - 1
                }
            )
            LOGGER.info("Tree bootstrap %d/%d", index + 1, bootstrap)
        for clade in tree.get_nonterminals():
            key = split(clade)
            if 1 < len(key) < len(names) - 1:
                clade.confidence = 100.0 * counts[key] / bootstrap
    for clade in tree.get_nonterminals():
        clade.name = None
    tree.rooted = False
    raw = io.StringIO()
    Phylo.write(tree, raw, "newick")
    display_tree = copy.deepcopy(tree)
    negatives = 0
    for clade in display_tree.find_clades():
        if clade.branch_length is not None and clade.branch_length < 0:
            negatives += 1
            clade.branch_length = 0.0
    display = io.StringIO()
    Phylo.write(display_tree, display, "newick")
    return (
        raw.getvalue(),
        display.getvalue(),
        {
            "retained_columns": len(retained),
            "retained_column_indices_1based": (retained + 1).tolist(),
            "max_gap_fraction": max_gap,
            "bootstrap_replicates": bootstrap,
            "seed": seed,
            "negative_branches_display_clipped": negatives,
            "tree_method": (
                "unrooted neighbour joining; pairwise-deletion protein p-distance"
            ),
        },
    )


def validate_tree(*, text: str, sequence_ids: set[str]) -> str:
    """Validate a user-supplied Newick tree against exactly the aligned records.

    Args:
        text: Newick text from a supported external inference tool.
        sequence_ids: Exact alignment identifiers.

    Returns:
        Validated Newick text, with support values preserved.
    """
    if len(text) > 5_000_000:
        raise WorkbenchError("Newick file exceeds 5 MiB")
    try:
        tree = Phylo.read(io.StringIO(text), "newick")
    except (ValueError, IndexError) as error:
        raise WorkbenchError("Cannot parse a single Newick tree") from error
    leaves = [tip.name for tip in tree.get_terminals()]
    if set(leaves) != sequence_ids or len(leaves) != len(set(leaves)):
        raise WorkbenchError(
            "Tree tip names must match the selected FASTA/alignment IDs exactly"
        )
    if any(
        clade.branch_length is not None and not np.isfinite(clade.branch_length)
        for clade in tree.find_clades()
    ):
        raise WorkbenchError("Tree branch lengths must be finite")
    return text


def analyse_sequences(
    *,
    root: Path,
    sequence_ids: list[str] | None = None,
    engine: str = "famsa",
    aligned_fasta: Path | None = None,
    newick: Path | None = None,
    max_gap: float = 0.5,
    bootstrap: int = 0,
    seed: int = 42,
    threads: int = 4,
    timeout: int = 3600,
) -> dict:
    """Align unique sequence records and retain a reproducible tree analysis.

    Args:
        root: Resource directory.
        sequence_ids: Exact selected FASTA IDs, or all unique records.
        engine: famsa or mafft; imported alignment takes precedence.
        aligned_fasta: Optional existing aligned FASTA.
        newick: Optional tree whose leaf names match the alignment.
        max_gap: Column filtering rule for tree inference only.
        bootstrap: Column resampling replicate count.
        seed: Bootstrap seed.
        threads: Explicit worker threads.
        timeout: External MAFFT command timeout.

    Returns:
        Completed analysis metadata and relative artifact paths.
    """
    if (
        engine not in {"famsa", "mafft"}
        or type(threads) is not int
        or not 1 <= threads <= 128
        or not 1 <= timeout <= 86400
    ):
        raise WorkbenchError(
            "Choose famsa/mafft, 1–128 threads and a positive bounded timeout"
        )
    data = load_project(root=root)
    selected = sequence_ids or list(data["sequences"])
    if len(set(selected)) != len(selected) or any(
        name not in data["sequences"] for name in selected
    ):
        raise WorkbenchError("Choose unique existing sequence identifiers")
    records = {name: data["sequences"][name] for name in selected}
    if (
        not 1 <= len(records) <= 200
        or sum(len(value) for value in records.values()) > 2_000_000
    ):
        raise WorkbenchError(
            "Sequence analysis supports 1–200 records and 2 million residues"
        )
    identity = {
        "records": records,
        "engine": engine,
        "max_gap": max_gap,
        "bootstrap": bootstrap,
        "seed": seed,
        "threads": threads,
        "aligned_sha": digest_file(path=aligned_fasta) if aligned_fasta else None,
        "newick_sha": digest_file(path=newick) if newick else None,
        "pyfamsa_version": pyfamsa.__version__,
    }
    identifier = (
        "msa_"
        + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    )
    directory = root / "sequence_analyses" / identifier
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "input.fasta").write_text(fasta_text(records=records))
    if aligned_fasta:
        alignment = read_fasta(path=aligned_fasta, aligned=True)
        if set(alignment) != set(records) or any(
            alignment[name].replace("-", "").replace(".", "") != records[name]
            for name in records
        ):
            raise WorkbenchError(
                "Imported alignment must preserve every selected ungapped sequence"
                " exactly"
            )
        method = "imported aligned FASTA"
    elif len(records) == 1:
        alignment, method = records, "single sequence; no MSA needed"
    elif engine == "famsa":
        aliases = {f"sequence_{index}": name for index, name in enumerate(records)}
        sequences = [
            pyfamsa.Sequence(alias.encode(), records[name].encode())
            for alias, name in aliases.items()
        ]
        aligned = pyfamsa.Aligner(
            threads=threads, guide_tree="upgma", keep_duplicates=True
        ).align(sequences)
        alignment = {aliases[row.id.decode()]: row.sequence.decode() for row in aligned}
        method = f"FAMSA / pyfamsa {pyfamsa.__version__}; UPGMA guide tree"
    else:
        executable = shutil.which("mafft")
        if executable is None:
            raise WorkbenchError("MAFFT is unavailable; install it or select FAMSA")
        aliases = {f"sequence_{index}": name for index, name in enumerate(records)}
        source = directory / "mafft_input.fasta"
        source.write_text(
            fasta_text(
                records={alias: records[name] for alias, name in aliases.items()}
            )
        )
        command = [
            executable,
            "--auto",
            "--amino",
            "--thread",
            str(threads),
            str(source),
        ]
        write_json(
            path=directory / "command.json",
            value={
                "argv": command,
                "executable_sha256": digest_file(path=Path(executable)),
                "timeout": timeout,
            },
        )
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=timeout
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WorkbenchError(f"MAFFT could not complete: {error}") from error
        (directory / "stderr.log").write_text(completed.stderr)
        output = directory / "mafft_output.fasta"
        output.write_text(completed.stdout)
        if completed.returncode:
            raise WorkbenchError("MAFFT failed; inspect stderr.log")
        alignment = {
            aliases[key]: value
            for key, value in read_fasta(path=output, aligned=True).items()
        }
        method = "MAFFT --auto --amino"
    alignment = {name: alignment[name] for name in records}
    if len({len(value) for value in alignment.values()}) != 1:
        raise WorkbenchError("Aligner returned a non-rectangular alignment")
    (directory / "alignment.fasta").write_text(fasta_text(records=alignment))
    metadata = {
        "tree_method": "none; fewer than three sequences",
        "retained_columns": 0,
        "bootstrap_replicates": 0,
    }
    if newick:
        tree = validate_tree(text=newick.read_text(), sequence_ids=set(alignment))
        (directory / "tree.newick").write_text(tree)
        metadata = {
            "tree_method": "user-supplied Newick; original support retained",
            "retained_columns": None,
            "bootstrap_replicates": None,
        }
    elif len(alignment) >= 3:
        raw, display, metadata = infer_tree(
            records=alignment, max_gap=max_gap, bootstrap=bootstrap, seed=seed
        )
        (directory / "tree_raw.newick").write_text(raw)
        (directory / "tree.newick").write_text(display)
    result = dict(
        metadata,
        analysis_id=identifier,
        alignment_method=method,
        sequence_count=len(alignment),
        alignment_length=len(next(iter(alignment.values()))),
        alignment_path=(directory / "alignment.fasta").relative_to(root).as_posix(),
        tree_path=(
            (directory / "tree.newick").relative_to(root).as_posix()
            if (directory / "tree.newick").is_file()
            else None
        ),
        created_utc=utc_now(),
        settings=identity,
    )
    write_tsv(
        path=directory / "sequence_to_models.tsv",
        rows=[
            {
                "sequence_id": name,
                "models": ";".join(
                    row["sample_id"]
                    for row in data["models"]
                    if row.get("sequence_id") == name
                ),
            }
            for name in records
        ],
        columns=["sequence_id", "models"],
    )
    write_json(path=directory / "methods.json", value=result)
    from .viewers import alignment_document

    msa_text = (directory / "alignment.fasta").read_text()
    tree_text = (directory / "tree.newick").read_text() if result["tree_path"] else ""
    for viewer, filename in (
        ("jbrowse", "alignment_tree.html"),
        ("alignment", "alignment_viewer.html"),
    ):
        (directory / filename).write_text(
            alignment_document(msa=msa_text, tree=tree_text, viewer=viewer),
            encoding="utf-8",
        )
    data["sequence_analyses"] = [
        row for row in data["sequence_analyses"] if row["analysis_id"] != identifier
    ] + [result]
    save_project(root=root, data=data)
    LOGGER.info("Completed sequence analysis %s", identifier)
    return result
