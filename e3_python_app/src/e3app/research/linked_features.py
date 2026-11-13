"""Link portable review models and pocket coordinates to exact protein sequences."""

from __future__ import annotations

from hashlib import md5, sha256
from html.parser import HTMLParser
import json
import logging
import math
from pathlib import Path
import re
from typing import Mapping

from Bio.SeqUtils import seq1
import duckdb
import pandas as pd

from e3app.config import AppConfig
from e3app.errors import AppError
from e3app.pocket_review import discover_pocket_review_dir, read_review_page

from .common import ResearchError, bounded_number, normalise_protein
from .feature_catalogue import recorded_feature_payload

LOGGER = logging.getLogger(__name__)
MAX_LINKED_RESIDUES = 20_000
POCKET_COLOURS = ("#ac4319", "#8161b1", "#087b83", "#ae4165", "#80600c")


class _ReviewDataParser(HTMLParser):
    """Collect the inert reviewData JSON block from a portable group page."""

    def __init__(self) -> None:
        """Start with no matching script tag or data."""
        super().__init__(convert_charrefs=False)
        self.active = False
        self.matches = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Identify the exact application/json script containing review evidence."""
        attributes = dict(attrs)
        if tag == "script" and attributes.get("id") == "reviewData":
            if attributes.get("type") == "application/json":
                self.matches += 1
                self.active = True

    def handle_endtag(self, tag: str) -> None:
        """Stop capturing at the end of the evidence block."""
        if tag == "script":
            self.active = False

    def handle_data(self, data: str) -> None:
        """Collect evidence text without loading scripts or linked resources."""
        if self.active:
            self.chunks.append(data)


def read_group_evidence(*, review_dir: Path, group_id: str) -> dict | None:
    """Load one exact HOG's inert portable review payload.

    Args:
        review_dir: Configured published review directory.
        group_id: Exact HOG or primary group identifier.

    Returns:
        Selected group payload, or None when the review does not cover the group.

    Raises:
        AppError: If the index, page, or its declared group is invalid.
    """
    index = review_dir / "tables" / "review_report_index.tsv"
    if not index.is_file():
        return None
    try:
        with duckdb.connect(config={"threads": 1}) as database:
            pages = database.execute(
                "SELECT DISTINCT group_review_html FROM read_csv(?, delim='\t', header=true, "
                "all_varchar=true) WHERE primary_group_id = ? LIMIT 2",
                [str(index), group_id],
            ).fetchall()
    except duckdb.Error as exc:
        raise AppError("Could not read the pocket review group index.") from exc
    if not pages:
        return None
    if len(pages) != 1 or not pages[0][0]:
        raise AppError("The pocket review has multiple pages for this group.")
    document = read_review_page(review_dir=review_dir, relative_path=pages[0][0])
    parser = _ReviewDataParser()
    try:
        parser.feed(document)
        parser.close()
        if parser.matches != 1 or parser.active:
            raise ValueError("Expected one complete reviewData block")
        payload = json.loads("".join(parser.chunks))
        if payload["group_key"]["primary_group_id"] != group_id:
            raise ValueError("Wrong group in the pocket review")
        if not isinstance(payload["proteins"], list) or not isinstance(payload["alignment"], dict):
            raise ValueError("Invalid portable review schema")
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise AppError("The selected pocket review page has no matching residue data.") from exc
    return payload


def _integer(*, value: object, label: str, maximum: int = MAX_LINKED_RESIDUES) -> int:
    """Validate a bounded one-based residue coordinate or ranked pocket number."""
    return int(bounded_number(value=value, label=label, minimum=1, maximum=maximum, integer=True))


def model_residues(*, atoms: list, sequence: str) -> list[dict[str, object]]:
    """Validate a single model trace against the exact ungapped sequence.

    Args:
        atoms: C-alpha records embedded in a published review or supplied by a model parser.
        sequence: Verified reference sequence on the one-based display axis.

    Returns:
        Model coordinates, observed amino acid and optional 0–100 pLDDT per mapped position.

    Raises:
        ResearchError: If model residues are ambiguous or disagree with the sequence.
    """
    if not atoms or len(atoms) > len(sequence):
        raise ResearchError("The model trace does not cover a unique chain of this sequence.")
    residues = {}
    chains = set()
    for atom in atoms:
        try:
            chain = str(atom["chain"]).strip()
            position = _integer(value=atom["resi"], label="Model residue", maximum=len(sequence))
            residue = seq1(str(atom["resn"]).strip().upper(), undef_code="?")
            xyz = [float(atom[axis]) for axis in ("x", "y", "z")]
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ResearchError("A model residue could not be mapped to the sequence.") from exc
        if (
            residue != sequence[position - 1] or position in residues
            or not all(math.isfinite(value) for value in xyz)
        ):
            raise ResearchError("Model residue identities or numbering disagree with the sequence.")
        if residue in "XBZJ?":
            raise ResearchError("Model residue identities are ambiguous on this sequence axis.")
        chains.add(chain)
        raw_confidence = atom.get("plddt")
        confidence = None
        if raw_confidence is not None:
            confidence = bounded_number(
                value=raw_confidence, label="Model pLDDT", minimum=0, maximum=100,
            )
        residues[position] = {
            "position": position, "residue": residue, "chain": chain,
            "x": xyz[0], "y": xyz[1], "z": xyz[2], "plddt": confidence,
        }
    if len(chains) != 1:
        raise ResearchError("The review model contains multiple coordinate chains.")
    return [residues[position] for position in sorted(residues)]


def _mapped_pockets(
    *, protein: Mapping[str, object], alignment: Mapping[str, object],
    residues: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Retain pocket positions verified against both the alignment and model membership."""
    by_position = {row["position"]: row for row in residues}
    atoms = {(str(atom["chain"]).strip(), int(atom["resi"])): atom for atom in protein["atoms"]}
    pockets = {}
    for annotation in alignment.get("pocket_annotations", []):
        position = _integer(value=annotation["fasta_position"], label="Pocket position")
        residue = by_position.get(position)
        if residue is None or annotation.get("fasta_residue") != residue["residue"]:
            continue
        if annotation.get("structure_insertion_code") not in (None, "", ".", "?"):
            continue
        locator = (
            annotation.get("structure_label_chain") or annotation.get("structure_auth_chain"),
            annotation.get("structure_label_seq_id") or annotation.get("structure_auth_seq_id"),
        )
        if tuple(str(value).strip() for value in locator) != (residue["chain"], str(position)):
            continue
        number = _integer(value=annotation["pocket_number"], label="Pocket number")
        rank = _integer(value=annotation["selection_rank"], label="Pocket rank")
        atom = atoms[(residue["chain"], position)]
        if not any(
            (str(item.get("pocket_number")), str(item.get("selection_rank")))
            == (str(number), str(rank)) for item in atom.get("pockets", [])
        ):
            continue
        pockets.setdefault((rank, number), set()).add(position)
    return [
        {
            "rank": rank, "number": number, "positions": sorted(positions),
            "color": POCKET_COLOURS[(rank - 1) % len(POCKET_COLOURS)],
        }
        for (rank, number), positions in sorted(pockets.items())
    ]


