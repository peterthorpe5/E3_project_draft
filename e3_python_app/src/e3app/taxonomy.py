"""Versioned and user-supplied taxonomy predicates for orthology groups."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import logging
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from e3app.errors import AppError

LOGGER = logging.getLogger(__name__)

TAXONOMY_NODE_COLUMNS = ("taxon_id", "name", "rank", "parent_taxon_id")
SPECIES_TAXONOMY_COLUMNS = (
    "canonical_species_name",
    "source_species_name",
    "taxon_id",
    "lineage_taxon_ids",
)
CUSTOM_TAXONOMY_ALIASES = {
    "canonical_species_name": (
        "canonical_species_name",
        "accepted_species_name",
    ),
    "source_species_name": (
        "source_species_name",
        "workflow_species_label",
        "orthofinder_species_label",
    ),
    "taxon_id": (
        "taxon_id",
        "ncbi_taxon_id",
        "resolved_taxon_id",
    ),
    "lineage_taxon_ids": ("lineage_taxon_ids",),
    "lineage_names": ("lineage_names",),
    "lineage_ranks": ("lineage_ranks",),
    "taxon_rank": ("taxon_rank", "rank"),
    "mapping_status": ("mapping_status",),
    "role": ("role",),
}
REVIEWED_MAPPING_STATUS = "REVIEWED"


@dataclass(frozen=True)
class TaxonomyAuthority:
    """Validated taxonomy tables and their provenance.

    Attributes:
        species_taxonomy: Reviewed source-label-to-taxonomy mappings.
        taxonomy_nodes: Nodes reconstructed from every reviewed lineage.
        source_label: Human-readable provenance for the active mapping.
        input_row_count: Rows read before review-status filtering.
        reviewed_row_count: Rows accepted as authoritative mappings.
        excluded_row_count: Rows retained outside the active authority because
            their status is not ``REVIEWED``.
    """

    species_taxonomy: pd.DataFrame
    taxonomy_nodes: pd.DataFrame
    source_label: str
    input_row_count: int
    reviewed_row_count: int
    excluded_row_count: int


@dataclass(frozen=True)
class TaxonomyFilters:
    """Taxon-ID predicates selected for an orthology-group query.

    Attributes:
        required_exact_taxon_ids: Species taxon IDs that must occur exactly.
        include_clade_taxon_ids: Clades that must each contain at least one member.
        only_clade_taxon_ids: Clades outside which no mapped member may occur.
        excluded_exact_taxon_ids: Species taxon IDs that must not occur exactly.
        excluded_clade_taxon_ids: Clades from which no member may occur.
    """

    required_exact_taxon_ids: tuple[int, ...] = ()
    include_clade_taxon_ids: tuple[int, ...] = ()
    only_clade_taxon_ids: tuple[int, ...] = ()
    excluded_exact_taxon_ids: tuple[int, ...] = ()
    excluded_clade_taxon_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class CompiledTaxonomyFilters:
    """Species-label sets compiled from validated taxon-ID predicates."""

    required_exact_species: tuple[str, ...]
    include_clade_species: tuple[tuple[int, tuple[str, ...]], ...]
    only_allowed_species: tuple[str, ...] | None
    excluded_species: tuple[str, ...]
    mapped_species: tuple[str, ...]
    selected_scope_species: tuple[str, ...]
    species_taxon_ids: tuple[tuple[str, int], ...]

    @property
    def active(self) -> bool:
        """Return whether at least one taxonomy predicate is active."""
        return bool(
            self.required_exact_species
            or self.include_clade_species
            or self.only_allowed_species is not None
            or self.excluded_species
        )


def _normalise_taxon_ids(values: Iterable[object]) -> tuple[int, ...]:
    """Return unique positive integer taxon IDs in input order.

    Args:
        values: Candidate NCBI taxonomy identifiers.

    Returns:
        Normalised identifier tuple.

    Raises:
        AppError: If a value is Boolean, non-integral or non-positive.
    """
    normalised: list[int] = []
    for value in values:
        if isinstance(value, bool):
            raise AppError("Taxon IDs must be positive integers")
        try:
            taxon_id = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise AppError("Taxon IDs must be positive integers") from exc
        if taxon_id <= 0 or str(value).strip() != str(taxon_id):
            raise AppError("Taxon IDs must be positive integers")
        if taxon_id not in normalised:
            normalised.append(taxon_id)
    return tuple(normalised)


def taxonomy_filters(
    *,
    required_exact_taxon_ids: Sequence[object] = (),
    include_clade_taxon_ids: Sequence[object] = (),
    only_clade_taxon_ids: Sequence[object] = (),
    excluded_exact_taxon_ids: Sequence[object] = (),
    excluded_clade_taxon_ids: Sequence[object] = (),
) -> TaxonomyFilters:
    """Build normalised taxonomy predicates from user-facing values.

    Args:
        required_exact_taxon_ids: Exact species IDs that must occur.
        include_clade_taxon_ids: Clade IDs that must occur, outside hits allowed.
        only_clade_taxon_ids: Clade IDs outside which mapped hits are forbidden.
        excluded_exact_taxon_ids: Exact species IDs that are forbidden.
        excluded_clade_taxon_ids: Clade IDs below which hits are forbidden.

    Returns:
        Immutable normalised predicates.
    """
    return TaxonomyFilters(
        required_exact_taxon_ids=_normalise_taxon_ids(
            required_exact_taxon_ids
        ),
        include_clade_taxon_ids=_normalise_taxon_ids(
            include_clade_taxon_ids
        ),
        only_clade_taxon_ids=_normalise_taxon_ids(only_clade_taxon_ids),
        excluded_exact_taxon_ids=_normalise_taxon_ids(
            excluded_exact_taxon_ids
        ),
        excluded_clade_taxon_ids=_normalise_taxon_ids(
            excluded_clade_taxon_ids
        ),
    )


def load_taxonomy_nodes() -> pd.DataFrame:
    """Load the versioned subset of NCBI taxonomy shipped with the app.

    Returns:
        Validated taxonomy-node table.

    Raises:
        AppError: If the packaged snapshot is missing or malformed.
    """
    resource = files("e3app").joinpath("resources", "taxonomy_nodes.tsv")
    try:
        table = pd.read_csv(resource, sep="\t", dtype_backend="numpy_nullable")
    except (FileNotFoundError, OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise AppError("The packaged taxonomy-node snapshot is unavailable") from exc
    missing = sorted(set(TAXONOMY_NODE_COLUMNS).difference(table.columns))
    if missing:
        raise AppError(
            "The taxonomy-node snapshot is missing columns: "
            + ", ".join(missing)
        )
    numeric = pd.to_numeric(table["taxon_id"], errors="coerce")
    if numeric.isna().any() or (numeric <= 0).any() or numeric.duplicated().any():
        raise AppError("The taxonomy-node snapshot contains invalid taxon IDs")
    table = table.copy()
    table["taxon_id"] = numeric.astype("int64")
    return table.sort_values(["name", "taxon_id"]).reset_index(drop=True)


def _load_packaged_species_taxonomy() -> pd.DataFrame:
    """Load the maintained species mapping distributed with the application.

    Returns:
        Packaged species-to-taxonomy mapping.

    Raises:
        AppError: If the packaged mapping is unavailable or malformed.
    """
    resource = files("e3app").joinpath("resources", "species_taxonomy.tsv")
    try:
        with resource.open(mode="r", encoding="utf-8", newline="") as handle:
            table = pd.read_csv(
                handle,
                sep="\t",
                dtype_backend="numpy_nullable",
            )
    except (FileNotFoundError, OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise AppError("The packaged species taxonomy mapping is unavailable") from exc
    missing = sorted(set(SPECIES_TAXONOMY_COLUMNS).difference(table.columns))
    if missing:
        raise AppError(
            "The packaged species taxonomy mapping is missing columns: "
            + ", ".join(missing)
        )
    return table


def _source_column(
    *,
    columns: Sequence[str],
    output_name: str,
    required: bool,
) -> str | None:
    """Choose one documented source-column alias.

    Args:
        columns: Input table column names.
        output_name: Canonical field requested by the loader.
        required: Whether absence must fail validation.

    Returns:
        Matching source column or ``None`` for an absent optional field.

    Raises:
        AppError: If no required alias exists or several aliases are present.
    """
    aliases = CUSTOM_TAXONOMY_ALIASES[output_name]
    present = [alias for alias in aliases if alias in columns]
    if len(present) > 1:
        raise AppError(
            f"Taxonomy mapping supplies several aliases for {output_name}: "
            + ", ".join(present)
        )
    if not present and required:
        raise AppError(
            f"Taxonomy mapping requires one of: {', '.join(aliases)}"
        )
    return present[0] if present else None


def _split_lineage(value: object, *, field: str) -> list[str]:
    """Split one non-empty semicolon-delimited lineage field.

    Args:
        value: Cell value to split.
        field: Field name used in validation errors.

    Returns:
        Ordered non-empty tokens.

    Raises:
        AppError: If the lineage field is empty or contains an empty token.
    """
    text = str(value if value is not None else "").strip()
    if not text:
        raise AppError(f"Reviewed taxonomy rows require {field}")
    tokens = [token.strip() for token in text.split(";")]
    if any(not token for token in tokens):
        raise AppError(f"Taxonomy mapping contains an empty {field} token")
    return tokens


def _positive_taxon_id(value: object, *, field: str) -> int:
    """Parse one strict positive taxonomy identifier.

    Args:
        value: Candidate identifier.
        field: Field label used in errors.

    Returns:
        Positive integer identifier.

    Raises:
        AppError: If the value is Boolean, non-integral or non-positive.
    """
    if isinstance(value, bool):
        raise AppError(f"{field} must contain positive integer taxon IDs")
    cleaned = str(value if value is not None else "").strip()
    try:
        taxon_id = int(cleaned)
    except (TypeError, ValueError) as exc:
        raise AppError(f"{field} must contain positive integer taxon IDs") from exc
    if taxon_id <= 0 or cleaned != str(taxon_id):
        raise AppError(f"{field} must contain positive integer taxon IDs")
    return taxon_id


def _custom_taxonomy_rows(
    *, table: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Standardise reviewed custom mappings and reconstruct their node table.

    Args:
        table: Parsed user-supplied TSV.

    Returns:
        Standardised species mapping and taxonomy-node tables.

    Raises:
        AppError: If required values, lineages or node metadata are ambiguous.
    """
    columns = [str(column) for column in table.columns]
    source_columns = {
        name: _source_column(
            columns=columns,
            output_name=name,
            required=name
            in {"source_species_name", "taxon_id", "lineage_taxon_ids"},
        )
        for name in CUSTOM_TAXONOMY_ALIASES
    }
    status_column = source_columns["mapping_status"]
    if status_column is None:
        reviewed = table.copy()
    else:
        statuses = table[status_column].fillna("").astype(str).str.strip().str.upper()
        reviewed = table.loc[statuses.eq(REVIEWED_MAPPING_STATUS)].copy()
    if reviewed.empty:
        raise AppError("Taxonomy mapping contains no REVIEWED rows")

    source_column = str(source_columns["source_species_name"])
    sources = reviewed[source_column].fillna("").astype(str).str.strip()
    if sources.eq("").any():
        raise AppError("Reviewed taxonomy rows require a source species label")
    folded = sources.str.casefold()
    if folded.duplicated(keep=False).any():
        duplicates = sorted(sources.loc[folded.duplicated(keep=False)].unique())
        raise AppError(
            "Reviewed taxonomy source labels must be unique: "
            + ", ".join(duplicates)
        )

    species_records: list[dict[str, object]] = []
    node_records: dict[int, dict[str, object]] = {}
    for index, row in reviewed.iterrows():
        source = str(row[source_column]).strip()
        taxon_column = str(source_columns["taxon_id"])
        leaf_id = _positive_taxon_id(row[taxon_column], field="taxon_id")
        canonical_column = source_columns["canonical_species_name"]
        canonical = (
            str(row[canonical_column]).strip()
            if canonical_column is not None
            else source.replace("_", " ")
        )
        if not canonical:
            raise AppError(
                f"Reviewed taxonomy row {index + 2} requires an accepted name"
            )
        lineage_column = str(source_columns["lineage_taxon_ids"])
        raw_identifiers = _split_lineage(
            row[lineage_column],
            field="lineage_taxon_ids",
        )
        lineage_ids = [
            _positive_taxon_id(token, field="lineage_taxon_ids")
            for token in raw_identifiers
        ]
        if len(lineage_ids) != len(set(lineage_ids)):
            raise AppError(
                f"Taxonomy lineage for {source} repeats a taxon ID"
            )
        if leaf_id in lineage_ids and lineage_ids[-1] != leaf_id:
            raise AppError(
                f"Terminal taxon {leaf_id} is not last in the lineage for {source}"
            )

        names_column = source_columns["lineage_names"]
        ranks_column = source_columns["lineage_ranks"]
        names = (
            _split_lineage(row[names_column], field="lineage_names")
            if names_column is not None and str(row[names_column]).strip()
            else [f"Taxon {identifier}" for identifier in lineage_ids]
        )
        ranks = (
            _split_lineage(row[ranks_column], field="lineage_ranks")
            if ranks_column is not None and str(row[ranks_column]).strip()
            else ["lineage" for _ in lineage_ids]
        )
        if len(names) != len(lineage_ids) or len(ranks) != len(lineage_ids):
            raise AppError(
                f"Lineage IDs, names and ranks must have equal lengths for {source}"
            )
        rank_column = source_columns["taxon_rank"]
        leaf_rank = (
            str(row[rank_column]).strip()
            if rank_column is not None
            else ""
        ) or "terminal taxon"
        if leaf_id not in lineage_ids:
            lineage_ids.append(leaf_id)
            names.append(canonical)
            ranks.append(leaf_rank)
        else:
            names[-1] = canonical
            if rank_column is not None or ranks_column is None:
                ranks[-1] = leaf_rank

        for position, identifier in enumerate(lineage_ids):
            parent = lineage_ids[position - 1] if position else identifier
            candidate = {
                "taxon_id": identifier,
                "name": names[position],
                "rank": ranks[position] or "no rank",
                "parent_taxon_id": parent,
            }
            existing = node_records.get(identifier)
            if existing is not None and existing != candidate:
                raise AppError(
                    f"Taxon {identifier} has inconsistent lineage metadata"
                )
            node_records[identifier] = candidate

        role_column = source_columns["role"]
        role = (
            str(row[role_column]).strip()
            if role_column is not None
            else ""
        ) or "unclassified"
        species_records.append(
            {
                "canonical_species_name": canonical,
                "source_species_name": source,
                "taxon_id": leaf_id,
                "lineage_taxon_ids": ";".join(map(str, lineage_ids)),
                "role": role,
                "mapping_status": REVIEWED_MAPPING_STATUS,
            }
        )

    species = pd.DataFrame.from_records(species_records)
    nodes = pd.DataFrame.from_records(list(node_records.values()))
    species["taxon_id"] = species["taxon_id"].astype("int64")
    nodes["taxon_id"] = nodes["taxon_id"].astype("int64")
    nodes["parent_taxon_id"] = nodes["parent_taxon_id"].astype("int64")
    return (
        species.sort_values(
            ["canonical_species_name", "source_species_name"],
            kind="stable",
        ).reset_index(drop=True),
        nodes.sort_values(["name", "taxon_id"], kind="stable").reset_index(
            drop=True
        ),
    )


