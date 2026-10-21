"""External protein-family analyses, exact cluster audits and alignment statistics."""

from __future__ import annotations

from collections import Counter
import csv
import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path
import shlex
import shutil
import signal
import sqlite3
import subprocess
import tempfile
from typing import Mapping

from Bio import Phylo
from Bio.Phylo.NewickIO import NewickError
from Bio.Align import substitution_matrices
import duckdb
import pandas as pd

from .common import (
    ResearchConfig,
    ResearchError,
    atomic_json,
    bounded_number,
    iter_fasta,
    utc_now,
    write_tsv,
)

LOGGER = logging.getLogger(__name__)
REALIGN_FIELDS = (
    "qseqid",
    "sseqid",
    "pident",
    "qlen",
    "slen",
    "qstart",
    "qend",
    "sstart",
    "send",
    "length",
    "evalue",
    "bitscore",
    "nident",
)
AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")


def run_command(
    *, arguments: list[str], output: Path, config: ResearchConfig, stdout: Path | None = None
) -> None:
    """Execute a configured scientific tool without a shell, logging its exact argv.

    Args:
        arguments: Executable and explicit arguments; never a shell command string.
        output: Owned job directory for logs and command provenance.
        config: Runtime resource/timeout settings.
        stdout: Optional separate scientific stdout artifact, e.g. MAFFT FASTA.

    Raises:
        ResearchError: If the executable is absent, times out or exits unsuccessfully.
    """
    if not arguments or shutil.which(arguments[0]) is None:
        raise ResearchError(
            f"Required executable is unavailable: {arguments[0] if arguments else 'empty'}"
        )
    with (output / "commands.jsonl").open(mode="a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"argv": arguments, "timeout_seconds": config.command_timeout}) + "\n"
        )
    LOGGER.info("Running %s", shlex.join(arguments))
    with (output / "worker.log").open(mode="a", encoding="utf-8") as log:
        with (stdout or output / "stdout.log").open(mode="w", encoding="utf-8") as result:
            process = subprocess.Popen(arguments, stdout=result, stderr=log, start_new_session=True)
            try:
                return_code = process.wait(timeout=config.command_timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait()
                if isinstance(exc, KeyboardInterrupt):
                    raise
                raise ResearchError("Scientific command exceeded its timeout") from exc
    if return_code:
        raise ResearchError(
            f"Scientific command failed ({return_code}); inspect the job's worker.log"
        )


def index_fasta(*, source: Path, destination: Path, maximum: int) -> tuple[sqlite3.Connection, int]:
    """Index validated proteins on disk, detecting duplicate IDs without a giant in-memory set.

    Args:
        source: Protein FASTA.
        destination: New SQLite staging database.
        maximum: Maximum complete input size; no silent truncation.

    Returns:
        Open staging connection and record count; the caller closes the connection.

    Raises:
        ResearchError: If identifiers repeat, input is empty or the bound is exceeded.
    """
    connection = sqlite3.connect(database=destination)
    try:
        connection.execute(
            "CREATE TABLE sequences(id TEXT PRIMARY KEY,sequence TEXT NOT NULL,hash TEXT NOT NULL)"
        )
        count = 0
        for identifier, sequence in iter_fasta(path=source):
            count += 1
            if count > maximum:
                raise ResearchError("Complete FASTA input exceeds the configured sequence bound")
            try:
                connection.execute(
                    "INSERT INTO sequences VALUES (?,?,?)",
                    (
                        identifier,
                        sequence,
                        hashlib.sha256(identifier.encode()).hexdigest(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ResearchError(f"Duplicate FASTA identifier: {identifier}") from exc
            if count % 10_000 == 0:
                connection.commit()
        if not count:
            raise ResearchError("Protein FASTA contains no records")
        connection.commit()
        return connection, count
    except BaseException:
        connection.close()
        raise


def audit_subclusters(
    *,
    membership: Path,
    realignments: Path,
    source_ids: Path,
    output: Path,
    identity: float,
    coverage: float,
    evalue: float,
    config: ResearchConfig,
) -> dict[str, Path]:
    """Audit exact representative-member alignments and retain failures as singletons.

    Args:
        membership: Native headered DIAMOND membership.
        realignments: Headerless exact alignment fields in REALIGN_FIELDS order.
        source_ids: Complete input sequence_id table.
        output: Owned job directory.
        identity: Required exact identity percentage.
        coverage: Required percentage in each direction.
        evalue: Maximum exact realignment E-value.
        config: DuckDB memory/thread settings.

    Returns:
        Raw/exact audited membership and subcluster summary artifact paths.

    Raises:
        ResearchError: If membership is incomplete, duplicated or references invalid sequences.
    """
    with membership.open(encoding="utf-8") as handle:
        header = next(csv.reader(handle, delimiter="\t"), [])
    if tuple(header) not in {
        ("centroid", "member"),
        ("representative", "member"),
        ("cluster", "member"),
    }:
        raise ResearchError("Unrecognised DIAMOND cluster membership header")
    with duckdb.connect(
        config={"memory_limit": f"{config.memory_gb}GB", "threads": config.threads}
    ) as connection:
        connection.read_csv(
            str(membership), delimiter="\t", header=True, all_varchar=True
        ).create_view("native")
        connection.read_csv(
            str(source_ids), delimiter="\t", header=True, all_varchar=True
        ).create_view("inputs")
        representative = '"' + header[0] + '"'
        connection.execute(
            f"CREATE VIEW membership AS SELECT {representative} AS representative_id, "
            "member AS sequence_id FROM native"
        )
        invalid = connection.execute("""
            SELECT 1 FROM (
                SELECT sequence_id FROM membership GROUP BY sequence_id HAVING count(*)<>1
                UNION ALL SELECT sequence_id FROM inputs ANTI JOIN membership USING(sequence_id)
                UNION ALL SELECT sequence_id FROM membership ANTI JOIN inputs USING(sequence_id)
                UNION ALL SELECT representative_id FROM membership m
                    WHERE NOT EXISTS(SELECT 1 FROM membership r
                        WHERE r.sequence_id=m.representative_id
                        AND r.representative_id=m.representative_id)
            ) LIMIT 1
        """).fetchone()
        if invalid:
            raise ResearchError(
                "DIAMOND membership does not cover every input exactly once with a valid centroid"
            )
        if realignments.stat().st_size:
            columns = {
                name: "VARCHAR" if name in {"qseqid", "sseqid"} else "DOUBLE"
                for name in REALIGN_FIELDS
            }
            connection.read_csv(
                str(realignments), delimiter="\t", header=False, columns=columns
            ).create_view("raw_alignments")
        else:
            connection.execute(
                "CREATE TABLE raw_alignments("
                + ",".join(
                    f"{name} {'VARCHAR' if name in {'qseqid', 'sseqid'} else 'DOUBLE'}"
                    for name in REALIGN_FIELDS
                )
                + ")"
            )
        connection.execute("""
            CREATE VIEW best_alignments AS
            SELECT * EXCLUDE(pident),100*nident/nullif(length,0) AS pident,
                100*(abs(qend-qstart)+1)/nullif(qlen,0) AS representative_coverage,
                100*(abs(send-sstart)+1)/nullif(slen,0) AS member_coverage
            FROM raw_alignments QUALIFY row_number() OVER (
                PARTITION BY qseqid,sseqid ORDER BY bitscore DESC,evalue ASC,pident DESC)=1
        """)
        connection.execute(
            """
            CREATE TABLE audited AS
            WITH evidence AS (
                SELECT m.*,a.pident,a.representative_coverage,a.member_coverage,a.evalue,a.bitscore,
                    CASE WHEN m.sequence_id=m.representative_id THEN 'CENTROID_SELF'
                         WHEN a.qseqid IS NULL THEN 'NO_REALIGNMENT'
                         WHEN a.pident IS NULL OR a.evalue IS NULL OR a.bitscore IS NULL
                           OR NOT isfinite(a.pident) OR NOT isfinite(a.evalue)
                           OR NOT isfinite(a.bitscore) OR a.qlen<=0 OR a.slen<=0
                           OR a.length<=0 OR a.nident NOT BETWEEN 0 AND a.length
                           OR a.nident IS NULL OR floor(a.nident)<>a.nident
                           OR a.qstart NOT BETWEEN 1 AND a.qlen OR a.qend NOT BETWEEN 1 AND a.qlen
                           OR a.sstart NOT BETWEEN 1 AND a.slen OR a.send NOT BETWEEN 1 AND a.slen
                           OR a.qlen IS NULL OR a.slen IS NULL OR a.qstart IS NULL
                           OR a.qend IS NULL OR a.sstart IS NULL OR a.send IS NULL
                           OR a.pident NOT BETWEEN 0 AND 100 OR a.evalue<0
                           OR a.representative_coverage NOT BETWEEN 0 AND 100
                           OR a.member_coverage NOT BETWEEN 0 AND 100 THEN 'INVALID_REALIGNMENT'
                         WHEN a.pident>=? AND a.representative_coverage>=?
                           AND a.member_coverage>=? AND a.evalue<=? AND a.bitscore>20
                           THEN 'EXACT_THRESHOLDS_PASS'
                         ELSE 'EXACT_THRESHOLDS_FAIL' END AS alignment_status
                FROM membership m LEFT JOIN best_alignments a
                    ON a.qseqid=m.representative_id AND a.sseqid=m.sequence_id
            ), assigned AS (
                SELECT *,CASE WHEN alignment_status IN ('CENTROID_SELF','EXACT_THRESHOLDS_PASS')
                    THEN representative_id ELSE sequence_id END AS audited_representative_id
                FROM evidence
            )
            SELECT 'sub_' || substr(sha256(audited_representative_id),1,24) AS subcluster_id,
                audited_representative_id,sequence_id,representative_id AS native_representative_id,
                alignment_status,pident,representative_coverage,member_coverage,evalue,bitscore
            FROM assigned ORDER BY subcluster_id,sequence_id
        """,
            [identity, coverage, coverage, evalue],
        )
        connection.table("audited").write_parquet(
            str(output / "membership.parquet"), compression="zstd"
        )
        connection.sql("SELECT * FROM audited").write_csv(
            str(output / "membership.tsv"), sep="\t", header=True
        )
        connection.sql("""
            SELECT subcluster_id,min(audited_representative_id) AS representative_id,
                count(*) AS member_count,count(*) FILTER (WHERE alignment_status NOT IN
                ('CENTROID_SELF','EXACT_THRESHOLDS_PASS')) AS rescued_singleton_count,
                min(pident) FILTER (WHERE alignment_status='EXACT_THRESHOLDS_PASS')
                    AS minimum_passing_identity,
                min(representative_coverage) FILTER (WHERE alignment_status='EXACT_THRESHOLDS_PASS')
                    AS minimum_passing_representative_coverage,
                min(member_coverage) FILTER (WHERE alignment_status='EXACT_THRESHOLDS_PASS')
                    AS minimum_passing_member_coverage
            FROM audited GROUP BY subcluster_id ORDER BY member_count DESC,subcluster_id
        """).write_csv(str(output / "subclusters.tsv"), sep="\t", header=True)
    return {
        name: output / name for name in ("membership.parquet", "membership.tsv", "subclusters.tsv")
    }


def subcluster(
    *, config: ResearchConfig, source: Path, output: Path, parameters: Mapping[str, object]
) -> dict[str, Path]:
    """Run stricter DIAMOND DeepClust and audit every native assignment by realignment.

    Args:
        config: Trusted executable/resource configuration.
        source: Complete input cluster FASTA.
        output: Owned job directory.
        parameters: Identity, mutual_coverage and evalue controls.

    Returns:
        Sequence, native clustering, exact membership and summary artifacts.
    """
    identity = bounded_number(
        value=parameters.get("identity", 70), label="Identity", minimum=1, maximum=100
    )
    coverage = bounded_number(
        value=parameters.get("mutual_coverage", 80), label="Mutual coverage", minimum=1, maximum=100
    )
    evalue = bounded_number(
        value=parameters.get("evalue", 1e-10), label="E-value", minimum=1e-300, maximum=1
    )
    sequences = output / "sequences.fasta"
    connection, count = index_fasta(
        source=source, destination=output / "input.sqlite", maximum=config.max_sequences
    )
    try:
        with sequences.open(mode="w", encoding="utf-8") as fasta:
            with (output / "input_ids.tsv").open(mode="w", encoding="utf-8") as identifiers:
                identifiers.write("sequence_id\n")
                for identifier, sequence in connection.execute(
                    "SELECT id,sequence FROM sequences ORDER BY id"
                ):
                    fasta.write(f">{identifier}\n{sequence}\n")
                    identifiers.write(identifier + "\n")
    finally:
        connection.close()
    base = [config.diamond]
    run_command(
        arguments=[*base, "version"],
        output=output,
        config=config,
        stdout=output / "diamond_version.txt",
    )
    run_command(
        arguments=[
            *base,
            "makedb",
            "--in",
            str(sequences),
            "--db",
            str(output / "proteins"),
            "--threads",
            str(config.threads),
        ],
        output=output,
        config=config,
    )
    temporary_root = Path(os.environ.get("TMPDIR", config.workspace / "temporary"))
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temporary_root, prefix="protein-subcluster-") as temporary:
        common = [
            "--db",
            str(output / "proteins.dmnd"),
            "--threads",
            str(config.threads),
            "--memory-limit",
            f"{config.memory_gb}G",
            "--tmpdir",
            temporary,
        ]
        run_command(
            arguments=[
                *base,
                "deepclust",
                *common,
                "--id",
                str(identity),
                "--mutual-cover",
                str(coverage),
                "--evalue",
                str(evalue),
                "--out",
                str(output / "native_membership.tsv"),
                "--header",
            ],
            output=output,
            config=config,
        )
        # Native realign consumes two data columns, including no header row.
        with (output / "native_membership.tsv").open(encoding="utf-8") as native:
            with (output / "realign_membership.tsv").open(mode="w", encoding="utf-8") as pairs:
                header = native.readline().rstrip("\n").split("\t")
                if tuple(header) not in {
                    ("centroid", "member"),
                    ("representative", "member"),
                    ("cluster", "member"),
                }:
                    raise ResearchError("Unrecognised DIAMOND membership header before realignment")
                shutil.copyfileobj(native, pairs)
        run_command(
            arguments=[
                *base,
                "realign",
                *common,
                "--clusters",
                str(output / "realign_membership.tsv"),
                "--out",
                str(output / "exact_alignments.tsv"),
                "--outfmt",
                "6",
                *REALIGN_FIELDS,
                "--comp-based-stats",
                "0",
            ],
            output=output,
            config=config,
        )
    result = audit_subclusters(
        membership=output / "native_membership.tsv",
        realignments=output / "exact_alignments.tsv",
        source_ids=output / "input_ids.tsv",
        output=output,
        identity=float(identity),
        coverage=float(coverage),
        evalue=float(evalue),
        config=config,
    )
    result.update(
        {
            name: output / name
            for name in (
                "sequences.fasta",
                "native_membership.tsv",
                "exact_alignments.tsv",
                "diamond_version.txt",
            )
        }
    )
    atomic_json(
        path=output / "subcluster_settings.json",
        value={
            "input_sequences": count,
            "exact_identity_percent": identity,
            "mutual_coverage_percent": coverage,
            "maximum_evalue": evalue,
            "minimum_bitscore_exclusive": 20,
            "interpretation": (
                "Thresholds audited against the assigned centroid, not every member pair;"
                " failures retained as singletons."
            ),
        },
    )
    result["subcluster_settings.json"] = output / "subcluster_settings.json"
    return result


def alignment_statistics(
    *, alignment: Path, reference_id: str, maximum_cells: int, output: Path
) -> dict[str, Path]:
    """Calculate alignment-column and reference-to-member statistics without all-pairs work.

    Args:
        alignment: Aligned protein FASTA with unique IDs and equal-length rows.
        reference_id: Exact selected ungapped reference identifier.
        maximum_cells: Matrix size bound.
        output: Owned output directory.

    Returns:
        Column and member TSV plus summary JSON artifacts. Identity denominators
        contain positions with canonical residues in both rows; unknowns are excluded.

    Raises:
        ResearchError: If alignment dimensions, IDs or reference are invalid.
    """
    records: dict[str, str] = {}
    longest = 0
    for identifier, sequence in iter_fasta(path=alignment, aligned=True):
        if identifier in records:
            raise ResearchError("Alignment contains duplicate sequence identifiers")
        records[identifier] = sequence
        longest = max(longest, len(sequence))
        if len(records) * longest > maximum_cells:
            raise ResearchError("Alignment exceeds the configured matrix size bound")
    lengths = {len(value) for value in records.values()}
    if len(lengths) != 1 or reference_id not in records:
        raise ResearchError(
            "Alignment rows must have equal length and contain the selected reference"
        )
    reference = records[reference_id]
    nrows = len(records)
    columns: list[dict[str, object]] = []
    reference_position = 0
    for position in range(len(reference)):
        residues = [value[position] for value in records.values()]
        counts = Counter(value for value in residues if value in AMINO_ACIDS)
        known = sum(counts.values())
        consensus, maximum = (
            sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0] if known else (None, 0)
        )
        if reference[position] != "-":
            reference_position += 1
        columns.append(
            {
                "alignment_column": position + 1,
                "reference_position": reference_position if reference[position] != "-" else None,
                "gap_fraction": residues.count("-") / nrows,
                "canonical_residue_fraction": known / nrows,
                "consensus_residue": consensus,
                "consensus_fraction_of_known": maximum / known if known else None,
                "shannon_entropy_bits": (
                    -sum((count / known) * math.log2(count / known) for count in counts.values())
                    if known
                    else None
                ),
            }
        )
    matrix = substitution_matrices.load(name="BLOSUM62")
    rows: list[dict[str, object]] = []
    reference_length = len(reference.replace("-", ""))
    for identifier, sequence in records.items():
        comparable = [
            (a, b)
            for a, b in zip(reference, sequence, strict=True)
            if a in AMINO_ACIDS and b in AMINO_ACIDS
        ]
        overlap = sum(a != "-" and b != "-" for a, b in zip(reference, sequence, strict=True))
        member_length = len(sequence.replace("-", ""))
        rows.append(
            {
                "sequence_id": identifier,
                "reference_id": reference_id,
                "sequence_length": member_length,
                "comparable_residue_count": len(comparable),
                "identity_to_reference_fraction": (
                    sum(a == b for a, b in comparable) / len(comparable) if comparable else None
                ),
                "reference_overlap_fraction": overlap / reference_length,
                "member_overlap_fraction": overlap / member_length,
                "blosum62_sum_over_comparable_positions": sum(
                    float(matrix[a, b]) for a, b in comparable
                ),
            }
        )
    write_tsv(path=output / "alignment_columns.tsv", rows=columns, columns=list(columns[0]))
    write_tsv(path=output / "alignment_members.tsv", rows=rows, columns=list(rows[0]))
    atomic_json(
        path=output / "alignment_summary.json",
        value={
            "aligned_sequence_count": nrows,
            "alignment_length": len(reference),
            "reference_id": reference_id,
            "mean_gap_fraction": sum(row["gap_fraction"] for row in columns) / len(columns),
            "statistics_scope": "Reference-to-member statistics; no all-pairs calculation.",
            "blosum_scope": (
                "Raw BLOSUM62 sum over comparable aligned residues; no gap penalty; not a"
                " search significance score."
            ),
        },
    )
    return {
        name: output / name
        for name in ("alignment_columns.tsv", "alignment_members.tsv", "alignment_summary.json")
    }


def auspice_dataset(
    *, newick: str, metadata: Mapping[str, Mapping[str, object]], title: str
) -> dict[str, object]:
    """Convert an inferred protein tree to Auspice v2 divergence JSON without invented dates.

    Args:
        newick: Actual inferred Newick tree.
        metadata: Reviewed species/subcluster traits by exact tip identifier.
        title: Dataset title.

    Returns:
        Auspice v2 dataset with cumulative substitutions-per-site divergence.

    Raises:
        ResearchError: If tip names/branches are invalid or the tree is excessively deep.
    """
    try:
        tree = Phylo.read(io.StringIO(newick), "newick")
    except (ValueError, TypeError, NewickError) as exc:
        raise ResearchError("Could not parse the inferred Newick tree") from exc
    tip_names = [tip.name for tip in tree.get_terminals()]
    if not tip_names or None in tip_names or len(tip_names) != len(set(tip_names)):
        raise ResearchError("Phylogenetic tips must have unique identifiers")
    result: dict[str, object] = {}
    stack = [(tree.root, result, 0.0, 0)]
    node_number = 0
    used = set(tip_names)
    while stack:
        clade, node, parent_divergence, depth = stack.pop()
        if depth > 400:
            raise ResearchError("Tree nesting exceeds the safe portable JSON depth")
        length = clade.branch_length or 0.0
        if not math.isfinite(length) or length < 0:
            raise ResearchError("Tree contains invalid branch lengths")
        divergence = parent_divergence + length
        node_number += 1
        name = clade.name if clade.is_terminal() else f"INTERNAL_{node_number}"
        while not clade.is_terminal() and name in used:
            name += "_"
        used.add(name)
        node.update({"name": name, "node_attrs": {"div": divergence}})
        if clade.confidence is not None:
            node["node_attrs"]["local_support"] = {"value": float(clade.confidence)}
        if clade.is_terminal():
            for field in ("species", "subcluster_id", "taxon_id"):
                value = metadata.get(name, {}).get(field)
                if value is not None and str(value):
                    node["node_attrs"][field] = {"value": str(value)}
        else:
            node["children"] = [{} for _ in clade.clades]
            stack.extend(
                (child, target, divergence, depth + 1)
                for child, target in zip(clade.clades, node["children"], strict=True)
            )
    return {
        "version": "v2",
        "meta": {
            "title": title,
            "updated": utc_now().split("T", 1)[0],
            "panels": ["tree"],
            "description": (
                "Protein phylogeny; branch lengths are divergence, not time. Root "
                "placement is not an inferred ancestor."
            ),
            "colorings": [
                {"key": field, "title": field.replace("_", " ").title(), "type": "categorical"}
                for field in ("species", "subcluster_id", "taxon_id")
            ],
            "filters": ["species", "subcluster_id", "taxon_id"],
            "display_defaults": {
                "distance_measure": "div",
                "layout": "rect",
                "color_by": "species",
            },
        },
        "tree": result,
    }


def align_family(
    *,
    config: ResearchConfig,
    source: Path,
    output: Path,
    parameters: Mapping[str, object],
    membership: Path | None = None,
    metadata: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, Path]:
    """Align a complete selected family or an explicitly requested deterministic sample.

    Args:
        config: Tool/resource profile.
        source: Protein FASTA.
        output: Owned job directory.
        parameters: Optional subcluster_id, reference_id and explicit sample_size.
        membership: Optional audited source subcluster memberships.
        metadata: Reviewed taxonomic traits for tree tips.

    Returns:
        Input/selection audit, alignment, column/member statistics and optional inferred tree.

    Raises:
        ResearchError: If the complete selection is oversized or an inferred tree changes tip IDs.
    """
    connection, total = index_fasta(
        source=source, destination=output / "input.sqlite", maximum=config.max_sequences
    )
    try:
        connection.execute("CREATE TABLE selected(id TEXT PRIMARY KEY)")
        if parameters.get("subcluster_id"):
            if membership is None:
                raise ResearchError("A subcluster selection requires its audited membership table")
            with membership.open(encoding="utf-8") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    if row["subcluster_id"] == parameters["subcluster_id"]:
                        connection.execute("INSERT INTO selected VALUES (?)", (row["sequence_id"],))
        else:
            connection.execute("INSERT INTO selected SELECT id FROM sequences")
        selected_count = connection.execute("SELECT count(*) FROM selected").fetchone()[0]
        if not selected_count:
            raise ResearchError("No proteins belong to the requested alignment selection")
        sample_size = bounded_number(
            value=parameters.get("sample_size", selected_count),
            label="Alignment size",
            minimum=1,
            maximum=config.max_alignment_sequences,
            integer=True,
        )
        if sample_size < selected_count and not parameters.get("allow_sampling", False):
            raise ResearchError(
                "Enable explicit deterministic sampling or align the complete selection"
            )
        reference = str(
            parameters.get("reference_id")
            or connection.execute(
                "SELECT id FROM sequences JOIN selected USING(id) ORDER BY id LIMIT 1"
            ).fetchone()[0]
        )
        if connection.execute("SELECT 1 FROM selected WHERE id=?", (reference,)).fetchone() is None:
            raise ResearchError("Reference protein is outside the alignment selection")
        selected = connection.execute(
            "SELECT id,sequence FROM sequences JOIN selected USING(id) "
            "ORDER BY CASE WHEN id=? THEN 0 ELSE 1 END,hash,id LIMIT ?",
            (reference, sample_size),
        ).fetchall()
    finally:
        connection.close()
    sequences = output / "sequences.fasta"
    with sequences.open(mode="w", encoding="utf-8") as handle:
        handle.writelines(f">{identifier}\n{sequence}\n" for identifier, sequence in selected)
    if max(len(sequence) for _, sequence in selected) * len(selected) > config.max_alignment_cells:
        raise ResearchError("Requested alignment exceeds the configured matrix size bound")
    run_command(
        arguments=[config.mafft, "--version"],
        output=output,
        config=config,
        stdout=output / "mafft_version.txt",
    )
    if len(selected) == 1:
        shutil.copyfile(sequences, output / "alignment.fasta")
    else:
        run_command(
            arguments=[
                config.mafft,
                "--thread",
                str(config.threads),
                "--amino",
                "--auto",
                str(sequences),
            ],
            output=output,
            config=config,
            stdout=output / "alignment.fasta",
        )
    result = alignment_statistics(
        alignment=output / "alignment.fasta",
        reference_id=reference,
        maximum_cells=config.max_alignment_cells,
        output=output,
    )
    aligned = dict(iter_fasta(path=output / "alignment.fasta", aligned=True))
    aligned_ids = set(aligned)
    if aligned_ids != {identifier for identifier, _ in selected}:
        raise ResearchError("Alignment tool changed the selected sequence identifiers")
    if any(aligned[identifier].replace("-", "") != sequence for identifier, sequence in selected):
        raise ResearchError("Alignment tool changed a selected protein sequence")
    if len(selected) >= 3 and bool(parameters.get("infer_tree", True)):
        run_command(
            arguments=[config.fasttree, "-wag", "-gamma", str(output / "alignment.fasta")],
            output=output,
            config=config,
            stdout=output / "tree.nwk",
        )
        newick = (output / "tree.nwk").read_text(encoding="utf-8")
        tree_ids = {tip.name for tip in Phylo.read(io.StringIO(newick), "newick").get_terminals()}
        if tree_ids != aligned_ids:
            raise ResearchError("Inferred tree tip names differ from the aligned proteins")
        dataset = auspice_dataset(
            newick=newick, metadata=metadata or {}, title="Protein family phylogeny"
        )
        atomic_json(path=output / "auspice.json", value=dataset)
        result.update({"tree.nwk": output / "tree.nwk", "auspice.json": output / "auspice.json"})
    write_tsv(
        path=output / "selection.tsv",
        rows=[
            {
                "input_count": total,
                "selected_family_count": selected_count,
                "aligned_count": len(selected),
                "sampling": (
                    "SHA256_ID_ORDER_WITH_REFERENCE"
                    if len(selected) < selected_count
                    else "ALL_SELECTED"
                ),
                "reference_id": reference,
                "subcluster_id": parameters.get("subcluster_id", ""),
            }
        ],
        columns=(
            "input_count",
            "selected_family_count",
            "aligned_count",
            "sampling",
            "reference_id",
            "subcluster_id",
        ),
    )
    result.update(
        {
            name: output / name
            for name in ("sequences.fasta", "alignment.fasta", "selection.tsv", "mafft_version.txt")
        }
    )
    return result
