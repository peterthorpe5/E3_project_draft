"""Generate reproducible cluster inputs for the inherited full 1KP+ run."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

import yaml

from e3_discovery.exceptions import DataValidationError
from e3_discovery.io_utils import atomic_text_writer

_OS_PATTERN = re.compile(r"(?:^|\s)OS=(.*?)(?=\sOX=|\s[A-Z]{2}=|$)")
_OX_PATTERN = re.compile(r"(?:^|\s)OX=(\d+)")


def full_onekp_discovery_root(source_root: Path) -> Path:
    """Resolve the inherited E3 discovery directory below the source root.

    Args:
        source_root: Path to the inherited ``Erin_Butterfield_data`` directory.

    Returns:
        Resolved ``E3_discovery_engine`` input directory.
    """

    return (
        Path(source_root).expanduser().resolve()
        / "Other_things"
        / "Denbi"
        / "denbi_data"
        / "E3_discovery_engine"
    )


def locate_inherited_samples_json(
    discovery_root: Path,
    repository_root: Path,
) -> Path:
    """Locate the inherited full-run sample list with a repository fallback.

    Args:
        discovery_root: Inherited E3 discovery input directory.
        repository_root: Checked-out production repository.

    Returns:
        Existing non-empty source ``samples.json`` or the read-only recovered
        copy under ``legacy_reference``.

    Raises:
        FileNotFoundError: If neither candidate exists and is non-empty.
    """

    candidates = (
        Path(discovery_root) / "samples.json",
        Path(repository_root).expanduser().resolve()
        / "legacy_reference"
        / "samples.inherited.json",
    )
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate.resolve()
    raise FileNotFoundError(
        "Inherited samples.json was not found in either location: "
        + "; ".join(str(path) for path in candidates)
    )


def validate_full_onekp_source_inputs(
    source_root: Path,
    repository_root: Path,
) -> Dict[str, object]:
    """Validate every file required before a full 1KP+ Slurm submission.

    The check reports all missing or empty FASTA files together rather than
    stopping at the first absent input. It also permits the recovered repository
    copy of ``samples.json`` when the source-tree copy was not backed up.

    Args:
        source_root: Path to inherited ``Erin_Butterfield_data``.
        repository_root: Checked-out E3 Discovery Engine repository.

    Returns:
        Paths, ordered sample names, FASTA count and total source bytes.

    Raises:
        FileNotFoundError: If required metadata, environment or FASTA files are
            missing or empty.
        DataValidationError: If the inherited sample list is malformed.
    """

    repository = Path(repository_root).expanduser().resolve()
    discovery = full_onekp_discovery_root(source_root)
    samples_json = locate_inherited_samples_json(discovery, repository)
    seed_table = discovery / "files" / "e3_ligases.csv"
    environment = repository / "workflow" / "envs" / "production.yml"
    required = {
        "E3 seed table": seed_table,
        "production environment": environment,
    }
    problems = [
        f"{label}: {path}"
        for label, path in required.items()
        if not path.is_file() or path.stat().st_size == 0
    ]
    names = read_inherited_sample_names(samples_json)
    fasta_dir = discovery / "files" / "fasta_files"
    fasta_paths = [fasta_dir / f"{name}.fasta" for name in names]
    problems.extend(
        f"FASTA for {name}: {path}"
        for name, path in zip(names, fasta_paths)
        if not path.is_file() or path.stat().st_size == 0
    )
    if problems:
        raise FileNotFoundError(
            "Full 1KP+ source preflight failed. Missing or empty inputs:\n"
            + "\n".join(problems)
        )
    return {
        "discovery_root": str(discovery),
        "samples_json": str(samples_json),
        "seed_table": str(seed_table.resolve()),
        "environment": str(environment.resolve()),
        "fasta_dir": str(fasta_dir.resolve()),
        "sample_names": names,
        "sample_count": len(names),
        "total_fasta_bytes": sum(path.stat().st_size for path in fasta_paths),
    }


def read_inherited_sample_names(samples_json: Path) -> List[str]:
    """Read the ordered inherited sample list from ``samples.json``.

    Args:
        samples_json: JSON file containing a non-empty ``Samples`` list.

    Returns:
        Unique sample names in inherited order.

    Raises:
        FileNotFoundError: If the JSON file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
        DataValidationError: If the sample list is absent, empty, duplicated or
            contains blank values.
    """

    path = Path(samples_json)
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    values = payload.get("Samples") if isinstance(payload, dict) else None
    if not isinstance(values, list) or not values:
        raise DataValidationError(f"No non-empty Samples list in {path}")
    names = [str(value).strip() for value in values]
    if any(not value for value in names):
        raise DataValidationError(f"Blank sample name in {path}")
    if len(set(names)) != len(names):
        raise DataValidationError(f"Duplicate sample name in {path}")
    return names


def read_first_fasta_header(fasta_path: Path) -> str:
    """Read the first non-empty FASTA header from a plain-text file.

    Args:
        fasta_path: Protein FASTA file path.

    Returns:
        Header text without the leading ``>`` character.

    Raises:
        FileNotFoundError: If the FASTA file does not exist.
        DataValidationError: If the file contains no FASTA header.
    """

    path = Path(fasta_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(">"):
                header = line[1:].strip()
                if header:
                    return header
    raise DataValidationError(f"No FASTA header found in {path}")


def uniprot_header_metadata(
    sample_name: str,
    header: str,
) -> Dict[str, str]:
    """Extract species and taxonomy metadata from a UniProt-style header.

    Args:
        sample_name: Fallback sample name used when ``OS=`` is absent.
        header: FASTA header text without the leading ``>``.

    Returns:
        Mapping containing species, taxon ID and manifest parser settings.
    """

    species = str(sample_name).replace("_", " ")
    taxon_id = ""
    os_match = _OS_PATTERN.search(str(header))
    ox_match = _OX_PATTERN.search(str(header))
    if os_match:
        species = os_match.group(1).strip()
    if ox_match:
        taxon_id = ox_match.group(1)
    return {
        "species": species,
        "taxon_id": taxon_id,
        "source_database": "inherited_project_FASTA",
        "header_parser": "manifest",
        "header_parser_strict": "false",
        "empty_sequence_policy": "error",
        "maximum_skipped_empty_sequences": "0",
    }


def build_full_onekp_manifest_rows(
    sample_names: Iterable[str],
    fasta_dir: Path,
) -> List[Dict[str, str]]:
    """Build manifest rows for 14 named proteomes plus the combined 1KP file.

    Args:
        sample_names: Ordered inherited sample names.
        fasta_dir: Directory containing ``<sample>.fasta`` files.

    Returns:
        Manifest row dictionaries with cluster paths and parser settings.

    Raises:
        FileNotFoundError: If a required FASTA is missing or empty.
        DataValidationError: If a named FASTA lacks a valid header.
    """

    directory = Path(fasta_dir).resolve()
    rows: List[Dict[str, str]] = []
    for sample_name in sample_names:
        fasta_path = directory / f"{sample_name}.fasta"
        if not fasta_path.is_file() or fasta_path.stat().st_size == 0:
            raise FileNotFoundError(fasta_path)
        if sample_name == "onekp_dataset":
            metadata = {
                "species": "1KP combined transcriptome-derived protein dataset",
                "taxon_id": "",
                "source_database": "1KP inherited combined dataset",
                "header_parser": "onekp_scaffold",
                "header_parser_strict": "true",
                "empty_sequence_policy": "skip",
                "maximum_skipped_empty_sequences": "2",
            }
        else:
            metadata = uniprot_header_metadata(
                sample_name,
                read_first_fasta_header(fasta_path),
            )
        rows.append(
            {
                "sample_id": sample_name,
                "fasta_path": str(fasta_path),
                "species": metadata["species"],
                "taxon_id": metadata["taxon_id"],
                "proteome_id": "",
                "source_database": metadata["source_database"],
                "release": "not_recorded",
                "provenance_status": "source_release_to_be_confirmed",
                "header_parser": metadata["header_parser"],
                "header_parser_strict": metadata["header_parser_strict"],
                "empty_sequence_policy": metadata["empty_sequence_policy"],
                "maximum_skipped_empty_sequences": metadata[
                    "maximum_skipped_empty_sequences"
                ],
            }
        )
    return rows


def write_full_onekp_manifest(
    rows: Iterable[Mapping[str, str]],
    output_path: Path,
) -> int:
    """Write full-run manifest rows as a deterministic TSV file.

    Args:
        rows: Manifest row mappings.
        output_path: Destination TSV path.

    Returns:
        Number of manifest rows written.

    Raises:
        DataValidationError: If no rows are supplied.
        OSError: If the output cannot be written atomically.
    """

    materialised = [dict(row) for row in rows]
    if not materialised:
        raise DataValidationError("Full 1KP+ manifest cannot be empty")
    fields = [
        "sample_id",
        "fasta_path",
        "species",
        "taxon_id",
        "proteome_id",
        "source_database",
        "release",
        "provenance_status",
        "header_parser",
        "header_parser_strict",
        "empty_sequence_policy",
        "maximum_skipped_empty_sequences",
    ]
    with atomic_text_writer(output_path, newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(materialised)
    return len(materialised)


def build_full_onekp_cluster_config(
    manifest_path: Path,
    seed_table: Path,
    results_root: Path,
    environment_path: Path,
    threads: int,
    memory_limit: str,
    tmpdir: Path,
) -> Dict[str, object]:
    """Build the production YAML mapping for a Slurm 1KP+ run.

    Args:
        manifest_path: Generated full-run sample manifest.
        seed_table: Inherited E3 candidate CSV file.
        results_root: Persistent cluster output directory.
        environment_path: Pinned production Conda environment file.
        threads: DIAMOND and Snakemake thread count.
        memory_limit: DIAMOND memory limit, leaving headroom below Slurm RAM.
        tmpdir: Fast job-local temporary directory.

    Returns:
        Complete workflow configuration mapping.

    Raises:
        ValueError: If threads are not positive or memory limit is blank.
    """

    if threads < 1:
        raise ValueError("threads must be positive")
    if not str(memory_limit).strip():
        raise ValueError("memory_limit must be non-empty")
    scratch = Path(tmpdir).expanduser().resolve()
    return {
        "project": {
            "name": "e3_full_onekp_plus_cluster",
            "description": (
                "Full inherited 1KP+ E3 Discovery Engine production run on "
                "the University of Dundee Slurm cluster using tantan masking."
            ),
        },
        "inputs": {
            "samples_tsv": str(Path(manifest_path).resolve()),
            "e3_seed_table": str(Path(seed_table).resolve()),
            "e3_seed_column": "entry",
            "identifier_mode": "prefix_sample",
            "compute_input_checksums": True,
        },
        "outputs": {"root": str(Path(results_root).resolve())},
        "software": {
            "environment": str(Path(environment_path).resolve()),
        },
        "resources": {
            "threads": int(threads),
            "parquet_batch_size": 250000,
        },
        "diamond": {
            "executable": "diamond",
            "path_alias_root": str(scratch / "path_aliases"),
            "tmpdir": str(scratch / "diamond_tmp"),
            "identity_mode": "exact",
            "identity_percent": 50,
            "mutual_cover_percent": 50,
            "clustering_evalue": 0.1,
            "comp_based_stats": 0,
            "memory_limit": str(memory_limit),
            "masking": "tantan",
            "cluster_steps": [],
            "extra_args": [],
        },
        "thresholds": {
            "minimum_percent_identity": 50,
            "minimum_representative_coverage": 50,
            "minimum_member_coverage": 50,
            "minimum_bitscore": 20,
            "maximum_evalue": 1.0e-10,
        },
        "benchmarking": {"repeats": 1},
    }


def write_cluster_config(
    config: Mapping[str, object],
    output_path: Path,
) -> Path:
    """Write a cluster configuration mapping as deterministic YAML.

    Args:
        config: Complete workflow configuration mapping.
        output_path: Destination YAML path.

    Returns:
        Resolved written configuration path.

    Raises:
        DataValidationError: If the supplied mapping is empty.
        OSError: If the YAML cannot be written atomically.
    """

    if not config:
        raise DataValidationError("Cluster configuration cannot be empty")
    with atomic_text_writer(output_path, newline="\n") as handle:
        yaml.safe_dump(
            dict(config),
            handle,
            sort_keys=False,
            default_flow_style=False,
        )
    return Path(output_path).resolve()


def create_full_onekp_cluster_files(
    source_root: Path,
    repository_root: Path,
    results_root: Path,
    output_dir: Path,
    threads: int,
    memory_limit: str,
    tmpdir: Path,
) -> Dict[str, object]:
    """Create the Slurm full-run manifest and YAML configuration.

    Args:
        source_root: Cluster path to ``Erin_Butterfield_data``.
        repository_root: Checked-out E3 Discovery Engine repository.
        results_root: Persistent output directory for the full analysis.
        output_dir: Directory receiving generated manifest and YAML files.
        threads: DIAMOND and Snakemake thread count.
        memory_limit: DIAMOND memory limit below the Slurm memory request.
        tmpdir: Job-local temporary directory.

    Returns:
        Paths and sample count for the generated cluster input files.

    Raises:
        FileNotFoundError: If inherited sample, FASTA, seed or environment files
            are missing.
        DataValidationError: If inherited sample metadata is malformed.
        ValueError: If resource settings are invalid.
    """

    validation = validate_full_onekp_source_inputs(
        source_root=source_root,
        repository_root=repository_root,
    )
    seed_table = Path(str(validation["seed_table"]))
    environment = Path(str(validation["environment"]))
    fasta_dir = Path(str(validation["fasta_dir"]))
    names = [str(value) for value in validation["sample_names"]]
    rows = build_full_onekp_manifest_rows(names, fasta_dir)
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "full_onekp_plus.cluster.samples.tsv"
    config_path = destination / "full_onekp_plus.cluster.config.yaml"
    write_full_onekp_manifest(rows, manifest_path)
    config = build_full_onekp_cluster_config(
        manifest_path=manifest_path,
        seed_table=seed_table,
        results_root=results_root,
        environment_path=environment,
        threads=threads,
        memory_limit=memory_limit,
        tmpdir=tmpdir,
    )
    write_cluster_config(config, config_path)
    return {
        "sample_count": len(rows),
        "manifest_path": str(manifest_path),
        "config_path": str(config_path),
        "results_root": str(Path(results_root).resolve()),
        "tmpdir": str(Path(tmpdir).resolve()),
    }