def load_taxonomy_authority(
    *, taxonomy_map: Path | None = None
) -> TaxonomyAuthority:
    """Load the default snapshot or a reviewed arbitrary-taxonomy bridge TSV.

    A custom bridge can include species, subspecies, varieties and cultivars.
    It is matched to the loaded OrthoFinder data by exact source label. When a
    ``mapping_status`` column is supplied, only rows explicitly marked
    ``REVIEWED`` become active; no pending or ambiguous name is guessed.

    Args:
        taxonomy_map: Optional custom TSV path.

    Returns:
        Validated species and node authority with provenance counts.

    Raises:
        AppError: If the custom file cannot be read or violates the contract.
    """
    if taxonomy_map is None:
        species = _load_packaged_species_taxonomy()
        nodes = load_taxonomy_nodes()
        LOGGER.info(
            "Loaded packaged taxonomy authority with %d species mappings",
            len(species),
        )
        return TaxonomyAuthority(
            species_taxonomy=species,
            taxonomy_nodes=nodes,
            source_label="packaged 13-species E3 taxonomy snapshot",
            input_row_count=len(species),
            reviewed_row_count=len(species),
            excluded_row_count=0,
        )
    path = Path(taxonomy_map).expanduser().resolve()
    try:
        table = pd.read_csv(
            path,
            sep="\t",
            dtype="string",
            keep_default_na=False,
        )
    except (FileNotFoundError, OSError, UnicodeError, pd.errors.ParserError) as exc:
        LOGGER.exception("Could not read custom taxonomy mapping %s", path)
        raise AppError(f"Could not read taxonomy mapping TSV: {path}") from exc
    if table.empty:
        raise AppError("Taxonomy mapping TSV contains no rows")
    species, nodes = _custom_taxonomy_rows(table=table)
    status_column = _source_column(
        columns=[str(column) for column in table.columns],
        output_name="mapping_status",
        required=False,
    )
    reviewed_count = len(species)
    excluded_count = len(table) - reviewed_count if status_column is not None else 0
    LOGGER.info(
        "Loaded custom taxonomy authority path=%s reviewed=%d excluded=%d",
        path,
        reviewed_count,
        excluded_count,
    )
    return TaxonomyAuthority(
        species_taxonomy=species,
        taxonomy_nodes=nodes,
        source_label=str(path),
        input_row_count=len(table),
        reviewed_row_count=reviewed_count,
        excluded_row_count=excluded_count,
    )


