"""Tests for release-local taxon-ID predicate compilation."""

from __future__ import annotations

import pandas as pd
import pytest

from e3app.errors import AppError
from e3app.taxonomy import (
    compile_taxonomy_filters,
    load_taxonomy_nodes,
    taxonomy_choice_labels,
    taxonomy_filters,
)


def _species_taxonomy() -> pd.DataFrame:
    """Return a minimal plant taxonomy mapping for isolated tests."""
    return pd.DataFrame(
        {
            "canonical_species_name": ["Grass one", "Grass two", "Potato"],
            "source_species_name": ["grass_one", "grass_two", "potato"],
            "taxon_id": [101, 102, 201],
            "lineage_taxon_ids": ["1;10;101", "1;10;102", "1;20;201"],
        }
    )


def _nodes() -> pd.DataFrame:
    """Return matching minimal taxonomy nodes."""
    return pd.DataFrame(
        {
            "taxon_id": [1, 10, 20, 101, 102, 201],
            "name": ["root", "grasses", "nightshades", "one", "two", "potato"],
            "rank": ["root", "family", "family", "species", "species", "species"],
            "parent_taxon_id": [None, 1, 1, 10, 10, 20],
        }
    )


def test_taxonomy_filter_values_are_normalised_and_validated() -> None:
    """Taxon IDs are unique positive integers and Boolean values fail closed."""
    filters = taxonomy_filters(
        required_exact_taxon_ids=(101, "101"),
        include_clade_taxon_ids=(10,),
        excluded_exact_taxon_ids=(201,),
    )
    assert filters.required_exact_taxon_ids == (101,)
    assert filters.include_clade_taxon_ids == (10,)
    assert filters.excluded_exact_taxon_ids == (201,)
    with pytest.raises(AppError, match="positive integers"):
        taxonomy_filters(include_clade_taxon_ids=(True,))
    with pytest.raises(AppError, match="positive integers"):
        taxonomy_filters(include_clade_taxon_ids=("10.0",))


def test_compile_supports_exact_include_only_and_exclusion() -> None:
    """Compiled predicates preserve each requested taxonomic meaning."""
    compiled = compile_taxonomy_filters(
        filters=taxonomy_filters(
            required_exact_taxon_ids=(101,),
            include_clade_taxon_ids=(10,),
            only_clade_taxon_ids=(1,),
            excluded_exact_taxon_ids=(201,),
        ),
        species_taxonomy=_species_taxonomy(),
        available_species=("grass_one", "grass_two", "potato", "unknown"),
        taxonomy_nodes=_nodes(),
    )
    assert compiled.active
    assert compiled.required_exact_species == ("grass_one",)
    assert compiled.include_clade_species == (
        (10, ("grass_one", "grass_two")),
    )
    assert compiled.only_allowed_species == (
        "grass_one",
        "grass_two",
        "potato",
    )
    assert compiled.excluded_species == ("potato",)
    assert compiled.mapped_species == ("grass_one", "grass_two", "potato")


def test_compile_rejects_unavailable_and_contradictory_predicates() -> None:
    """Unavailable or impossible selections never become silent negatives."""
    common = {
        "species_taxonomy": _species_taxonomy(),
        "available_species": ("grass_one", "grass_two", "potato"),
        "taxonomy_nodes": _nodes(),
    }
    with pytest.raises(AppError, match="not available"):
        compile_taxonomy_filters(
            filters=taxonomy_filters(include_clade_taxon_ids=(999,)),
            **common,
        )
    with pytest.raises(AppError, match="also excluded"):
        compile_taxonomy_filters(
            filters=taxonomy_filters(
                required_exact_taxon_ids=(101,),
                excluded_exact_taxon_ids=(101,),
            ),
            **common,
        )
    with pytest.raises(AppError, match="outside the only-in"):
        compile_taxonomy_filters(
            filters=taxonomy_filters(
                required_exact_taxon_ids=(201,),
                only_clade_taxon_ids=(10,),
            ),
            **common,
        )
    with pytest.raises(AppError, match="fully excluded"):
        compile_taxonomy_filters(
            filters=taxonomy_filters(
                include_clade_taxon_ids=(10,),
                excluded_clade_taxon_ids=(10,),
            ),
            **common,
        )


def test_packaged_taxonomy_snapshot_and_labels_are_valid() -> None:
    """The installed resource exposes verified clade and species labels."""
    nodes = load_taxonomy_nodes()
    labels = taxonomy_choice_labels(nodes)
    assert labels[4479] == "Poaceae — family — taxon 4479"
    assert labels[4113] == "Solanum tuberosum — species — taxon 4113"
    with pytest.raises(AppError, match="require"):
        taxonomy_choice_labels(nodes.drop(columns="rank"))


def test_compile_rejects_malformed_mapping_contracts() -> None:
    """Bad release mappings are reported before a scientific query executes."""
    with pytest.raises(AppError, match="missing columns"):
        compile_taxonomy_filters(
            filters=taxonomy_filters(),
            species_taxonomy=_species_taxonomy().drop(columns="lineage_taxon_ids"),
            available_species=("grass_one",),
            taxonomy_nodes=_nodes(),
        )
    malformed = _species_taxonomy()
    malformed.loc[0, "lineage_taxon_ids"] = "1;bad"
    with pytest.raises(AppError, match="malformed lineage"):
        compile_taxonomy_filters(
            filters=taxonomy_filters(include_clade_taxon_ids=(10,)),
            species_taxonomy=malformed,
            available_species=("grass_one",),
            taxonomy_nodes=_nodes(),
        )
