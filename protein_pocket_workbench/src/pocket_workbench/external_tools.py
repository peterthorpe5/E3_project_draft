"""Validated external-viewer links and exact local sequence/structure hand-offs."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
import re
import zipfile
from pathlib import Path
from urllib.parse import urlencode

import gemmi

from . import __version__
from .core import WorkbenchError, inside
from .groups import AF3_INSPECTOR_URL, inspector_bundle, source_link
from .presentation import model_labels, ranked_pockets

LOGGER = logging.getLogger(__name__)
MOLSTAR_URL = "https://molstar.org/viewer/"
ALPHAFOLD_URL = "https://alphafold.ebi.ac.uk/"
EMERALD_URL = "https://algbio.github.io/emerald-ui/"
PROTEIN_IMAGER_URL = "https://3dproteinimaging.com/protein-imager/"
MAX_MODEL_BYTES = 64 * 1024**2
MAX_BUNDLE_BYTES = 512 * 1024**2
UNIPROT_PATTERN = re.compile(
    r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})"
)
RESOURCES = (
    {
        "name": "Protein Imager",
        "url": PROTEIN_IMAGER_URL,
        "purpose": "Inspect molecular structures and prepare illustrations.",
        "preparation": (
            "Download a saved PDB/mmCIF and load it manually. Use its pocket residue"
            " TSV for exact prepared-chain selections. This link opens the start page."
        ),
    },
    {
        "name": "Mol* Viewer",
        "url": MOLSTAR_URL,
        "purpose": "Inspect atomic structures, residues and model confidence.",
        "preparation": (
            "A populated accession link loads a public AlphaFold Database model. To"
            " inspect the project's actual de novo model, download its coordinate"
            " file and load that file manually instead."
        ),
    },
    {
        "name": "AlphaFold Database",
        "url": ALPHAFOLD_URL,
        "purpose": (
            "Open a supplied canonical UniProt accession in the public database."
        ),
        "preparation": (
            "Database records are separate from the project's saved models and may"
            " differ in sequence coverage, release, conformation or residue numbering."
        ),
    },
    {
        "name": "EMERALD",
        "url": EMERALD_URL,
        "purpose": "Explore pairwise protein alignments and alignment-safe windows.",
        "preparation": (
            "Populated links require two distinct canonical UniProt accessions. For"
            " local or RefSeq identifiers, download the exact two-record FASTA and"
            " load it manually. Alignment-safe windows are not disorder predictions."
        ),
    },
    {
        "name": "AlphaFold 3 Multi-Model Inspector",
        "url": AF3_INSPECTOR_URL,
        "purpose": "Inspect several selected local structures in an external viewer.",
        "preparation": (
            "Prepare and download the local-model ZIP, then upload it manually. Model"
            " indices map to project IDs in manifest.tsv. Missing AF3-specific metrics"
            " remain unknown; this export does not supply PAE."
        ),
    },
)
POCKET_COLUMNS = (
    "sample_id",
    "method",
    "pocket_id",
    "review_rank",
    "rank",
    "ranking_basis",
    "confidence_status",
    "mean_plddt",
    "druggability_score",
    "p2rank_rescore_score",
    "probability",
    "volume_a3",
    "quality_screen_pass",
    "near_cut_boundary",
    "near_very_low_confidence",
)
RESIDUE_COLUMNS = (
    "sample_id",
    "method",
    "pocket_id",
    "review_rank",
    "rank",
    "residue_key",
    "mapping_status",
    "tool_chain",
    "tool_residue_number",
    "author_chain",
    "author_residue_number",
    "insertion_code",
    "sequence_id",
    "sequence_position",
    "model_position",
    "amino_acid",
    "plddt",
    "quality_screen_pass",
    "near_cut_boundary",
    "near_very_low_confidence",
)


def canonical_uniprot(*, value: object) -> str | None:
    """Validate an entire canonical accession without guessing an ID from a name.

    Args:
        value: Explicit source accession or exact stored sequence/model identifier.

    Returns:
        Upper-case canonical accession, or None for RefSeq, isoforms or other IDs.
    """
    if not isinstance(value, str):
        return None
    accession = value.strip().upper()
    return accession if UNIPROT_PATTERN.fullmatch(accession) else None


def public_model_links(*, accession: object) -> dict[str, str | None]:
    """Build supported database links without contacting the destination services.

    Args:
        accession: An explicit canonical UniProt accession.

    Returns:
        AlphaFold and Mol* URLs, or None values for an unsupported identifier.
    """
    canonical = canonical_uniprot(value=accession)
    return {
        "alphafold": f"{ALPHAFOLD_URL}entry/{canonical}" if canonical else None,
        "molstar": (
            MOLSTAR_URL + "?" + urlencode({"afdb": canonical}) if canonical else None
        ),
    }


def emerald_pair_url(
    *, first: object, second: object, alpha: float = 0.75, delta: int = 8
) -> str | None:
    """Prepare the documented two-UniProt EMERALD URL in the chosen role order.

    Args:
        first: First canonical UniProt accession.
        second: Second canonical UniProt accession.
        alpha: Finite safety-window parameter in [0, 1].
        delta: Integer suboptimality parameter in [0, 100].

    Returns:
        Populated URL, or None if either ID is unsupported or both IDs are equal.

    Raises:
        WorkbenchError: An analysis parameter is invalid.
    """
    if (
        isinstance(alpha, bool)
        or not isinstance(alpha, (int, float))
        or not math.isfinite(alpha)
        or not 0 <= alpha <= 1
    ):
        raise WorkbenchError("EMERALD alpha must be a finite number between 0 and 1")
    if isinstance(delta, bool) or not isinstance(delta, int) or not 0 <= delta <= 100:
        raise WorkbenchError("EMERALD delta must be an integer between 0 and 100")
    a, b = canonical_uniprot(value=first), canonical_uniprot(value=second)
    if a is None or b is None or a == b:
        return None
    return (
        EMERALD_URL
        + "?"
        + urlencode({"seqA": a, "seqB": b, "alpha": f"{alpha:g}", "delta": delta})
    )


def external_records(*, data: dict, group: str | None = None) -> list[dict]:
    """Inventory exact selectable model records and otherwise unrepresented FASTA.

    Args:
        data: Loaded native project.
        group: Explicit HOG/group ID; None includes every model and FASTA-only row.

    Returns:
        Record metadata and saved sequences. Replicates/ranges remain distinct.
    """
    labels = model_labels(identifiers=[m["sample_id"] for m in data["models"]])
    records = []
    represented = {m.get("sequence_id") for m in data["models"]}
    for model in data["models"]:
        group_id = model.get("hog_id") or model.get("group_id") or "Ungrouped"
        if group is not None and group != group_id:
            continue
        explicit = model.get("source_accession")
        candidates = (
            [(explicit, "source_accession")]
            if isinstance(explicit, str) and explicit.strip()
            else [(model.get(k), k) for k in ("sequence_id", "sample_id")]
        )
        accession, basis = None, "unavailable"
        for value, field in candidates:
            if canonical := canonical_uniprot(value=value):
                accession, basis = canonical, field
                break
        sequence_id = model.get("sequence_id", "")
        records.append(
            {
                "record_id": "model:" + model["sample_id"],
                "kind": "model",
                "sample_id": model["sample_id"],
                "label": labels[model["sample_id"]],
                "group_id": group_id,
                "sequence_id": sequence_id,
                "input_scope": model.get("input_scope", "full_model"),
                "original_start": model.get("original_start"),
                "original_end": model.get("original_end"),
                "input_sequence": model.get("sequence"),
                "representative_sequence": data["sequences"].get(sequence_id),
                "coordinates_available": bool(model.get("prepared_model")),
                "canonical_accession": accession,
                "accession_basis": basis,
                "source_url": source_link(value=model.get("source_url", "")),
                "public_links": public_model_links(accession=accession),
            }
        )
    if group is None:
        for identifier, sequence in data["sequences"].items():
            if identifier in represented:
                continue
            accession = canonical_uniprot(value=identifier)
            records.append(
                {
                    "record_id": "sequence:" + identifier,
                    "kind": "sequence",
                    "sample_id": "",
                    "label": identifier + " · FASTA only",
                    "group_id": "",
                    "sequence_id": identifier,
                    "input_scope": "fasta_only",
                    "input_sequence": sequence,
                    "representative_sequence": sequence,
                    "coordinates_available": False,
                    "canonical_accession": accession,
                    "accession_basis": "sequence_id" if accession else "unavailable",
                    "source_url": "",
                    "public_links": public_model_links(accession=accession),
                }
            )
    return records


def record_sequence(*, record: dict, scope: str) -> tuple[str, str]:
    """Read a labelled exact sequence without substituting another model or range.

    Args:
        record: A record returned by external_records.
        scope: model_input or representative_fasta.

    Returns:
        Validated sequence and its actual source label.

    Raises:
        WorkbenchError: Requested sequence is absent, invalid or exceeds the bound.
    """
    if scope not in {"model_input", "representative_fasta"}:
        raise WorkbenchError("Choose model_input or representative_fasta")
    key = "input_sequence" if scope == "model_input" else "representative_sequence"
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WorkbenchError(f"No exact {scope} sequence for {record['record_id']}")
    sequence = re.sub(r"\s+", "", value).upper()
    if len(sequence) > 1_000_000 or re.fullmatch(r"[A-Z]+", sequence) is None:
        raise WorkbenchError(
            f"Invalid or oversized protein sequence: {record['record_id']}"
        )
    source = "fasta_only" if record["kind"] == "sequence" else scope
    return sequence, source


def fasta_record(*, record: dict, scope: str, role: str) -> str:
    """Render one safe, uniquely role-labelled FASTA record from exact saved data.

    Args:
        record: Selected local model or FASTA-only record.
        scope: Explicit sequence source.
        role: First, second or model-index label.

    Returns:
        FASTA text with 80-character sequence lines and a final newline.
    """
    sequence, source = record_sequence(record=record, scope=scope)
    header = (
        f"{role}|{record['record_id']} sequence_id={record.get('sequence_id', '')} "
        f"scope={source} input_scope={record['input_scope']}"
    )
    header = re.sub(r"[\r\n\t>]+", " ", header)
    wrapped = "\n".join(sequence[i : i + 80] for i in range(0, len(sequence), 80))
    return f">{header}\n{wrapped}\n"


def pair_fasta(*, data: dict, first: str, second: str, scope: str) -> bytes:
    """Export the chosen two records in their chosen order, retaining input scope.

    Args:
        data: Native project.
        first: Exact first record ID.
        second: Exact second record ID, different from first.
        scope: model_input or representative_fasta.

    Returns:
        UTF-8 two-record FASTA, including identical sequences for distinct models.

    Raises:
        WorkbenchError: IDs or exact sequences are unavailable.
    """
    records = {r["record_id"]: r for r in external_records(data=data)}
    if first == second or first not in records or second not in records:
        raise WorkbenchError("Choose two different available protein/model records")
    return (
        fasta_record(record=records[first], scope=scope, role="first")
        + fasta_record(record=records[second], scope=scope, role="second")
    ).encode("utf-8")


def model_file(*, root: Path, model: dict, file_format: str = "cif") -> bytes:
    """Read a complete saved prepared model, optionally converting it to mmCIF.

    Args:
        root: Native resource directory.
        model: Selected model; prepared_model must be a bounded resource path.
        file_format: pdb for the original bytes, or cif for a lossless atom export.

    Returns:
        Complete atomic coordinates with the prepared chain/residue labels retained.

    Raises:
        WorkbenchError: Missing, invalid or oversized coordinates, or invalid format.
    """
    if file_format not in {"pdb", "cif"}:
        raise WorkbenchError("Choose pdb or cif for an external model")
    if not model.get("prepared_model"):
        raise WorkbenchError("This record has no saved prepared structure")
    path = inside(root=root, relative=model["prepared_model"])
    if not path.is_file() or path.stat().st_size > MAX_MODEL_BYTES:
        raise WorkbenchError("Model coordinates are missing or exceed 64 MiB")
    try:
        structure = gemmi.read_structure(str(path))
    except (RuntimeError, ValueError) as error:
        LOGGER.warning("Cannot parse external model %s", model.get("sample_id"))
        raise WorkbenchError("Saved model coordinates cannot be parsed") from error
    if not len(structure) or not structure[0].count_atom_sites():
        raise WorkbenchError("Saved model contains no atomic coordinates")
    return (
        path.read_bytes()
        if file_format == "pdb"
        else structure.make_mmcif_document().as_string().encode("utf-8")
    )


def table_tsv(*, rows: list[dict], columns: tuple | list) -> bytes:
    """Encode explicit scalar fields as TSV, including a header for an empty table.

    Args:
        rows: Export records.
        columns: Ordered field names to retain.

    Returns:
        UTF-8 tab-separated bytes; no CSV output is created.
    """
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=list(columns),
        delimiter="\t",
        lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def pocket_tables(*, root: Path, data: dict, model_ids: list[str]) -> dict[str, list]:
    """Map selected models' pocket membership to exact prepared and author labels.

    Args:
        root: Native project directory.
        data: Saved models and pocket records.
        model_ids: Existing model identifiers to include, without rank filtering.

    Returns:
        Pocket summaries and residue-level rows, retaining unmapped entries explicitly.

    Raises:
        WorkbenchError: A requested model is absent.
    """
    models = {m["sample_id"]: m for m in data["models"]}
    if set(model_ids) - models.keys():
        raise WorkbenchError("A selected model is absent from this resource")
    lookup = {}
    for identifier in model_ids:
        path = models[identifier].get("coordinates")
        lookup[identifier] = {
            r["residue_key"]: r
            for r in (
                json.loads(inside(root=root, relative=path).read_text()) if path else []
            )
        }
    pockets = ranked_pockets(
        pockets=[p for p in data["pockets"] if p["sample_id"] in lookup]
    )
    summaries, residues = [], []
    for pocket in pockets:
        identifier = pocket["sample_id"]
        summaries.append({k: pocket.get(k) for k in POCKET_COLUMNS})
        base = {
            k: pocket.get(k)
            for k in (
                "sample_id",
                "method",
                "pocket_id",
                "review_rank",
                "rank",
                "quality_screen_pass",
                "near_cut_boundary",
                "near_very_low_confidence",
            )
        }
        for key in sorted(set(pocket.get("residues", []))):
            mapped = lookup[identifier].get(key, {})
            row = dict(
                base, **{k: mapped.get(k) for k in RESIDUE_COLUMNS if k not in base}
            )
            row.update(
                residue_key=key,
                sequence_id=models[identifier].get("sequence_id", ""),
                mapping_status="mapped" if mapped else "unmapped",
            )
            residues.append(row)
    unmapped = sum(r["mapping_status"] == "unmapped" for r in residues)
    if unmapped:
        LOGGER.warning(
            "External export retains %d unmapped pocket membership rows", unmapped
        )
    return {"pockets": summaries, "residues": residues}


def prepare_external_bundle(
    *, root: Path, data: dict, model_ids: list[str], comparison_id: str | None = None
) -> bytes:
    """Prepare audited local models, pocket labels and exact input sequences for upload.

    Args:
        root: Finished native project, read without mutation.
        data: Loaded resource.
        model_ids: One to 1,000 distinct existing model IDs.
        comparison_id: Optional complete saved fit for the selected two models.

    Returns:
        Inspector-compatible ZIP with coordinate hashes, pocket TSVs and hand-off audit.

    Raises:
        WorkbenchError: Invalid selection, mismatched fit or oversized export.
    """
    models = {m["sample_id"]: m for m in data["models"]}
    if (
        not 1 <= len(model_ids) <= 1000
        or len(set(model_ids)) != len(model_ids)
        or set(model_ids) - models.keys()
    ):
        raise WorkbenchError("Choose 1–1,000 distinct models from this resource")
    selected = [dict(models[n]) for n in model_ids]
    if not any(m.get("prepared_model") for m in selected):
        raise WorkbenchError("The selected models contain no saved atomic coordinates")
    comparison = None
    if comparison_id:
        entry = next(
            (c for c in data["comparisons"] if c["comparison_id"] == comparison_id),
            None,
        )
        if entry is None:
            raise WorkbenchError("The selected saved comparison is unavailable")
        comparison = json.loads(
            inside(root=root, relative=entry["result_path"]).read_text()
        )
        if comparison.get("status") != "complete" or set(model_ids) != {
            comparison["reference"],
            comparison["mobile"],
        }:
            raise WorkbenchError(
                "A saved alignment requires its exact two complete models"
            )
        selected = [dict(models[comparison[k]]) for k in ("reference", "mobile")]
        selected[1]["prepared_model"] = comparison["mobile_aligned"]
    tables = pocket_tables(root=root, data=data, model_ids=model_ids)
    records = {
        r["sample_id"]: r for r in external_records(data=data) if r["kind"] == "model"
    }
    fasta, sequence_audit, tool_links = [], [], []
    for index, model in enumerate(selected):
        record = records[model["sample_id"]]
        status, sequence_hash, length = "unavailable", "", None
        try:
            sequence, _ = record_sequence(record=record, scope="model_input")
            fasta.append(
                fasta_record(record=record, scope="model_input", role=f"model_{index}")
            )
            status, sequence_hash, length = (
                "included_exact_input",
                hashlib.sha256(sequence.encode()).hexdigest(),
                len(sequence),
            )
        except WorkbenchError as error:
            LOGGER.warning("No exact input FASTA in external bundle: %s", error)
        sequence_audit.append(
            dict(
                model_index=index,
                sample_id=model["sample_id"],
                sequence_id=record["sequence_id"],
                input_scope=record["input_scope"],
                original_start=record.get("original_start"),
                original_end=record.get("original_end"),
                sequence_status=status,
                sequence_length=length,
                sequence_sha256=sequence_hash,
            )
        )
        tool_links.append(
            dict(
                sample_id=model["sample_id"],
                canonical_accession=record["canonical_accession"],
                accession_basis=record["accession_basis"],
                **record["public_links"],
            )
        )
    extras = {
        "pockets.tsv": table_tsv(rows=tables["pockets"], columns=POCKET_COLUMNS),
        "pocket_residues.tsv": table_tsv(
            rows=tables["residues"], columns=RESIDUE_COLUMNS
        ),
        "model_inputs.fasta": "".join(fasta).encode("utf-8"),
        "sequence_audit.tsv": table_tsv(
            rows=sequence_audit, columns=list(sequence_audit[0])
        ),
        "public_links.tsv": table_tsv(rows=tool_links, columns=list(tool_links[0])),
    }
    handoff = {
        "workbench_version": __version__,
        "coordinate_frame": (
            "saved_alignment" if comparison else "original_prepared_models"
        ),
        "comparison_id": comparison_id,
        "model_ids": [m["sample_id"] for m in selected],
        "pocket_numbering": (
            "prepared tool chain/residue numbers; author labels are separate columns"
        ),
        "analysis_recomputed": False,
        "automatic_upload": False,
    }
    if comparison:
        extras["saved_comparison.json"] = json.dumps(
            comparison, indent=2, allow_nan=False
        ).encode()
        handoff.update(
            reference=comparison["reference"],
            mobile=comparison["mobile"],
            engine=comparison["engine"],
            scope=comparison.get("scope"),
        )
    instructions = (
        "EXTERNAL TOOL HAND-OFF\n\nDownload this ZIP; choose and upload files yourself"
        " in the destination viewer.\nNo structures are fetched from public databases"
        " or uploaded by this app.\nCoordinate frame:"
        f" {handoff['coordinate_frame']}\nFor a saved alignment, the reference is first"
        " and the second model already\nhas the recorded mobile transform applied. No"
        " new fitting was performed.\nOtherwise models retain their independent"
        " prepared coordinate frames.\n\nInspector: upload the ZIP. manifest.tsv maps"
        " model indices to IDs.\nProtein Imager / Mol*: load a selected"
        " workbench_model_<index>.cif manually.\npocket_residues.tsv supplies"
        " tool-chain/residue labels matching these files,\nplus original author/FASTA"
        " positions when mapped. Unmapped residues remain\nexplicit; no replacement"
        " rank or residue position is invented.\nAll pocket methods and original ranks"
        " are retained in pockets.tsv.\nmodel_inputs.fasta contains only available"
        " exact model-input sequences;\nread sequence_audit.tsv for missing inputs and"
        " retained-region coordinates.\nPublic database links open separate database"
        " models, which can differ from\nthe saved de novo structures. They do not"
        " transfer local pocket annotations.\nPAE and AF3-specific summary metrics are"
        " not supplied by this compatibility\nexport. Missing metrics are unknown."
        " Distinct group members are not\nautomatically alternative predictions of the"
        " same sequence.\n\n"
        + "\n".join(f"{r['name']}: {r['url']}" for r in RESOURCES)
        + "\n"
    )
    extras["HANDOFF.txt"] = instructions.encode("utf-8")
    stream = io.BytesIO(inspector_bundle(root=root, models=selected))
    with zipfile.ZipFile(stream, mode="a", compression=zipfile.ZIP_DEFLATED) as archive:
        if (
            sum(i.file_size for i in archive.infolist())
            + sum(map(len, extras.values()))
            > MAX_BUNDLE_BYTES
        ):
            raise WorkbenchError("Selected hand-off files exceed 512 MiB")
        hashes = {
            i.filename: hashlib.sha256(archive.read(i)).hexdigest()
            for i in archive.infolist()
        }
        for name, content in extras.items():
            archive.writestr(name, content)
            hashes[name] = hashlib.sha256(content).hexdigest()
        handoff["file_sha256"] = hashes
        archive.writestr("handoff.json", json.dumps(handoff, indent=2, allow_nan=False))
    LOGGER.info(
        "Prepared %d local models for external tools; saved alignment=%s",
        len(selected),
        comparison_id,
    )
    return stream.getvalue()


def bundle_model_file(*, bundle: bytes, sample_id: str) -> tuple[bytes, str]:
    """Extract one audited model in memory and verify its recorded content hash.

    Args:
        bundle: ZIP created by prepare_external_bundle or inspector_bundle.
        sample_id: Exact requested project model ID.

    Returns:
        Model bytes and the Inspector-compatible filename inside the bundle.

    Raises:
        WorkbenchError: Missing/invalid model, manifest, oversized entry or bad hash.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            if len(set(archive.namelist())) != len(archive.namelist()):
                raise WorkbenchError("External bundle contains duplicate filenames")
            manifest = list(
                csv.DictReader(
                    io.StringIO(archive.read("manifest.tsv").decode()), delimiter="\t"
                )
            )
            records = [r for r in manifest if r.get("sample_id") == sample_id]
            if len(records) != 1 or not records[0].get("model_index", "").isdigit():
                raise WorkbenchError(
                    "The requested model is not uniquely available in the bundle"
                )
            record = records[0]
            filename = f"workbench_model_{int(record['model_index'])}.cif"
            if archive.getinfo(filename).file_size > MAX_MODEL_BYTES:
                raise WorkbenchError("Selected model exceeds the 64 MiB download bound")
            content = archive.read(filename)
            if hashlib.sha256(content).hexdigest() != record.get("sha256"):
                raise WorkbenchError("Selected model differs from its bundle audit")
            return content, filename
    except (zipfile.BadZipFile, KeyError, UnicodeError, ValueError) as error:
        if isinstance(error, WorkbenchError):
            raise
        raise WorkbenchError(
            "External bundle model or manifest is invalid or unavailable"
        ) from error