def _lineage_ids(value: object) -> frozenset[int]:
    """Parse one semicolon-delimited lineage, failing closed on bad data."""
    identifiers: set[int] = set()
    for token in str(value or "").split(";"):
        token = token.strip()
        if not token:
            continue
        try:
            identifier = int(token)
        except ValueError as exc:
            raise AppError("Species taxonomy contains a malformed lineage") from exc
        if identifier <= 0:
            raise AppError("Species taxonomy contains a malformed lineage")
        identifiers.add(identifier)
    return frozenset(identifiers)


def compile_taxonomy_filters(
    *,
    filters: TaxonomyFilters,
    species_taxonomy: pd.DataFrame,
    available_species: Sequence[str],
    taxonomy_nodes: pd.DataFrame | None = None,
) -> CompiledTaxonomyFilters:
    """Compile taxon predicates into exact source-species label sets.

    The supplied authority may be the packaged snapshot or an input-specific
    reviewed bridge. A requested taxon is rejected when it cannot affect the
    loaded release, preventing a silently empty or misleading query.

    Args:
        filters: Normalised taxon-ID predicates.
        species_taxonomy: Curated species mapping and lineage table.
        available_species: Species labels present in the selected membership table.
        taxonomy_nodes: Optional preloaded node table for testing.

    Returns:
        Compiled species sets suitable for parameterised SQL.

    Raises:
        AppError: If the mapping is malformed, a taxon is unavailable, or the
            predicates contradict one another.
    """
    missing = sorted(
        set(SPECIES_TAXONOMY_COLUMNS).difference(species_taxonomy.columns)
    )
    if missing:
        raise AppError(
            "The species taxonomy mapping is missing columns: "
            + ", ".join(missing)
        )
    nodes = load_taxonomy_nodes() if taxonomy_nodes is None else taxonomy_nodes
    node_ids = set(pd.to_numeric(nodes["taxon_id"], errors="coerce").dropna().astype(int))
    requested = set(
        filters.required_exact_taxon_ids
        + filters.include_clade_taxon_ids
        + filters.only_clade_taxon_ids
        + filters.excluded_exact_taxon_ids
        + filters.excluded_clade_taxon_ids
    )
    unknown = sorted(requested.difference(node_ids))
    if unknown:
        raise AppError(
            "Taxon IDs are not available in the active taxonomy authority: "
            + ", ".join(map(str, unknown))
        )

    available = {str(value).strip() for value in available_species if str(value).strip()}
    records: list[tuple[str, int, frozenset[int]]] = []
    for row in species_taxonomy.itertuples(index=False):
        source = str(row.source_species_name).strip()
        if not source or source not in available:
            continue
        try:
            leaf_id = int(row.taxon_id)
        except (TypeError, ValueError) as exc:
            raise AppError("Species taxonomy contains an invalid taxon ID") from exc
        lineage = _lineage_ids(row.lineage_taxon_ids) | {leaf_id}
        records.append((source, leaf_id, lineage))
    mapped_species = tuple(sorted({record[0] for record in records}))

    def exact_species(taxon_id: int) -> tuple[str, ...]:
        return tuple(sorted(source for source, leaf, _ in records if leaf == taxon_id))

    def clade_species(taxon_id: int) -> tuple[str, ...]:
        return tuple(
            sorted(source for source, _, lineage in records if taxon_id in lineage)
        )

    required: list[str] = []
    for taxon_id in filters.required_exact_taxon_ids:
        matches = exact_species(taxon_id)
        if not matches:
            raise AppError(
                f"Exact taxon ID {taxon_id} is not represented in this relation"
            )
        required.extend(matches)
    included: list[tuple[int, tuple[str, ...]]] = []
    for taxon_id in filters.include_clade_taxon_ids:
        matches = clade_species(taxon_id)
        if not matches:
            raise AppError(
                f"Clade taxon ID {taxon_id} is not represented in this relation"
            )
        included.append((taxon_id, matches))
    only_sets: list[set[str]] = []
    for taxon_id in filters.only_clade_taxon_ids:
        matches = set(clade_species(taxon_id))
        if not matches:
            raise AppError(
                f"Only-in clade taxon ID {taxon_id} is not represented in this relation"
            )
        only_sets.append(matches)
    only_allowed = (
        tuple(sorted(set.intersection(*only_sets))) if only_sets else None
    )
    if only_allowed == ():
        raise AppError("Selected only-in clades have no represented species in common")

    excluded: set[str] = set()
    for taxon_id in filters.excluded_exact_taxon_ids:
        matches = exact_species(taxon_id)
        if not matches:
            raise AppError(
                f"Excluded exact taxon ID {taxon_id} is not represented in this relation"
            )
        excluded.update(matches)
    for taxon_id in filters.excluded_clade_taxon_ids:
        matches = clade_species(taxon_id)
        if not matches:
            raise AppError(
                f"Excluded clade taxon ID {taxon_id} is not represented in this relation"
            )
        excluded.update(matches)

    required_set = set(required)
    if required_set.intersection(excluded):
        raise AppError("A required exact taxon is also excluded")
    for taxon_id, matches in included:
        if set(matches).issubset(excluded):
            raise AppError(f"Included clade taxon ID {taxon_id} is fully excluded")
    if only_allowed is not None and set(only_allowed).issubset(excluded):
        raise AppError("The selected only-in scope is fully excluded")
    if only_allowed is not None and not required_set.issubset(set(only_allowed)):
        raise AppError("A required exact taxon falls outside the only-in clade")

    scope: set[str] = set(required)
    for _, matches in included:
        scope.update(matches)
    if only_allowed is not None:
        scope.update(only_allowed)
    return CompiledTaxonomyFilters(
        required_exact_species=tuple(dict.fromkeys(required)),
        include_clade_species=tuple(included),
        only_allowed_species=only_allowed,
        excluded_species=tuple(sorted(excluded)),
        mapped_species=mapped_species,
        selected_scope_species=tuple(sorted(scope)),
        species_taxon_ids=tuple(
            sorted((source, leaf_id) for source, leaf_id, _ in records)
        ),
    )


def taxonomy_choice_labels(nodes: pd.DataFrame) -> dict[int, str]:
    """Return taxon IDs mapped to readable ``name — rank — ID`` labels.

    Args:
        nodes: Validated taxonomy-node table.

    Returns:
        Choice labels ordered by the caller's node table.
    """
    missing = sorted(set(TAXONOMY_NODE_COLUMNS).difference(nodes.columns))
    if missing:
        raise AppError("Taxonomy choices require: " + ", ".join(missing))
    return {
        int(row.taxon_id): f"{row.name} — {row.rank} — taxon {int(row.taxon_id)}"
        for row in nodes.itertuples(index=False)
    }
