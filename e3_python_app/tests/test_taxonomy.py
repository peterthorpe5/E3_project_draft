"""Tests for release-local taxon-ID predicate compilation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import e3app.taxonomy as taxonomy_module
from e3app.errors import AppError
from e3app.taxonomy import (
    compile_taxonomy_filters,
    load_taxonomy_authority,
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


def test_custom_taxonomy_supports_new_species_and_cultivars(
    tmp_path: Path,
) -> None:
    """A reviewed bridge extends exact and descendant selectors offline."""
    mapping = tmp_path / "taxonomy_bridge.tsv"
    mapping.write_text(
        "workflow_species_label\taccepted_species_name\tncbi_taxon_id\t"
        "lineage_taxon_ids\tlineage_names\tlineage_ranks\ttaxon_rank\t"
        "mapping_status\trole\n"
        "potato_cv_alpha\tSolanum tuberosum cultivar Alpha\t99001\t"
        "1;2759;33090;4113;99001\troot;Eukaryota;Viridiplantae;"
        "Solanum tuberosum;Solanum tuberosum cultivar Alpha\t"
        "no rank;superkingdom;kingdom;species;cultivar\tcultivar\t"
        "REVIEWED\ttarget_crop\n"
        "new_grass\tNew grass species\t99002\t1;2759;33090;4479;99002\t"
        "root;Eukaryota;Viridiplantae;Poaceae;New grass species\t"
        "no rank;superkingdom;kingdom;family;species\tspecies\t"
        "REVIEWED\ttarget_plant\n"
        "pending_name\tPending name\t99003\t1;99003\troot;Pending name\t"
        "no rank;species\tspecies\tPENDING_REVIEW\tunclassified\n",
        encoding="utf-8",
    )
    authority = load_taxonomy_authority(taxonomy_map=mapping)
    assert authority.input_row_count == 3
    assert authority.reviewed_row_count == 2
    assert authority.excluded_row_count == 1
    assert set(authority.species_taxonomy["source_species_name"]) == {
        "potato_cv_alpha",
        "new_grass",
    }
    labels = taxonomy_choice_labels(authority.taxonomy_nodes)
    assert labels[99001] == (
        "Solanum tuberosum cultivar Alpha — cultivar — taxon 99001"
    )
    compiled = compile_taxonomy_filters(
        filters=taxonomy_filters(
            required_exact_taxon_ids=(99001,),
            include_clade_taxon_ids=(4113,),
            excluded_clade_taxon_ids=(4479,),
        ),
        species_taxonomy=authority.species_taxonomy,
        available_species=("potato_cv_alpha", "new_grass", "pending_name"),
        taxonomy_nodes=authority.taxonomy_nodes,
    )
    assert compiled.required_exact_species == ("potato_cv_alpha",)
    assert compiled.include_clade_species == ((4113, ("potato_cv_alpha",)),)
    assert compiled.excluded_species == ("new_grass",)
    assert "pending_name" not in compiled.mapped_species


def test_custom_taxonomy_without_status_treats_rows_as_reviewed(
    tmp_path: Path,
) -> None:
    """The compact four-column contract remains usable for controlled inputs."""
    mapping = tmp_path / "compact.tsv"
    mapping.write_text(
        "source_species_name\tcanonical_species_name\ttaxon_id\t"
        "lineage_taxon_ids\n"
        "sample_one\tSample one\t88001\t1\n",
        encoding="utf-8",
    )
    authority = load_taxonomy_authority(taxonomy_map=mapping)
    assert authority.reviewed_row_count == 1
    assert authority.excluded_row_count == 0
    assert authority.species_taxonomy.loc[0, "role"] == "unclassified"
    assert set(authority.taxonomy_nodes["taxon_id"]) == {1, 88001}
    leaf = authority.taxonomy_nodes.loc[
        authority.taxonomy_nodes["taxon_id"].eq(88001)
    ].iloc[0]
    assert leaf["rank"] == "terminal taxon"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            "source_species_name\ttaxon_id\tlineage_taxon_ids\n"
            "duplicate\t70001\t1;70001\n"
            "Duplicate\t70002\t1;70002\n",
            "source labels must be unique",
        ),
        (
            "source_species_name\ttaxon_id\tlineage_taxon_ids\t"
            "mapping_status\n"
            "pending\t70001\t1;70001\tPENDING_REVIEW\n",
            "no REVIEWED rows",
        ),
        (
            "source_species_name\ttaxon_id\tlineage_taxon_ids\t"
            "lineage_names\n"
            "sample\t70001\t1;70001\troot\n",
            "must have equal lengths",
        ),
        (
            "source_species_name\ttaxon_id\tlineage_taxon_ids\n"
            "sample\t70001\t1;70001;2\n",
            "is not last",
        ),
        (
            "source_species_name\tcanonical_species_name\ttaxon_id\t"
            "lineage_taxon_ids\n"
            "sample\t\t70001\t1;70001\n",
            "requires an accepted name",
        ),
        (
            "source_species_name\ttaxon_id\tlineage_taxon_ids\n"
            "sample\t70001\t1;1;70001\n",
            "repeats a taxon ID",
        ),
        (
            "source_species_name\ttaxon_id\tlineage_taxon_ids\tlineage_names\n"
            "one\t70001\t1;70001\troot;one\n"
            "two\t70002\t1;70002\tROOT;two\n",
            "inconsistent lineage metadata",
        ),
        (
            "source_species_name\tworkflow_species_label\ttaxon_id\t"
            "lineage_taxon_ids\n"
            "one\tone\t70001\t1;70001\n",
            "several aliases",
        ),
        (
            "source_species_name\tlineage_taxon_ids\n"
            "one\t1;70001\n",
            "requires one of",
        ),
        (
            "source_species_name\ttaxon_id\tlineage_taxon_ids\n"
            "one\t70001\t\n",
            "require lineage_taxon_ids",
        ),
        (
            "source_species_name\ttaxon_id\tlineage_taxon_ids\n"
            "one\t70001\t1;;70001\n",
            "empty lineage_taxon_ids token",
        ),
        (
            "source_species_name\ttaxon_id\tlineage_taxon_ids\n"
            "one\t0\t1\n",
            "positive integer taxon IDs",
        ),
    ],
)
def test_custom_taxonomy_rejects_ambiguous_contracts(
    tmp_path: Path,
    body: str,
    message: str,
) -> None:
    """Malformed or unreviewed custom mappings fail before group filtering."""
    mapping = tmp_path / "bad.tsv"
    mapping.write_text(body, encoding="utf-8")
    with pytest.raises(AppError, match=message):
        load_taxonomy_authority(taxonomy_map=mapping)


def test_custom_taxonomy_helpers_reject_strict_scalar_failures() -> None:
    """Low-level validators reject Boolean and malformed taxonomy IDs."""
    assert taxonomy_module._source_column(
        columns=(),
        output_name="role",
        required=False,
    ) is None
    with pytest.raises(AppError, match="positive integer"):
        taxonomy_module._positive_taxon_id(True, field="taxon_id")
    with pytest.raises(AppError, match="positive integer"):
        taxonomy_module._positive_taxon_id("bad", field="taxon_id")
    with pytest.raises(AppError, match="require lineage_names"):
        taxonomy_module._split_lineage(None, field="lineage_names")


def test_custom_taxonomy_rejects_missing_and_empty_files(tmp_path: Path) -> None:
    """Unreadable and header-only mapping files fail with explicit messages."""
    with pytest.raises(AppError, match="Could not read taxonomy mapping TSV"):
        load_taxonomy_authority(taxonomy_map=tmp_path / "missing.tsv")
    empty = tmp_path / "empty.tsv"
    empty.write_text("source_species_name\ttaxon_id\tlineage_taxon_ids\n", encoding="utf-8")
    with pytest.raises(AppError, match="contains no rows"):
        load_taxonomy_authority(taxonomy_map=empty)
