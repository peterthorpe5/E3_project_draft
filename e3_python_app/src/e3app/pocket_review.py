"""Validation and loading for portable structure/alignment review bundles."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

import pandas as pd

from e3app.errors import AppError
from e3app.exports import dataframe_to_fasta_bytes

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from e3app.config import AppConfig

ReviewFocus = Literal["structure", "alignment"]
MAX_HTML_BYTES = 100 * 1024 * 1024

INDEX_COLUMNS = (
    "review_rank",
    "primary_group_type",
    "primary_group_id",
    "lead_cluster_id",
    "reference_accession",
    "protein_count",
    "alignment_sequence_count",
    "group_review_html",
)

SEQUENCE_COLUMNS = (
    "review_rank",
    "primary_group_type",
    "primary_group_id",
    "lead_cluster_id",
    "fasta_identifier",
    "candidate_accession",
    "species_column",
    "is_reference",
    "has_ranked_pocket_evidence",
    "sequence_length",
    "alignment_length",
)

MODEL_COLUMNS = (
    "review_rank",
    "primary_group_type",
    "primary_group_id",
    "lead_cluster_id",
    "candidate_accession",
    "species_column",
    "is_reference",
    "model_status",
    "ca_atom_count",
    "mapped_pocket_ca_count",
    "retained_pocket_count",
)

VIEWER_COLUMNS = (
    "review_rank",
    "primary_group_type",
    "primary_group_id",
    "lead_cluster_id",
    "reference_accession",
    "mobile_accession",
    "reference_species",
    "mobile_species",
    "alignment_tool",
    "interactive_view_html",
    "viewer_source_sha256",
)

SUPPLEMENTARY_SEQUENCE_COLUMNS = (
    "review_rank",
    "primary_group_type",
    "primary_group_id",
    "lead_cluster_id",
    "fasta_identifier",
    "candidate_accession",
    "species_column",
    "sequence_length",
    "sequence_sha256",
    "amino_acid_sequence",
    "structural_assessment_note",
)


@dataclass(frozen=True)
class PocketReviewBundle:
    """Validated portable review data available to both visualisation tabs."""

    available: bool
    path: Path | None
    reason: str
    index: pd.DataFrame
    sequences: pd.DataFrame
    models: pd.DataFrame
    structural_viewers: pd.DataFrame
    supplementary_sequences: pd.DataFrame = field(default_factory=pd.DataFrame)


def required_review_paths(review_dir: Path) -> dict[str, Path]:
    """Return required paths for one portable review bundle.

    Args:
        review_dir: Candidate bundle root.

    Returns:
        Named required paths.
    """
    root = review_dir.expanduser().resolve()
    return {
        "index": root / "index.html",
        "evidence_matrix": root / "evidence_matrix.html",
        "report_index": root / "tables" / "review_report_index.tsv",
        "sequences": root / "tables" / "prioritised_group_sequences.tsv",
        "models": root / "tables" / "protein_model_inventory.tsv",
        "manifest": root / "provenance" / "run_manifest.json",
        "groups": root / "groups",
    }


def pocket_review_available(review_dir: Path | None) -> bool:
    """Return whether every required portable-review component exists."""
    if review_dir is None or not review_dir.is_dir():
        return False
    paths = required_review_paths(review_dir)
    return paths["groups"].is_dir() and all(
        path.is_file() for name, path in paths.items() if name != "groups"
    )


def discover_pocket_review_dir(config: AppConfig) -> Path | None:
    """Resolve an explicit or uniquely discoverable review bundle.

    Args:
        config: Validated application configuration.

    Returns:
        A unique valid review directory, or ``None``.
    """
    if config.pocket_review_dir is not None:
        return config.pocket_review_dir.expanduser().resolve()
    source = config.source_path
    if source is None:
        return None
    search_root = source if config.source_mode == "run_directory" else source.parent
    if not search_root.is_dir():
        return None
    candidates = sorted(
        path.resolve()
        for path in search_root.iterdir()
        if path.is_dir()
        and path.name.lower().startswith("pocket_review")
        and pocket_review_available(path)
    )
    return candidates[0] if len(candidates) == 1 else None


def _read_tsv(path: Path, required_columns: tuple[str, ...]) -> pd.DataFrame:
    """Read a trusted TSV and require its documented columns."""
    if not path.is_file():
        raise AppError(f"Pocket-review table was not found: {path}")
    try:
        table = pd.read_csv(path, sep="\t", dtype_backend="numpy_nullable")
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise AppError(f"Could not read pocket-review table {path}: {exc}") from exc
    missing = sorted(set(required_columns).difference(table.columns))
    if missing:
        raise AppError(
            f"Pocket-review table {path.name} is missing columns: "
            f"{', '.join(missing)}"
        )
    return table


def _safe_group_page(review_dir: Path, relative_path: str) -> Path:
    """Resolve one index page while preventing path traversal."""
    text = str(relative_path).strip()
    parsed = urlparse(text)
    candidate = Path(text)
    if (
        not text
        or parsed.scheme
        or parsed.netloc
        or candidate.is_absolute()
        or ".." in candidate.parts
    ):
        raise AppError(f"Unsafe pocket-review group page: {relative_path!r}")
    root = review_dir.resolve()
    resolved = (root / candidate).resolve()
    if root != resolved and root not in resolved.parents:
        raise AppError(f"Unsafe pocket-review group page: {relative_path!r}")
    if not resolved.is_file():
        raise AppError(f"Pocket-review group page was not found: {relative_path}")
    return resolved


def load_pocket_review(review_dir: Path) -> PocketReviewBundle:
    """Load and validate one complete portable pocket-review bundle.

    Args:
        review_dir: Review bundle root.

    Returns:
        Loaded bundle.

    Raises:
        AppError: If the bundle or any indexed page is invalid.
    """
    root = review_dir.expanduser().resolve()
    if not pocket_review_available(root):
        raise AppError(f"Pocket-review bundle is incomplete: {root}")
    paths = required_review_paths(root)
    index = _read_tsv(paths["report_index"], INDEX_COLUMNS)
    sequences = _read_tsv(paths["sequences"], SEQUENCE_COLUMNS)
    models = _read_tsv(paths["models"], MODEL_COLUMNS)
    viewer_path = root / "tables" / "structural_alignment_viewers.tsv"
    structural_viewers = (
        _read_tsv(viewer_path, VIEWER_COLUMNS)
        if viewer_path.is_file()
        else pd.DataFrame(columns=VIEWER_COLUMNS)
    )
    supplementary_path = root / "tables" / "supplementary_group_sequences.tsv"
    supplementary_sequences = (
        _read_tsv(supplementary_path, SUPPLEMENTARY_SEQUENCE_COLUMNS)
        if supplementary_path.is_file()
        else pd.DataFrame(columns=SUPPLEMENTARY_SEQUENCE_COLUMNS)
    )
    if index.empty:
        raise AppError("Pocket-review index contains no group pages")
    numeric_ranks = pd.to_numeric(index["review_rank"], errors="coerce")
    if numeric_ranks.isna().any() or numeric_ranks.duplicated().any():
        raise AppError("Pocket-review ranks must be unique integers")
    if (numeric_ranks % 1 != 0).any():
        raise AppError("Pocket-review ranks must be unique integers")
    index = index.copy()
    index["review_rank"] = numeric_ranks.astype("int64")
    if index["group_review_html"].astype(str).duplicated().any():
        raise AppError("Pocket-review group pages must be unique")
    for relative in index["group_review_html"].astype(str):
        _safe_group_page(root, relative)
    for table in (sequences, models):
        ranks = pd.to_numeric(table["review_rank"], errors="coerce")
        if ranks.isna().any() or (ranks % 1 != 0).any():
            raise AppError("Pocket-review member ranks must be integers")
        table["review_rank"] = ranks.astype("int64")
    if not supplementary_sequences.empty:
        supplementary_ranks = pd.to_numeric(
            supplementary_sequences["review_rank"], errors="coerce"
        )
        if (
            supplementary_ranks.isna().any()
            or (supplementary_ranks % 1 != 0).any()
        ):
            raise AppError("Supplementary-sequence review ranks must be integers")
        supplementary_sequences["review_rank"] = supplementary_ranks.astype(
            "int64"
        )
        indexed_ranks = set(index["review_rank"].astype(int))
        unknown_ranks = sorted(
            set(supplementary_ranks.astype(int)).difference(indexed_ranks)
        )
        if unknown_ranks:
            raise AppError(
                "Supplementary sequence rows refer to absent review ranks: "
                + ", ".join(map(str, unknown_ranks))
            )
        duplicate_fields = [
            "review_rank",
            "primary_group_type",
            "primary_group_id",
            "candidate_accession",
        ]
        if supplementary_sequences.duplicated(duplicate_fields).any():
            raise AppError("Supplementary group-member sequences must be unique")
        for row in supplementary_sequences.itertuples(index=False):
            sequence = str(row.amino_acid_sequence).strip().upper()
            try:
                sequence_length = int(row.sequence_length)
                observed = hashlib.sha256(sequence.encode("ascii")).hexdigest()
            except (TypeError, ValueError, UnicodeEncodeError) as exc:
                raise AppError(
                    "Supplementary sequences must contain ASCII amino-acid "
                    f"records with integer lengths: {row.candidate_accession}"
                ) from exc
            if len(sequence) != sequence_length:
                raise AppError(
                    "Supplementary sequence length does not match for "
                    f"{row.candidate_accession}"
                )
            if observed != str(row.sequence_sha256).strip().lower():
                raise AppError(
                    "Supplementary sequence checksum does not match for "
                    f"{row.candidate_accession}"
                )
    if not structural_viewers.empty:
        viewer_ranks = pd.to_numeric(
            structural_viewers["review_rank"], errors="coerce"
        )
        if viewer_ranks.isna().any() or (viewer_ranks % 1 != 0).any():
            raise AppError("Structural-viewer review ranks must be integers")
        structural_viewers["review_rank"] = viewer_ranks.astype("int64")
        indexed_ranks = set(index["review_rank"].astype(int))
        unknown_ranks = sorted(
            set(viewer_ranks.astype(int)).difference(indexed_ranks)
        )
        if unknown_ranks:
            raise AppError(
                "Structural-viewer rows refer to absent review ranks: "
                + ", ".join(map(str, unknown_ranks))
            )
        if (
            structural_viewers["interactive_view_html"]
            .astype(str)
            .duplicated()
            .any()
        ):
            raise AppError("Structural-viewer pages must be unique")
        for row in structural_viewers.itertuples(index=False):
            page = _safe_group_page(root, str(row.interactive_view_html))
            try:
                digest = hashlib.sha256(page.read_bytes()).hexdigest()
            except OSError as exc:
                raise AppError(
                    f"Could not checksum structural-viewer page {page}: {exc}"
                ) from exc
            if digest != str(row.viewer_source_sha256).strip().lower():
                raise AppError(
                    "Structural-viewer checksum does not match its bundle index: "
                    f"{row.interactive_view_html}"
                )
    return PocketReviewBundle(
        available=True,
        path=root,
        reason="",
        index=index.sort_values("review_rank").reset_index(drop=True),
        sequences=sequences,
        models=models,
        structural_viewers=structural_viewers,
        supplementary_sequences=supplementary_sequences,
    )


def prepare_pocket_review(config: AppConfig) -> PocketReviewBundle:
    """Prepare optional review data without preventing core app use.

    Args:
        config: Validated application configuration.

    Returns:
        Available review data or an unavailable record explaining why.
    """
    review_dir = discover_pocket_review_dir(config)
    if review_dir is None:
        return PocketReviewBundle(
            available=False,
            path=None,
            reason=(
                "No unique pocket-review bundle was found. Start the app with "
                "--pocket-review-dir /path/to/pocket_review."
            ),
            index=pd.DataFrame(),
            sequences=pd.DataFrame(),
            models=pd.DataFrame(),
            structural_viewers=pd.DataFrame(),
        )
    try:
        return load_pocket_review(review_dir)
    except AppError as exc:
        return PocketReviewBundle(
            available=False,
            path=review_dir,
            reason=str(exc),
            index=pd.DataFrame(),
            sequences=pd.DataFrame(),
            models=pd.DataFrame(),
            structural_viewers=pd.DataFrame(),
        )


def prepare_human_plant_review(config: AppConfig) -> PocketReviewBundle:
    """Prepare the optional human-and-plant structural review bundle."""
    review_dir = config.human_plant_review_dir
    if review_dir is None:
        return PocketReviewBundle(
            available=False,
            path=None,
            reason=(
                "No human-and-plant review bundle is configured. Start the app "
                "with --human-plant-review-dir /path/to/pocket_review."
            ),
            index=pd.DataFrame(),
            sequences=pd.DataFrame(),
            models=pd.DataFrame(),
            structural_viewers=pd.DataFrame(),
        )
    try:
        return load_pocket_review(review_dir)
    except AppError as exc:
        return PocketReviewBundle(
            available=False,
            path=review_dir,
            reason=str(exc),
            index=pd.DataFrame(),
            sequences=pd.DataFrame(),
            models=pd.DataFrame(),
            structural_viewers=pd.DataFrame(),
        )


def structural_viewers_available(bundle: PocketReviewBundle) -> bool:
    """Return whether a review bundle contains validated pair viewers."""
    return bundle.available and not bundle.structural_viewers.empty


def selected_structural_viewers(
    *, bundle: PocketReviewBundle, review_rank: int
) -> pd.DataFrame:
    """Return all pairwise viewer records for one review-ranked group."""
    if not structural_viewers_available(bundle):
        return pd.DataFrame(columns=VIEWER_COLUMNS)
    selected = bundle.structural_viewers[
        bundle.structural_viewers["review_rank"] == int(review_rank)
    ].copy()
    return selected.reset_index(drop=True)


def structural_viewer_choice_labels(viewers: pd.DataFrame) -> dict[str, str]:
    """Map pairwise-viewer paths to explicit reference/mobile labels.

    Args:
        viewers: Validated viewer-index rows for one evolutionary group.

    Returns:
        Viewer paths mapped to labels that state both protein roles and species.

    Raises:
        AppError: If a required viewer field is absent or a path is duplicated.
    """
    missing = sorted(set(VIEWER_COLUMNS).difference(viewers.columns))
    if missing:
        raise AppError(
            "Structural-viewer rows are missing columns: " + ", ".join(missing)
        )
    labels: dict[str, str] = {}
    for row in viewers.itertuples(index=False):
        path = str(row.interactive_view_html)
        if path in labels:
            raise AppError(f"Structural-viewer page is duplicated: {path}")
        reference_species = str(row.reference_species).replace("_", " ")
        mobile_species = str(row.mobile_species).replace("_", " ")
        labels[path] = (
            f"Reference: {row.reference_accession} ({reference_species}) → "
            f"aligned member: {row.mobile_accession} ({mobile_species}) | "
            f"{row.alignment_tool}"
        )
    return labels


def group_choice_labels(bundle: PocketReviewBundle) -> dict[str, str]:
    """Map group-page paths to searchable, descriptive labels."""
    if not bundle.available:
        return {}
    labels: dict[str, str] = {}
    for row in bundle.index.itertuples(index=False):
        labels[str(row.group_review_html)] = (
            f"Rank {int(row.review_rank):03d} | {row.primary_group_id} | "
            f"lead {row.lead_cluster_id} | reference {row.reference_accession}"
        )
    return labels


def selected_group_row(
    bundle: PocketReviewBundle,
    group_page: str,
) -> pd.Series:
    """Return the unique index row for a selected page."""
    if not bundle.available:
        raise AppError("Pocket-review visualisations are unavailable")
    selected = bundle.index[
        bundle.index["group_review_html"].astype(str) == str(group_page)
    ]
    if len(selected) != 1:
        raise AppError(f"Unknown pocket-review group page: {group_page}")
    return selected.iloc[0]


def selected_group_members(
    bundle: PocketReviewBundle,
    review_rank: int,
    focus: ReviewFocus,
) -> pd.DataFrame:
    """Return display-ready model or sequence rows for one group."""
    if focus not in ("structure", "alignment"):
        raise AppError("Pocket-review focus must be structure or alignment")
    source = bundle.models if focus == "structure" else bundle.sequences
    preferred = MODEL_COLUMNS if focus == "structure" else SEQUENCE_COLUMNS
    selected = source[source["review_rank"] == int(review_rank)].copy()
    return selected[[column for column in preferred if column in selected.columns]]


def selected_group_alignment_fasta_bytes(
    *, bundle: PocketReviewBundle, review_rank: int
) -> bytes:
    """Return the selected group's published MAFFT alignment as FASTA bytes.

    Args:
        bundle: Loaded portable pocket-review bundle.
        review_rank: Selected review rank.

    Returns:
        Alignment FASTA preserving the bundle's exported identifiers and gaps.

    Raises:
        AppError: If the release predates aligned-sequence columns.
    """
    if "aligned_sequence" not in bundle.sequences.columns:
        raise AppError(
            "This pocket-review bundle does not contain aligned sequences. "
            "Regenerate it with the current structural-report release."
        )
    selected = bundle.sequences[
        bundle.sequences["review_rank"] == int(review_rank)
    ].copy()
    if selected.empty:
        raise AppError("The selected group has no published alignment rows")
    try:
        return dataframe_to_fasta_bytes(
            frame=selected,
            identifier_column="fasta_identifier",
            sequence_column="aligned_sequence",
            description_columns=("species_column", "candidate_accession"),
        )
    except (TypeError, ValueError) as exc:
        raise AppError(f"Could not export selected alignment: {exc}") from exc


def selected_group_supplementary_sequences(
    *, bundle: PocketReviewBundle, review_rank: int
) -> pd.DataFrame:
    """Return exact supplementary sequences for one review-ranked group."""
    if bundle.supplementary_sequences.empty:
        return pd.DataFrame(columns=SUPPLEMENTARY_SEQUENCE_COLUMNS)
    selected = bundle.supplementary_sequences[
        bundle.supplementary_sequences["review_rank"] == int(review_rank)
    ].copy()
    return selected.reset_index(drop=True)


def selected_group_supplementary_fasta_bytes(
    *, bundle: PocketReviewBundle, review_rank: int
) -> bytes:
    """Return exact supplementary member sequences as downloadable FASTA."""
    selected = selected_group_supplementary_sequences(
        bundle=bundle,
        review_rank=review_rank,
    )
    if selected.empty:
        raise AppError("The selected group has no supplementary sequences")
    try:
        return dataframe_to_fasta_bytes(
            frame=selected,
            identifier_column="fasta_identifier",
            sequence_column="amino_acid_sequence",
            description_columns=("species_column", "candidate_accession"),
        )
    except (TypeError, ValueError) as exc:
        raise AppError(
            f"Could not export supplementary sequences: {exc}"
        ) from exc


def read_review_html(
    bundle: PocketReviewBundle,
    relative_path: str,
) -> str:
    """Read one bounded, trusted HTML document from a review bundle.

    Args:
        bundle: Validated review bundle.
        relative_path: Bundle-relative document path.

    Returns:
        UTF-8 HTML text.

    Raises:
        AppError: If the bundle, path, size or encoding is invalid.
    """
    if bundle.path is None:
        raise AppError("Pocket-review visualisations are unavailable")
    page = _safe_group_page(bundle.path, relative_path)
    if page.stat().st_size > MAX_HTML_BYTES:
        raise AppError(f"Pocket-review page exceeds the 100 MiB safety limit: {page}")
    try:
        return page.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AppError(f"Could not read pocket-review page {page}: {exc}") from exc


def repair_pocket_review_viewer_controls(document: str) -> str:
    """Upgrade the legacy structure fit control in a trusted report page.

    Older portable reports only reset the zoom when ``Fit structure`` was
    pressed. At the initial auto-fit zoom this looked inert. This compatibility
    repair gives already-generated bundles the same fit-and-centre behaviour as
    newly generated reports, adds an accessible confirmation message and adds
    the offline 3D-view and alignment PDF controls introduced in release 0.4.

    Args:
        document: Trusted self-contained pocket-review HTML.

    Returns:
        Idempotently upgraded HTML.
    """
    if not isinstance(document, str):
        raise AppError("Pocket-review HTML must be text")
    upgraded = document.replace(
        '<button id="fit" type="button">Fit structure</button>',
        '<button id="fit" type="button">Fit and centre</button>',
    )
    old_handler = (
        'document.getElementById("fit").onclick=()=>{zoom=1;draw();};'
    )
    new_handler = (
        'document.getElementById("fit").onclick=()=>{'
        'rx=-.28;ry=.45;zoom=1;draw();const status='
        'document.getElementById("viewerStatus");if(status){'
        'status.textContent="View fitted and centred.";}};'
    )
    upgraded = upgraded.replace(old_handler, new_handler)
    if 'id="fit"' in upgraded and 'id="viewerStatus"' not in upgraded:
        upgraded = upgraded.replace(
            '<p id="proteinMeta">',
            '<p id="viewerStatus" class="note" aria-live="polite"></p>'
            '<p id="proteinMeta">',
            1,
        )
    if (
        'id="viewer"' not in upgraded
        or "Pocket-annotated MAFFT sequence alignment" not in upgraded
    ):
        return add_terminal_trimming_controls(upgraded)
    fit_markup = '<button id="fit" type="button">Fit and centre</button>'
    pdf_controls = (
        '<div class="button-row pdf-download-row">'
        '<button id="downloadViewPdf" type="button">'
        'Download current view PDF</button>'
        '<button id="downloadAlignmentPdf" type="button">'
        'Download alignment PDF</button></div>'
    )
    if 'id="downloadViewPdf"' not in upgraded:
        if fit_markup not in upgraded:
            return add_terminal_trimming_controls(upgraded)
        complete_button_row = fit_markup + "</div>"
        if complete_button_row in upgraded:
            upgraded = upgraded.replace(
                complete_button_row,
                complete_button_row + pdf_controls,
                1,
            )
        else:
            upgraded = upgraded.replace(fit_markup, fit_markup + pdf_controls, 1)
    if 'data-e3-pdf-compatibility="true"' in upgraded:
        return add_terminal_trimming_controls(upgraded)
    pdf_script = _pocket_review_pdf_compatibility_script()
    script_markup = (
        '<script data-e3-pdf-compatibility="true">'
        f"{pdf_script}</script>"
    )
    if "</body>" in upgraded:
        upgraded = upgraded.replace("</body>", script_markup + "</body>", 1)
    else:
        upgraded += script_markup
    return add_terminal_trimming_controls(upgraded)


def add_terminal_trimming_controls(document: str) -> str:
    """Add bounded N/C-terminal display controls to a trusted 3D viewer.

    The compatibility layer works with both selected-group pages and pairwise
    superposition pages. Existing review bundles gain manual residue-count
    trimming immediately. Bundles regenerated with residue-level pLDDT also
    gain a terminal low-confidence suggestion, a quality profile and optional
    pLDDT trace colouring. The browser-only filter never changes source data,
    model coordinates, evidence, scores or rankings.

    Args:
        document: Trusted self-contained structure-viewer HTML.

    Returns:
        Idempotently upgraded HTML, or the unchanged document when it is not a
        recognised viewer.

    Raises:
        AppError: If the supplied document is not text or the packaged browser
            compatibility asset is unavailable.
    """
    if not isinstance(document, str):
        raise AppError("Structural viewer HTML must be text")
    marker = 'data-e3-terminal-trimming="true"'
    if marker in document:
        return document
    if 'id="viewer"' not in document and "id='viewer'" not in document:
        return document
    if 'id="alignmentData"' not in document and 'id="reviewData"' not in document:
        return document
    script_markup = (
        f'<script {marker}>{_terminal_trimming_compatibility_script()}</script>'
    )
    LOGGER.debug("Adding browser-only terminal trimming to a 3D review page")
    if "</body>" in document:
        return document.replace("</body>", script_markup + "</body>", 1)
    return document + script_markup


def merge_pair_viewer_plddt(
    *, pair_document: str, group_document: str
) -> str:
    """Merge group-report pLDDT into a copied pairwise viewer payload.

    A newly regenerated portable group report can contain residue-level pLDDT
    even when its checksum-copied pair viewer was produced by an older
    structural run. This compatibility join uses exact accession, chain and
    structure-residue labels. It changes only the in-memory/downloaded viewer
    document and never the checksum-bound source page.

    Args:
        pair_document: Trusted pairwise viewer HTML containing ``alignmentData``.
        group_document: Trusted group report HTML containing ``reviewData``.

    Returns:
        Pairwise HTML with available pLDDT values merged into atom records, or
        the unchanged pair document when compatible payloads are unavailable.

    Raises:
        AppError: If either document is not text.
    """
    if not isinstance(pair_document, str) or not isinstance(group_document, str):
        raise AppError("Pair and group structural viewer documents must be text")
    pair_match = _embedded_json_script(
        document=pair_document,
        element_id="alignmentData",
    )
    group_match = _embedded_json_script(
        document=group_document,
        element_id="reviewData",
    )
    if pair_match is None or group_match is None:
        return pair_document
    try:
        pair_payload = json.loads(pair_match.group("payload"))
        group_payload = json.loads(group_match.group("payload"))
    except (json.JSONDecodeError, TypeError) as exc:
        LOGGER.warning("Could not merge viewer pLDDT from embedded JSON: %s", exc)
        return pair_document
    if not isinstance(pair_payload, dict) or not isinstance(group_payload, dict):
        return pair_document
    metadata = pair_payload.get("metadata")
    proteins = group_payload.get("proteins")
    if not isinstance(metadata, dict) or not isinstance(proteins, list):
        return pair_document
    protein_index = {
        str(protein.get("accession")): protein
        for protein in proteins
        if isinstance(protein, dict) and protein.get("accession") is not None
    }
    merged_count = 0
    for role, metadata_key in (("reference", "reference"), ("mobile", "mobile")):
        pair_atoms = pair_payload.get(role)
        protein = protein_index.get(str(metadata.get(metadata_key)))
        if not isinstance(pair_atoms, list) or not isinstance(protein, dict):
            continue
        group_atoms = protein.get("atoms")
        if not isinstance(group_atoms, list):
            continue
        quality_by_locator = _quality_by_structure_locator(group_atoms)
        for atom in pair_atoms:
            if not isinstance(atom, dict):
                continue
            locator = (str(atom.get("chain") or ""), str(atom.get("resi") or ""))
            if locator not in quality_by_locator:
                continue
            atom["plddt"] = quality_by_locator[locator]
            merged_count += 1
    if not merged_count:
        return pair_document
    encoded = json.dumps(pair_payload, separators=(",", ":")).replace("</", "<\\/")
    LOGGER.debug("Merged local pLDDT into %d pair-viewer atoms", merged_count)
    return (
        pair_document[: pair_match.start("payload")]
        + encoded
        + pair_document[pair_match.end("payload"):]
    )


def _embedded_json_script(
    *, document: str, element_id: str
) -> re.Match[str] | None:
    """Return a bounded embedded-JSON script match.

    Args:
        document: Trusted self-contained HTML document.
        element_id: Exact script element identifier.

    Returns:
        Regex match exposing the script body as ``payload``, or ``None``.
    """
    pattern = re.compile(
        r"<script\b(?=[^>]*\bid=[\"']"
        + re.escape(element_id)
        + r"[\"'])[^>]*>(?P<payload>.*?)</script>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    return pattern.search(document)


def _quality_by_structure_locator(
    atoms: list[object],
) -> dict[tuple[str, str], float]:
    """Return unambiguous pLDDT indexed by exact structure locator.

    Args:
        atoms: Group-viewer atom records.

    Returns:
        Chain/residue labels mapped to pLDDT values in the inclusive 0-100
        range. Missing or malformed scores are ignored.
    """
    indexed: dict[tuple[str, str], float] = {}
    conflicts: set[tuple[str, str]] = set()
    for atom in atoms:
        if not isinstance(atom, dict):
            continue
        raw_score = atom.get("plddt")
        if raw_score is None or isinstance(raw_score, bool):
            continue
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if not 0.0 <= score <= 100.0:
            continue
        locator = (str(atom.get("chain") or ""), str(atom.get("resi") or ""))
        if not all(locator) or locator in conflicts:
            continue
        if locator in indexed and indexed[locator] != score:
            indexed.pop(locator)
            conflicts.add(locator)
            continue
        indexed[locator] = score
    return indexed


@lru_cache(maxsize=1)
def _pocket_review_pdf_compatibility_script() -> str:
    """Return the packaged browser-side PDF exporter for legacy reports."""
    try:
        return (
            files("e3app")
            .joinpath("resources", "pocket_review_pdf_compat.js")
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, OSError, UnicodeError) as exc:
        raise AppError(
            "The packaged pocket-review PDF compatibility asset is unavailable"
        ) from exc


@lru_cache(maxsize=1)
def _terminal_trimming_compatibility_script() -> str:
    """Return the packaged browser-side terminal display controller."""
    try:
        return (
            files("e3app")
            .joinpath("resources", "terminal_trim_compat.js")
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, OSError, UnicodeError) as exc:
        raise AppError(
            "The packaged terminal trimming compatibility asset is unavailable"
        ) from exc


def read_group_html(
    bundle: PocketReviewBundle,
    group_page: str,
    focus: ReviewFocus,
) -> str:
    """Read a self-contained group page and focus its relevant section.

    Args:
        bundle: Validated review bundle.
        group_page: Trusted relative page from the index.
        focus: Structure or alignment section.

    Returns:
        Self-contained HTML with an appended scroll helper.
    """
    if focus not in ("structure", "alignment"):
        raise AppError("Pocket-review focus must be structure or alignment")
    document = repair_pocket_review_viewer_controls(
        read_review_html(bundle, group_page)
    )
    heading = (
        "Interactive 3D pocket location"
        if focus == "structure"
        else "Pocket-annotated MAFFT sequence alignment"
    )
    safe_heading = heading.replace("\\", "\\\\").replace("'", "\\'")
    scroll_script = (
        "<script>window.addEventListener('load',()=>{"
        "const target=Array.from(document.querySelectorAll('h2')).find("
        f"node=>node.textContent.trim()==='{safe_heading}');"
        "if(target){target.scrollIntoView();}});</script>"
    )
    return f"{document}\n{scroll_script}"
