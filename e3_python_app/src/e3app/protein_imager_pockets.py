"""Export recorded pockets in their original coordinate frame for manual inspection."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import StringIO
import json
import math
import re
from typing import Mapping, Sequence

from Bio.PDB import MMCIFIO
from Bio.PDB.MMCIF2Dict import MMCIF2Dict
import pandas as pd

from e3app.alphafold_hog_bundle import MAX_BUNDLE_BYTES, MAX_MODEL_BYTES
from e3app.errors import AppError
from e3app.external_actions import normalise_uniprot_accession
from e3app.pocket_review import PocketReviewBundle, read_review_html, selected_group_row


@dataclass(frozen=True)
class PocketSource:
    """One indexed report's original pocket evidence and source checksum."""

    group_id: str
    document_sha256: str
    proteins: tuple[dict, ...]


@dataclass(frozen=True)
class PocketUploadFile:
    """A complete original structure or one pocket, in the same native coordinates."""

    accession: str
    selection_rank: int
    pocket_number: int
    filename: str
    data: bytes
    representation: str


@dataclass(frozen=True)
class PocketExport:
    """Pocket upload files, scientific evidence tables and per-protein status."""

    files: tuple[PocketUploadFile, ...]
    audit: tuple[dict, ...]
    tables: Mapping[str, bytes]


def load_pocket_source(*, bundle: PocketReviewBundle, group_page: str) -> PocketSource | None:
    """Read the indexed group's embedded original coordinates without reconstructing predictions.

    Args:
        bundle: Validated portable pocket review.
        group_page: Indexed group page chosen in the app.

    Returns:
        Original recorded evidence, or None for a legacy page without embedded data.

    Raises:
        AppError: If embedded data disagree with the index or are malformed.
    """
    row = selected_group_row(bundle, group_page)
    document = read_review_html(bundle, group_page)
    matches = re.findall(
        r'<script\b[^>]*\bid=["\']reviewData["\'][^>]*>(.*?)</script>',
        document, flags=re.DOTALL | re.IGNORECASE,
    )
    if not matches:
        return None
    try:
        if len(matches) != 1:
            raise ValueError("Expected one reviewData record")
        payload = json.loads(matches[0])
        key = payload["group_key"]
        for field, expected in (
            ("primary_group_id", row["primary_group_id"]),
            ("primary_group_type", row["primary_group_type"]),
            ("cluster_id", row["lead_cluster_id"]),
        ):
            if key[field] != str(expected):
                raise ValueError(f"Indexed {field} differs from the embedded group")
        if payload["review_rank"] != int(row["review_rank"]):
            raise ValueError("Indexed rank differs from the embedded group")
        proteins = payload["proteins"]
        if not isinstance(proteins, list) or not all(isinstance(p, dict) for p in proteins):
            raise ValueError("Protein evidence must be a list of records")
        accessions = [p["accession"] for p in proteins]
        if len(set(accessions)) != len(accessions):
            raise ValueError("Duplicate protein evidence")
    except (ValueError, TypeError, KeyError) as exc:
        raise AppError(f"Invalid recorded Protein Imager pocket data: {exc}") from exc
    return PocketSource(
        group_id=str(row["primary_group_id"]),
        document_sha256=sha256(document.encode("utf-8")).hexdigest(),
        proteins=tuple(proteins),
    )


def _locator(atom: Mapping) -> tuple[str, str]:
    """Return the exact label-first locator used by the portable report generator."""
    chain, residue = str(atom["chain"]), str(atom["resi"])
    if not chain or not residue or chain in {"?", "."} or residue in {"?", "."}:
        raise ValueError("A reported atom has no unambiguous chain/residue locator")
    return chain, residue


def _positive_integer(value: object) -> int:
    """Validate pocket numbers and selection ranks without truncation."""
    text = str(value)
    if not text.isdigit() or int(text) < 1:
        raise ValueError("Pocket numbers and ranks must be positive integers")
    return int(text)


def _trace_dictionary(*, atoms: Sequence[dict]) -> dict:
    """Construct an explicitly C-alpha-only mmCIF while retaining original residue labels."""
    fields = (
        "group_PDB", "id", "type_symbol", "label_atom_id", "label_alt_id", "label_comp_id",
        "label_asym_id", "label_entity_id", "label_seq_id", "pdbx_PDB_ins_code", "Cartn_x",
        "Cartn_y", "Cartn_z", "occupancy", "B_iso_or_equiv", "auth_seq_id", "auth_asym_id",
        "auth_comp_id", "auth_atom_id", "pdbx_PDB_model_num",
    )
    result = {"data_": "recorded_CA_trace"}
    for field in fields:
        result[f"_atom_site.{field}"] = []
    for index, atom in enumerate(atoms, start=1):
        chain, residue = _locator(atom)
        coordinates = [float(atom[axis]) for axis in ("x", "y", "z")]
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError("Non-finite recorded atom coordinates")
        resn = str(atom["resn"])
        if not resn or not residue.lstrip("-").isdigit():
            raise ValueError("Unsupported recorded residue name or number")
        values = (
            "ATOM", str(index), "C", "CA", ".", resn, chain, "1", residue, "?",
            *(f"{value:.4f}" for value in coordinates), "1.00", "0.00", residue, chain,
            resn, "CA", "1",
        )
        for field, value in zip(fields, values, strict=True):
            result[f"_atom_site.{field}"].append(value)
    return result


