"""Versioned, release-local taxonomy predicates for orthology groups."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from typing import Iterable, Sequence

import pandas as pd

from e3app.errors import AppError

TAXONOMY_NODE_COLUMNS = ("taxon_id", "name", "rank", "parent_taxon_id")
SPECIES_TAXONOMY_COLUMNS = (
    "canonical_species_name",
    "source_species_name",
    "taxon_id",
    "lineage_taxon_ids",
)


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

    The packaged snapshot covers the curated release species only. A requested
    taxon is rejected when it cannot affect the loaded release, preventing a
    silently empty or scientifically misleading query.

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
            "Taxon IDs are not available in this versioned release snapshot: "
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
