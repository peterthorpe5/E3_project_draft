"""Safe bulk import of pipeline runs, AlphaFold ZIPs and protein FASTA."""

from __future__ import annotations

import csv
import json
import logging
import re
import shutil
import stat
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

import duckdb
import gemmi

from . import __version__
from ._pipeline.models import Sample, Settings
from ._pipeline.structure import prepare_structure
from .core import (
    SCHEMA_VERSION,
    WorkbenchError,
    digest_file,
    inside,
    safe_id,
    utc_now,
    write_json,
)

LOGGER = logging.getLogger(__name__)
MODEL_SUFFIXES = {".pdb", ".cif", ".mmcif"}


class ReportParser(HTMLParser):
    """Extract only the pipeline's inert JSON payload; never execute uploaded HTML."""

    def __init__(self) -> None:
        """Initialise exact script selection state."""
        super().__init__(convert_charrefs=False)
        self.selected = False
        self.parts: list[str] = []
        self.count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple]) -> None:
        """Select the exact application/json data element.

        Args:
            tag: HTML tag.
            attrs: Attribute pairs.
        """
        attributes = dict(attrs)
        if tag == "script" and attributes.get("id") == "data":
            if attributes.get("type") != "application/json":
                raise WorkbenchError("Report data must be an inert JSON script")
            self.count += 1
            self.selected = True

    def handle_endtag(self, tag: str) -> None:
        """Finish reading a script.

        Args:
            tag: Closing tag.
        """
        if tag == "script":
            self.selected = False

    def handle_data(self, data: str) -> None:
        """Retain selected JSON text only.

        Args:
            data: HTML text segment.
        """
        if self.selected:
            self.parts.append(data)


def read_report(*, path: Path) -> dict:
    """Decode a bounded protein-pocket-pipeline HTML report as data.

    Args:
        path: Existing pipeline report.

    Returns:
        Embedded model, pocket and method tables.
    """
    if path.stat().st_size > 250 * 1024 * 1024:
        raise WorkbenchError("Report exceeds the 250 MiB import bound")
    parser = ReportParser()
    parser.feed(path.read_text(encoding="utf-8-sig"))
    try:
        data = json.loads("".join(parser.parts))
    except ValueError as error:
        raise WorkbenchError("No valid pipeline JSON found in the report") from error
    if parser.count != 1 or not isinstance(data, dict):
        raise WorkbenchError("Expected exactly one pipeline report data element")
    if not isinstance(data.get("samples"), list) or not isinstance(
        data.get("pockets"), list
    ):
        raise WorkbenchError("Report needs samples and pockets tables")
    return data


def read_pipeline_database(*, path: Path) -> dict:
    """Read only materialised pipeline tables with external access disabled.

    Args:
        path: Existing protein_pockets.duckdb.

    Returns:
        Report-compatible table dictionary.
    """
    result = {}
    with duckdb.connect(
        str(path), read_only=True, config={"enable_external_access": False}
    ) as db:
        tables = {
            row[0]
            for row in db.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_type = 'BASE TABLE' AND table_schema = 'main'"
            ).fetchall()
        }
        for source, target in (
            ("samples", "samples"),
            ("pockets", "pockets"),
            ("ranked_pockets", "ranked"),
            ("method_runs", "methods"),
        ):
            if source not in tables:
                raise WorkbenchError(
                    f"Pipeline database lacks materialised table {source}"
                )
            cursor = db.execute(f'SELECT * FROM "{source}"')
            names = [item[0] for item in cursor.description]
            result[target] = [dict(zip(names, row)) for row in cursor.fetchall()]
    for row in result["pockets"] + result["ranked"]:
        value = row.get("residues", row.get("residue_ids", ""))
        row["residues"] = value if isinstance(value, list) else str(value).split(";")
    result["manifest"] = {"source": "pipeline DuckDB"}
    return result