def _cif_dictionary(*, payload: bytes) -> dict:
    """Parse one bounded, exact original mmCIF and reject ambiguous atom-site columns."""
    if len(payload) > MAX_MODEL_BYTES:
        raise ValueError("Original model exceeds the 100 MiB limit")
    parsed = MMCIF2Dict(StringIO(payload.decode("utf-8")))
    required = (
        "id", "group_PDB", "label_atom_id", "label_comp_id", "label_asym_id", "label_seq_id",
        "Cartn_x", "Cartn_y", "Cartn_z",
    )
    lengths = {len(parsed[f"_atom_site.{field}"]) for field in required}
    if len(lengths) != 1 or not next(iter(lengths)):
        raise ValueError("Original model has inconsistent or empty atom-site columns")
    length = next(iter(lengths))
    atom_fields = {key: value for key, value in parsed.items() if key.startswith("_atom_site.")}
    if any(not isinstance(value, list) or len(value) != length for value in atom_fields.values()):
        raise ValueError("Original model has inconsistent atom-site columns")
    return {"data_": "original_prediction_atoms", **atom_fields}


def _cif_locator(*, data: Mapping, index: int) -> tuple[str, str]:
    """Use label identifiers with the same author fallback as the report generator."""
    values = []
    for label, author in (("label_asym_id", "auth_asym_id"), ("label_seq_id", "auth_seq_id")):
        value = data[f"_atom_site.{label}"][index]
        if value in {"", ".", "?"}:
            value = data.get(f"_atom_site.{author}", [""] * len(data["_atom_site.id"]))[index]
        values.append(str(value))
    return values[0], values[1]


def _verify_trace(*, data: Mapping, atoms: Sequence[dict]) -> None:
    """Require every reported C-alpha locator, identity and native coordinate to match."""
    observed = {}
    for index, name in enumerate(data["_atom_site.label_atom_id"]):
        if name != "CA" or data["_atom_site.group_PDB"][index] != "ATOM":
            continue
        locator = _cif_locator(data=data, index=index)
        if locator in observed:
            raise ValueError("Ambiguous original C-alpha locator")
        observed[locator] = index
    if set(observed) != {_locator(atom) for atom in atoms}:
        raise ValueError("Original model and report C-alpha locators differ")
    for atom in atoms:
        index = observed[_locator(atom)]
        if data["_atom_site.label_comp_id"][index] != atom["resn"]:
            raise ValueError("Original model and report residue identities differ")
        for axis in ("x", "y", "z"):
            value = float(data[f"_atom_site.Cartn_{axis}"][index])
            if not math.isfinite(value) or abs(value - float(atom[axis])) > 0.00011:
                raise ValueError("Original model and report coordinates differ")


def _cif_bytes(*, data: dict, indices: Sequence[int] | None = None) -> bytes:
    """Write a valid mmCIF subset without changing native coordinates or residue numbering."""
    selected = data if indices is None else {
        key: [value[index] for index in indices] if key.startswith("_atom_site.") else value
        for key, value in data.items()
    }
    writer = MMCIFIO()
    writer.set_dict(selected)
    output = StringIO()
    writer.save(output)
    return output.getvalue().encode("utf-8")


def _tsv_bytes(*, rows: Sequence[dict]) -> bytes:
    """Serialise exact evidence records as tab-delimited supplementary data."""
    return pd.DataFrame(rows).to_csv(sep="\t", index=False, lineterminator="\n").encode("utf-8")