def linked_review_evidence(
    *, config: AppConfig, accession: str, group_id: str, species: str, sequence: str,
) -> dict[str, object] | None:
    """Select the exact published protein, then map its model and pockets.

    Args:
        config: Configured E3 resource and portable review directories.
        accession: Exact protein accession.
        group_id: Exact primary group.
        species: Exact release species label.
        sequence: Selected member sequence from the loaded E3 release.

    Returns:
        Verified sequence, model trace and pocket tracks, or None if unavailable.

    Raises:
        AppError: If a configured review is present but its evidence cannot be interpreted.
    """
    if not all((accession, group_id, species, sequence)):
        return None
    sequence = normalise_protein(sequence=sequence)
    if len(sequence) > MAX_LINKED_RESIDUES:
        raise ResearchError("This sequence exceeds the linked view's 20,000-residue limit.")
    review_dirs = (discover_pocket_review_dir(config=config), config.human_plant_review_dir)
    problem = None
    for review_dir in dict.fromkeys(path for path in review_dirs if path is not None):
        try:
            group = read_group_evidence(review_dir=review_dir, group_id=group_id)
        except AppError as exc:
            problem = exc
            LOGGER.warning("Could not read %s from %s: %s", group_id, review_dir, exc)
            continue
        if group is None:
            continue
        try:
            proteins = [
                row for row in group["proteins"]
                if (row["accession"], row["species"]) == (accession, species)
            ]
            records = [
                row for row in group["alignment"].get("records", [])
                if (row["accession"], row["species"]) == (accession, species)
            ]
            if len(proteins) != 1 or len(records) != 1 or not proteins[0].get("atoms"):
                continue
            protein, record = proteins[0], records[0]
            aligned_sequence = re.sub(r"[-.\s]", "", record["sequence"]).upper()
            if aligned_sequence != sequence:
                LOGGER.info("Review sequence differs from released member %s in %s", accession,
                            group_id)
                continue
            residues = model_residues(atoms=protein["atoms"], sequence=sequence)
            pockets = _mapped_pockets(protein=protein, alignment=record, residues=residues)
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as exc:
            problem = exc
            LOGGER.warning("Could not map %s in %s: %s", accession, review_dir, exc)
            continue
        LOGGER.info("Linked %s in %s: %d model residues, %d pockets", accession, group_id,
                    len(residues), len(pockets))
        return {
            "sequence": sequence, "model": residues, "pockets": pockets,
            "model_sha256": str(protein.get("model_sha256", "")), "model_source": review_dir.name,
        }
    if problem is not None:
        raise AppError("The selected model and pocket records could not be mapped.") from problem
    return None