def extract_zip(*, archive: Path, destination: Path) -> list[Path]:
    """Extract bounded regular files while rejecting ZIP path and symlink attacks.

    Args:
        archive: ZIP containing run output or AlphaFold model folders.
        destination: Empty extraction directory.

    Returns:
        Extracted file paths. MSA/templates and large AF3 full-data JSON are skipped.
    """
    destination.mkdir(parents=True, exist_ok=True)
    extracted = []
    seen = set()
    with zipfile.ZipFile(archive) as handle:
        entries = handle.infolist()
        if len(entries) > 100000:
            raise WorkbenchError("ZIP exceeds 100,000 entries")
        extracted_size = 0
        for item in entries:
            relative = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "\\" in item.filename
                or re.match(r"^[A-Za-z]:", item.filename)
                or stat.S_ISLNK(mode)
            ):
                raise WorkbenchError(f"Unsafe ZIP member: {item.filename!r}")
            if item.is_dir():
                continue
            if any(
                part.lower() in {"msas", "templates", "__macosx"}
                for part in relative.parts
            ):
                continue
            if "_full_data_" in relative.name or relative.name.startswith("._"):
                continue
            if relative.suffix.lower() not in (
                MODEL_SUFFIXES
                | {
                    ".html",
                    ".json",
                    ".tsv",
                    ".duckdb",
                    ".fa",
                    ".faa",
                    ".fasta",
                    ".nwk",
                    ".newick",
                }
            ):
                continue
            extracted_size += item.file_size
            if item.file_size > 1024**3 or extracted_size > 8 * 1024**3:
                raise WorkbenchError(
                    "Selected ZIP data exceeds 1 GiB per file or 8 GiB total"
                )
            key = str(relative).casefold()
            if key in seen:
                raise WorkbenchError(f"Duplicate ZIP member: {item.filename}")
            seen.add(key)
            target = inside(root=destination, relative=str(relative))
            target.parent.mkdir(parents=True, exist_ok=True)
            with handle.open(item) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            extracted.append(target)
    return extracted


def read_fasta(*, path: Path, aligned: bool = False) -> dict[str, str]:
    """Read unique first-token protein FASTA identifiers without name guessing.

    Args:
        path: Protein FASTA file.
        aligned: Whether gap characters are permitted.

    Returns:
        Exact identifiers mapped to upper-case sequences.
    """
    records: dict[str, str] = {}
    identifier = None
    if path.stat().st_size > 50 * 1024 * 1024:
        raise WorkbenchError("FASTA exceeds the 50 MiB import bound")
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if not line[1:].strip():
                raise WorkbenchError("FASTA contains a blank identifier")
            identifier = line[1:].split()[0]
            if identifier in records:
                raise WorkbenchError(f"Duplicate FASTA identifier: {identifier}")
            records[identifier] = ""
        elif identifier is None:
            raise WorkbenchError("FASTA sequence appears before its header")
        else:
            records[identifier] += line.upper()
    alphabet = set("ACDEFGHIKLMNPQRSTVWYBXZJUO" + ("-." if aligned else ""))
    if not records or len(records) > 1000:
        raise WorkbenchError("Supply 1–1,000 protein FASTA records")
    for identifier, sequence in records.items():
        if not sequence or set(sequence) - alphabet or len(sequence) > 20000:
            raise WorkbenchError(f"Invalid or overlong protein sequence: {identifier}")
    if aligned and len({len(sequence) for sequence in records.values()}) != 1:
        raise WorkbenchError("Aligned FASTA rows must have equal lengths")
    return records


