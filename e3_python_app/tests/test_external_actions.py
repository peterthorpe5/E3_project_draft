"""Tests for reproducible external pair-analysis actions."""

from __future__ import annotations

import pandas as pd
import pytest

from e3app.errors import AppError
from e3app.external_actions import (
    ALPHAFOLD_ENTRY_BASE_URL,
    EMERALD_BASE_URL,
    RCSB_MOLSTAR_URL,
    RCSB_PAIRWISE_ALIGNMENT_URL,
    build_alphafold_entry_url,
    build_emerald_pair_url,
    external_pair_actions,
    normalise_uniprot_accession,
    selected_pair_fasta_bytes,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" p12345 ", "P12345"),
        ("E0CX11", "E0CX11"),
        ("q9udw1", "Q9UDW1"),
        ("A0A023GPI8", "A0A023GPI8"),
        ("P12345-2", None),
        ("sp|P12345|PROTEIN", None),
        ("local_protein", None),
        (None, None),
    ],
)
def test_uniprot_accessions_are_normalised_without_guessing(
    value: object,
    expected: str | None,
) -> None:
    """Only complete canonical six- or ten-character accessions are accepted."""
    assert normalise_uniprot_accession(value=value) == expected


def test_emerald_and_structure_urls_preserve_pair_roles() -> None:
    """External actions expose the selected reference and comparison safely."""
    url = build_emerald_pair_url(
        reference_accession="e0cx11",
        comparison_accession="Q9UDW1",
    )
    assert url == (
        f"{EMERALD_BASE_URL}?seqA=E0CX11&seqB=Q9UDW1&alpha=0.75&delta=8"
    )
    actions = external_pair_actions(
        reference_accession="E0CX11",
        comparison_accession="Q9UDW1",
    )
    assert actions.emerald_url == url
    assert actions.reference_alphafold_url == (
        f"{ALPHAFOLD_ENTRY_BASE_URL}E0CX11"
    )
    assert actions.comparison_alphafold_url == (
        f"{ALPHAFOLD_ENTRY_BASE_URL}Q9UDW1"
    )
    assert actions.rcsb_molstar_url == RCSB_MOLSTAR_URL
    assert actions.rcsb_pairwise_alignment_url == RCSB_PAIRWISE_ALIGNMENT_URL


def test_non_uniprot_pair_retains_generic_structure_actions() -> None:
    """Local identifiers disable accession links but retain generic tools."""
    actions = external_pair_actions(
        reference_accession="plant_scaffold_1",
        comparison_accession="P12345-2",
    )
    assert actions.emerald_url is None
    assert actions.reference_alphafold_url is None
    assert actions.comparison_alphafold_url is None
    assert actions.rcsb_molstar_url == RCSB_MOLSTAR_URL


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"alpha": True}, "alpha must be"),
        ({"alpha": -0.01}, "alpha must be"),
        ({"alpha": 1.01}, "alpha must be"),
        ({"alpha": "0.75"}, "alpha must be"),
        ({"delta": True}, "delta must be"),
        ({"delta": -1}, "delta must be"),
        ({"delta": 101}, "delta must be"),
        ({"delta": 8.0}, "delta must be"),
    ],
)
def test_invalid_emerald_parameters_fail_explicitly(
    kwargs: dict[str, object],
    message: str,
) -> None:
    """Malformed numeric URL parameters never leak into external actions."""
    with pytest.raises(AppError, match=message):
        build_emerald_pair_url(
            reference_accession="E0CX11",
            comparison_accession="Q9UDW1",
            **kwargs,
        )


def test_alphafold_and_pair_actions_require_exact_identifiers() -> None:
    """Blank identifiers and isoform guessing are rejected consistently."""
    assert build_alphafold_entry_url(accession="P12345-2") is None
    with pytest.raises(AppError, match="Both reference and comparison"):
        external_pair_actions(
            reference_accession="",
            comparison_accession="Q9UDW1",
        )


def test_selected_pair_fasta_uses_ordered_sources_and_ungaps_sequences() -> None:
    """The download contains the exact chosen pair with source precedence."""
    primary = pd.DataFrame(
        {
            "candidate_accession": ["reference"],
            "amino_acid_sequence": ["ACD-EF"],
        }
    )
    supplementary = pd.DataFrame(
        {
            "candidate_accession": ["reference", "comparison"],
            "protein_sequence": ["XXXX", "GH I-JK"],
        }
    )
    observed = selected_pair_fasta_bytes(
        sources=(primary, supplementary),
        reference_accession="reference",
        comparison_accession="comparison",
    ).decode("utf-8")
    assert observed == (
        ">reference role=reference\nACDEF\n"
        ">comparison role=comparison\nGHIJK\n"
    )


def test_selected_pair_fasta_wraps_and_sanitises_headers() -> None:
    """FASTA lines are portable and header control characters are removed."""
    reference = "plant\nprotein"
    sequence = "A" * 81
    frame = pd.DataFrame(
        {
            "candidate_accession": [reference, "comparison"],
            "aligned_sequence": [sequence, "C-D"],
        }
    )
    observed = selected_pair_fasta_bytes(
        sources=(frame,),
        reference_accession=reference,
        comparison_accession="comparison",
    ).decode("utf-8")
    assert ">plant protein role=reference\n" in observed
    assert f"{'A' * 80}\nA\n" in observed
    assert observed.endswith(">comparison role=comparison\nCD\n")


def test_selected_pair_fasta_rejects_ambiguous_or_invalid_inputs() -> None:
    """Missing, conflicting, identical and malformed sequence inputs fail."""
    conflicting = pd.DataFrame(
        {
            "candidate_accession": ["A", "A", "B"],
            "amino_acid_sequence": ["ACD", "ACE", "B*D"],
        }
    )
    with pytest.raises(AppError, match="must be different"):
        selected_pair_fasta_bytes(
            sources=(conflicting,),
            reference_accession="A",
            comparison_accession="a",
        )
    with pytest.raises(AppError, match="Conflicting exact sequences"):
        selected_pair_fasta_bytes(
            sources=(conflicting,),
            reference_accession="A",
            comparison_accession="B",
        )
    with pytest.raises(AppError, match="No exact sequence"):
        selected_pair_fasta_bytes(
            sources=(conflicting.iloc[0:1],),
            reference_accession="A",
            comparison_accession="missing",
        )
    invalid = conflicting.iloc[[0, 2]].copy()
    with pytest.raises(AppError, match="Invalid amino-acid sequence"):
        selected_pair_fasta_bytes(
            sources=(invalid,),
            reference_accession="A",
            comparison_accession="B",
        )
