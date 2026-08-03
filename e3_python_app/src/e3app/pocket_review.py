"""Validation and loading for portable structure/alignment review bundles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

import pandas as pd

from e3app.errors import AppError

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


@dataclass(frozen=True)
class PocketReviewBundle:
    """Validated portable review data available to both visualisation tabs."""

    available: bool
    path: Path | None
    reason: str
    index: pd.DataFrame
    sequences: pd.DataFrame
    models: pd.DataFrame


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
    return PocketReviewBundle(
        available=True,
        path=root,
        reason="",
        index=index.sort_values("review_rank").reset_index(drop=True),
        sequences=sequences,
        models=models,
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
        )


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
    document = read_review_html(bundle, group_page)
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