def normalise_model(
    *,
    source: Path,
    destination: Path,
    sample_id: str,
    chain: str,
    confidence: str,
) -> tuple[list[dict], dict]:
    """Use the original pipeline's preparation and residue numbering unchanged.

    Args:
        source: PDB or mmCIF input.
        destination: Prepared all-atom PDB output.
        sample_id: Validated model identifier.
        chain: Explicit author chain, or empty for a single-chain model.
        confidence: plddt or none.

    Returns:
        C-alpha coordinates with original residue labels, and model metadata.
    """
    rows, metadata = prepare_structure(
        sample=Sample(sample_id=sample_id, model_path=source, chain=chain),
        settings=Settings(confidence=confidence),
        destination=destination,
    )
    if metadata["chain_count"] != 1:
        raise WorkbenchError(
            "Import one target protein chain per model for comparisons"
        )
    structure = gemmi.read_structure(str(destination))
    coordinates = {}
    for ch in structure[0]:
        for residue in ch:
            atom = residue.find_atom("CA", "*")
            coordinates[f"{ch.name}_{residue.seqid.num}"] = list(atom.pos)
    for row in rows:
        row["xyz"] = coordinates[row["residue_key"]]
    return rows, metadata


def map_sequence(
    *,
    sequence: str,
    sequences: dict[str, str],
    explicit_id: str = "",
) -> tuple[str, str, int | None]:
    """Match by exact sequence or a unique exact fragment with an explicit ID.

    Args:
        sequence: Prepared structure sequence.
        sequences: Supplied representative proteins.
        explicit_id: Optional audited model-to-FASTA mapping.

    Returns:
        Sequence identifier, mapping status and zero-based fragment offset.
    """
    if explicit_id:
        if explicit_id not in sequences:
            raise WorkbenchError(
                f"Mapped sequence ID is absent from FASTA: {explicit_id}"
            )
        target = sequences[explicit_id]
        if sequence == target:
            return explicit_id, "exact_explicit", 0
        if sequence in target and target.find(sequence) == target.rfind(sequence):
            return explicit_id, "unique_exact_fragment_explicit", target.find(sequence)
        raise WorkbenchError(f"Structure does not match mapped sequence {explicit_id}")
    matches = [
        identifier for identifier, value in sequences.items() if value == sequence
    ]
    if len(matches) == 1:
        return matches[0], "exact_sequence", 0
    if len(matches) > 1:
        return "", "ambiguous_identical_fasta_records", None
    return "", "no_exact_fasta_match", None