def linked_domain_features(
    *, rows: pd.DataFrame, sequence: str, annotations: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Map valid recorded coordinates and retain the annotation's sequence evidence.

    Args:
        rows: Recorded hits for one exact accession, group and species.
        sequence: Exact released sequence already matched to the review model.
        annotations: Validated hits from an optional exact-sequence InterProScan job.

    Returns:
        Tracks with exact checksum matches or explicitly labelled historical coordinates.
        Conflicting digests, incompatible lengths and invalid positions are excluded.
    """
    result = [{**feature, "provenance": "sequence_verified"} for feature in annotations or ()]
    seen_intervals = {
        (feature["accession"], fragment["start"], fragment["end"])
        for feature in result for location in feature["locations"]
        for fragment in location["fragments"]
    }
    if rows.empty or not sequence:
        return result
    columns = {
        "sequence_sha256": sha256(sequence.encode("ascii")).hexdigest(),
        "sequence_md5": md5(sequence.encode("ascii"), usedforsecurity=False).hexdigest(),
    }
    matches = pd.Series(False, index=rows.index)
    mismatches = pd.Series(False, index=rows.index)
    for name, digest in columns.items():
        if name in rows:
            values = rows[name].fillna("").astype(str).str.strip().str.lower()
            matches |= values.eq(digest)
            mismatches |= values.ne("") & values.ne(digest)
    coordinates = rows[["protein_length", "location_start", "location_end"]].apply(
        pd.to_numeric, errors="coerce",
    )
    valid = (
        coordinates.protein_length.eq(len(sequence)) & coordinates.location_start.ge(1)
        & coordinates.location_start.le(coordinates.location_end)
        & coordinates.location_end.le(len(sequence))
        & coordinates.mod(1).eq(0).all(axis=1) & ~mismatches
    )
    for provenance, subset in (
        ("sequence_verified", rows.loc[valid & matches]),
        ("recorded_coordinates", rows.loc[valid & ~matches]),
    ):
        if subset.empty:
            continue
        for feature in recorded_feature_payload(rows=subset)["features"]:
            fragment = feature["locations"][0]["fragments"][0]
            key = (feature["accession"], fragment["start"], fragment["end"])
            if key in seen_intervals:
                continue
            seen_intervals.add(key)
            result.append({**feature, "provenance": provenance})
    LOGGER.info("Mapped %d recorded domain intervals to the linked view", len(result))
    return result