def export_recorded_pockets(
    *, source: PocketSource, accessions: Sequence[str], models: Sequence[bytes] = (),
) -> PocketExport:
    """Export original pocket geometry and scores, using full atoms only with an exact checksum.

    Args:
        source: Original evidence from one indexed report group.
        accessions: Explicitly selected canonical accessions.
        models: Current downloads or user-supplied original mmCIF bytes. Only a
            model with the exact recorded SHA-256 is eligible for atomistic export.

    Returns:
        Full-model/pocket mmCIF files and TSV evidence. If the original full
        structure is absent, clearly labelled C-alpha-only geometry is exported.

    Raises:
        AppError: If evidence, residue membership or original-model matching is invalid.
    """
    if sum(len(model) for model in models) > MAX_BUNDLE_BYTES:
        raise AppError("Original model inputs exceed the 512 MiB limit")
    by_hash = {sha256(model).hexdigest(): model for model in models}
    proteins = {str(protein["accession"]): protein for protein in source.proteins}
    files, audit, scores, residues = [], [], [], []
    output_bytes = 0
    try:
        for accession in accessions:
            if normalise_uniprot_accession(value=accession) != accession:
                raise ValueError("Pocket export requires exact canonical accessions")
            protein = proteins.get(accession)
            record = {
                "accession": accession, "group_id": source.group_id,
                "report_sha256": source.document_sha256, "model_sha256": "",
                "representation": "not_recorded", "recorded_pockets": 0, "exported_pockets": 0,
            }
            audit.append(record)
            if protein is None:
                continue
            expected_hash = str(protein.get("model_sha256", ""))
            record["model_sha256"] = expected_hash
            pockets = protein["pockets"]
            record["recorded_pockets"] = len(pockets)
            pocket_keys = [
                (_positive_integer(p["selection_rank"]), _positive_integer(p["pocket_number"]))
                for p in pockets
            ]
            if len({rank for rank, _ in pocket_keys}) != len(pocket_keys) or len({
                number for _, number in pocket_keys
            }) != len(pocket_keys):
                raise ValueError("Duplicate pocket rank or number")
            scores.extend({"accession": accession, "group_id": source.group_id, **p}
                          for p in pockets)
            atoms = protein["atoms"]
            if not atoms:
                record["representation"] = "no_recorded_coordinates"
                continue
            if len({_locator(atom) for atom in atoms}) != len(atoms):
                raise ValueError("Duplicate reported C-alpha locator")
            data = _trace_dictionary(atoms=atoms)
            representation = "CA_trace_only"
            if expected_hash in by_hash:
                data = _cif_dictionary(payload=by_hash[expected_hash])
                _verify_trace(data=data, atoms=atoms)
                representation = "original_model_checksum_verified"
            record["representation"] = representation
            prefix = f"{accession}_{'CA_only' if representation == 'CA_trace_only' else 'original'}"
            files.append(PocketUploadFile(
                accession=accession, selection_rank=0, pocket_number=0,
                filename=f"{prefix}_protein.cif", data=_cif_bytes(data=data),
                representation=representation,
            ))
            output_bytes += len(files[-1].data)
            if output_bytes > MAX_BUNDLE_BYTES:
                raise AppError("Pocket upload files exceed the 512 MiB limit")
            members: dict[tuple[int, int], set[tuple[str, str]]] = {
                key: set() for key in pocket_keys
            }
            for atom in atoms:
                for annotation in atom["pockets"]:
                    key = (annotation["selection_rank"], annotation["pocket_number"])
                    if key not in members:
                        raise ValueError("Atom refers to a pocket absent from recorded evidence")
                    members[key].add(_locator(atom))
                    residues.append({
                        "accession": accession, "group_id": source.group_id,
                        **annotation, "chain": atom["chain"], "residue_id": atom["resi"],
                        "residue_name": atom["resn"], "recorded_plddt": atom.get("plddt"),
                        **{axis: atom[axis] for axis in ("x", "y", "z")},
                    })
            for (rank, number), locators in members.items():
                if not locators:
                    continue
                indices = [index for index, group in enumerate(data["_atom_site.group_PDB"])
                           if group == "ATOM" and _cif_locator(data=data, index=index) in locators]
                files.append(PocketUploadFile(
                    accession=accession, selection_rank=rank, pocket_number=number,
                    filename=f"{prefix}_rank{rank}_pocket{number}.cif",
                    data=_cif_bytes(data=data, indices=indices), representation=representation,
                ))
                output_bytes += len(files[-1].data)
                if output_bytes > MAX_BUNDLE_BYTES:
                    raise AppError("Pocket upload files exceed the 512 MiB limit")
                record["exported_pockets"] += 1
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError) as exc:
        raise AppError(f"Could not export recorded Protein Imager pockets: {exc}") from exc
    file_audit = [{
        "accession": file.accession, "selection_rank": file.selection_rank,
        "pocket_number": file.pocket_number, "upload_file": f"pockets/{file.filename}",
        "representation": file.representation, "sha256": sha256(file.data).hexdigest(),
        "size_bytes": len(file.data),
    } for file in files]
    tables = {f"{name}.tsv": _tsv_bytes(rows=rows) for name, rows in (
        ("pocket_status", audit), ("pocket_scores", scores), ("pocket_residues", residues),
        ("pocket_files", file_audit),
    )}
    return PocketExport(files=tuple(files), audit=tuple(audit), tables=tables)