def import_project(
    *,
    sources: list[Path],
    output: Path,
    title: str = "Protein pocket project",
    fasta: Path | None = None,
    mapping: Path | None = None,
    chain: str = "",
    confidence: str = "plddt",
) -> Path:
    """Build a portable resource from reports, result folders and bulk model ZIPs.

    Args:
        sources: Local report, run directory, model directory or ZIP inputs.
        output: New project directory; existing projects are never overwritten.
        title: Display title independent of organism or gene.
        fasta: Optional representative FASTA.
        mapping: Optional TSV with sample_id, sequence_id and chain/group columns.
        chain: Default target author chain.
        confidence: Interpret B fields as plddt or none.

    Returns:
        Created resource directory.
    """
    from .database import save_project

    if not sources or confidence not in {"plddt", "none"}:
        raise WorkbenchError("Supply input sources and confidence=plddt or none")
    output = output.expanduser().resolve()
    if output.exists():
        raise WorkbenchError(f"Choose a new output directory; already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="pocket-import-", dir=output.parent
    ) as temporary:
        stage = Path(temporary)
        root = stage / "project"
        root.mkdir()
        roots = []
        provenance = []
        for index, path in enumerate(sources):
            path = path.expanduser().resolve()
            if not path.exists():
                raise WorkbenchError(f"Input does not exist: {path}")
            provenance.append(
                {
                    "path": str(path),
                    "sha256": digest_file(path=path) if path.is_file() else None,
                }
            )
            if path.suffix.lower() == ".zip":
                extracted = stage / f"archive_{index}"
                extract_zip(archive=path, destination=extracted)
                roots.append(extracted)
            else:
                roots.append(path)
        files = [
            file
            for item in roots
            for file in ([item] if item.is_file() else item.rglob("*"))
            if file.is_file()
        ]
        if any(file.is_symlink() for file in files):
            raise WorkbenchError(
                "Import regular files; symbolic input files are unsupported"
            )
        native = [file for file in files if file.name == "project.json"]
        reports = [
            file
            for file in files
            if (
                file.name == "report.html"
                or (file in roots and file.suffix.lower() == ".html")
            )
            and not any(file.is_relative_to(project.parent) for project in native)
        ]
        if len(reports) > 1:
            raise WorkbenchError("Import one completed run/report per project")
        data = read_report(path=reports[0]) if reports else None
        if data is None:
            databases = [
                file
                for file in files
                if file.name == "protein_pockets.duckdb"
                and not any(file.is_relative_to(project.parent) for project in native)
            ]
            if len(databases) > 1:
                raise WorkbenchError("Import one pipeline database at a time")
            data = read_pipeline_database(path=databases[0]) if databases else None
        native_data = None
        if native:
            if len(native) != 1 or data is not None:
                raise WorkbenchError("Import one workbench project at a time")
            from .core import load_project

            native_data = load_project(root=native[0].parent)
            if len(roots) == 1 and fasta is None and mapping is None:
                root.rmdir()
                shutil.copytree(native[0].parent, root)
                # Rebuild from local assets instead of trusting uploaded SQL views.
                save_project(root=root, data=native_data)
                shutil.move(str(root), str(output))
                return output
            data = {
                "samples": native_data["models"],
                "pockets": native_data["pockets"],
                "methods": native_data["method_runs"],
                "manifest": native_data["source_manifest"],
            }
        sequences = (
            read_fasta(path=fasta)
            if fasta
            else (native_data or {}).get("sequences", {})
        )
        if not fasta:
            fasta_files = [
                file
                for file in files
                if file.suffix.lower() in {".fa", ".faa", ".fasta"}
                and not any(
                    part in {"inputs", "msas", "templates"} for part in file.parts
                )
            ]
            if len(fasta_files) == 1:
                sequences = read_fasta(path=fasta_files[0])
        map_rows = {}
        if mapping:
            with mapping.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    if not row.get("sample_id") or row["sample_id"] in map_rows:
                        raise WorkbenchError(
                            "Mapping TSV needs unique sample_id values"
                        )
                    map_rows[row["sample_id"]] = row
        structures: dict[str, Path] = {}
        for file in sorted(files):
            if file.suffix.lower() not in MODEL_SUFFIXES:
                continue
            if any(
                part in {"templates", "msas", "tool_outputs", "inputs"}
                for part in file.parts
            ):
                continue
            identifier = file.parent.name if file.name == "prepared.pdb" else file.stem
            safe_id(value=identifier)
            if identifier in structures:
                if digest_file(path=file) == digest_file(path=structures[identifier]):
                    continue
                # A completed run's prepared structure is authoritative for its pockets.
                if structures[identifier].name == "prepared.pdb":
                    continue
                if file.name != "prepared.pdb":
                    raise WorkbenchError(
                        f"Duplicate model ID: {identifier}; rename or import separately"
                    )
            structures[identifier] = file
        if data:
            models = [dict(row) for row in data["samples"]]
            known = {row["sample_id"] for row in models}
            extra = set(structures) - known
            if extra:
                LOGGER.warning(
                    "Models outside this report are excluded: %s", sorted(extra)
                )
        else:
            models = [
                {
                    "sample_id": identifier,
                    "cluster": source.parent.name,
                    "status": "pockets_not_run",
                }
                for identifier, source in structures.items()
            ]
        if not models or len(models) > 1000:
            raise WorkbenchError("Import 1–1,000 models")
        identifiers = [safe_id(value=row["sample_id"]) for row in models]
        if len({value.casefold() for value in identifiers}) != len(identifiers):
            raise WorkbenchError("Model IDs must be unique, including case")
        ranked = {
            (row["sample_id"], int(row["pocket_id"])): row
            for row in (data or {}).get("ranked", [])
        }
        pockets = []
        for original in (data or {}).get("pockets", []):
            row = dict(original)
            if row["sample_id"] not in set(identifiers):
                raise WorkbenchError("Pocket references an absent model")
            if row.get("method") == "fpocket":
                row.update(ranked.get((row["sample_id"], int(row["pocket_id"])), {}))
            if isinstance(row.get("residues"), str):
                row["residues"] = row["residues"].split(";")
            pockets.append(row)
        for model in models:
            identifier = model["sample_id"]
            mapping_row = map_rows.get(identifier, {})
            model["hog_id"] = mapping_row.get("hog_id") or model.get("hog_id", "")
            model["source_url"] = mapping_row.get("source_url") or model.get(
                "source_url", ""
            )
            model["source_accession"] = mapping_row.get(
                "source_accession"
            ) or model.get("source_accession", "")
            model["group_id"] = (
                model["hog_id"]
                or map_rows.get(identifier, {}).get("group_id")
                or model.get("cluster", "")
            )
            model.update(
                prepared_model=None,
                coordinates=None,
                sequence_id="",
                mapping_status="coordinates_missing",
            )
            source = structures.get(identifier)
            if source is None:
                continue
            LOGGER.info("Importing %s", identifier)
            relative = f"models/{identifier}/prepared.pdb"
            selected_chain = map_rows.get(identifier, {}).get("chain") or chain
            rows, metadata = normalise_model(
                source=source,
                destination=root / relative,
                sample_id=identifier,
                chain=selected_chain,
                confidence=confidence,
            )
            residue_map = source.parent / "residue_map.tsv"
            if source.name == "prepared.pdb" and residue_map.is_file():
                with residue_map.open(encoding="utf-8", newline="") as handle:
                    originals = {
                        row["residue_key"]: row
                        for row in csv.DictReader(handle, delimiter="\t")
                    }
                for row in rows:
                    original = originals.get(row["residue_key"], {})
                    for key in (
                        "author_chain",
                        "author_residue_number",
                        "insertion_code",
                    ):
                        if key in original:
                            row[key] = original[key]
            sequence = "".join(row["amino_acid"] for row in rows)
            if sequences:
                sequence_id, status, offset = map_sequence(
                    sequence=sequence,
                    sequences=sequences,
                    explicit_id=map_rows.get(identifier, {}).get("sequence_id", ""),
                )
            else:
                import hashlib

                sequence_id = (
                    "sequence_" + hashlib.sha256(sequence.encode()).hexdigest()[:12]
                )
                status, offset = "derived_from_structure", 0
            model.update(
                prepared_model=relative,
                coordinates=f"models/{identifier}/coordinates.json",
                sequence=sequence,
                sequence_id=sequence_id,
                mapping_status=status,
                confidence=confidence,
                structure_sha256=digest_file(path=source),
                residue_count=len(rows),
                mean_plddt=metadata["mean_plddt"],
                fraction_ge_threshold=metadata["fraction_ge_threshold"],
            )
            for position, row in enumerate(rows, start=1):
                row["sequence_position"] = (
                    position + offset if offset is not None else None
                )
                row["model_position"] = position
            write_json(path=root / model["coordinates"], value=rows)
        if not sequences:
            sequences = {
                row["sequence_id"]: row["sequence"]
                for row in models
                if row.get("sequence_id")
            }
        project = {
            "schema_version": SCHEMA_VERSION,
            "app_version": __version__,
            "title": title.strip() or "Protein pocket project",
            "created_utc": utc_now(),
            "models": models,
            "pockets": pockets,
            "sequences": sequences,
            "method_runs": (data or {}).get("methods", []),
            "source_manifest": (data or {}).get("manifest", {}),
            "provenance": provenance,
            "comparisons": [],
            "sequence_analyses": [],
        }
        save_project(root=root, data=project)
        shutil.move(str(root), str(output))
    LOGGER.info("Imported project %s", output)
    return output
