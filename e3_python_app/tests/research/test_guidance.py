"""Unit tests for generic guidance, exact identifiers and optional route setup."""

from dataclasses import replace
import sys

import pandas as pd
import pytest

from e3app.research.common import ResearchConfig, ResearchError
from e3app.research.guidance import (
    FIELD_HELP,
    PAGE_GUIDES,
    job_label,
    provider_problem,
    retrievable_cluster_ids,
    user_guide,
)


def test_generic_and_project_guides_share_the_core_workflow():
    """The project adapter is optional and never required for FASTA analysis."""
    generic = user_guide(include_e3=False)
    project = user_guide(include_e3=True)
    assert "## Starting from E3" not in generic
    assert "## Starting from E3" in project
    for title, aim, instructions in PAGE_GUIDES.values():
        assert title in generic and aim in generic and instructions in generic
    assert "does not calculate a medoid" in project
    assert "does not calculate a medoid" in generic
    assert "not an automatic descendant search" in FIELD_HELP["taxa"]
    assert "first ID in sorted identifier order" in FIELD_HELP["reference"]
    assert all(value.strip() for value in FIELD_HELP.values())


@pytest.mark.parametrize(
    "stamp,expected",
    [
        ("2026-10-22T12:15:00+01:00", "22 Oct 11:15 UTC"),
        ("2026-10-22T11:15:00Z", "22 Oct 11:15 UTC"),
        ("2026-10-22T11:15:00", "22 Oct 11:15 UTC"),
        ("invalid", "time unavailable"),
        (None, "time unavailable"),
    ],
)
def test_job_labels_are_readable_and_preserve_identity(*, stamp, expected):
    """Labels convert offsets to UTC without hiding the durable job identity."""
    label = job_label(
        job_id="a" * 32,
        record={"operation": "retrieve", "created_at": stamp},
        artifact="cluster.fasta",
    )
    assert "Retrieve global clusters" in label
    assert expected in label and "cluster.fasta" in label and "a" * 12 in label
    assert "Research job" in job_label(job_id="b" * 32, record={})


def test_retrieval_choices_exclude_unmatched_unindexed_and_duplicate_rows():
    """A mapping handoff cannot offer an absent or unindexed family as retrievable."""
    frame = pd.DataFrame(
        {
            "cluster_id": ["NR_A.1", "NR_A.1", None, "unindexed", "zero", "NA", ""],
            "member_count": ["3", "3", None, "", "0", "4", "5"],
        }
    )
    assert retrievable_cluster_ids(frame=frame) == ["NR_A.1", "NA"]
    assert retrievable_cluster_ids(frame=pd.DataFrame({"cluster_id": ["x"]})) == []


def test_model_routes_explain_missing_setup_without_network(*, monkeypatch):
    """External availability is not inferred from local configuration alone."""
    config = ResearchConfig()
    assert provider_problem(config=config, operation="predict", engine="atlas") == ""
    assert "esm_endpoint" in provider_problem(
        config=config, operation="predict", engine="huggingface_endpoint"
    )
    assert (
        provider_problem(
            config=replace(config, esm_endpoint="https://endpoint.invalid"),
            operation="predict",
            engine="huggingface_endpoint",
        )
        == ""
    )
    monkeypatch.setattr("e3app.research.guidance.importlib.util.find_spec", lambda name: None)
    assert "torch, transformers" in provider_problem(
        config=config, operation="predict", engine="local"
    )
    monkeypatch.setattr("e3app.research.guidance.importlib.util.find_spec", lambda name: object())
    assert provider_problem(config=config, operation="predict", engine="local") == ""


def test_annotation_routes_require_only_their_own_configuration(*, tmp_path):
    """eggNOG, InterProScan and EBI contact checks are route-specific."""
    config = ResearchConfig(
        interproscan="/not/installed/interpro", emapper="/not/installed/emapper"
    )
    assert "email" in provider_problem(
        config=config, operation="annotate", engine="interpro_remote"
    )
    assert (
        provider_problem(
            config=replace(config, email="operator@example.org"),
            operation="annotate",
            engine="interpro_remote",
        )
        == ""
    )
    assert "unavailable" in provider_problem(
        config=config, operation="annotate", engine="interpro_local"
    )
    assert (
        provider_problem(
            config=replace(config, interproscan=sys.executable),
            operation="annotate",
            engine="interpro_local",
        )
        == ""
    )
    assert "Install eggNOG" in provider_problem(
        config=config, operation="annotate", engine="eggnog"
    )
    configured = replace(config, emapper=sys.executable)
    assert "eggnog_data" in provider_problem(
        config=configured, operation="annotate", engine="eggnog"
    )
    assert (
        provider_problem(
            config=replace(configured, eggnog_data=str(tmp_path)),
            operation="annotate",
            engine="eggnog",
        )
        == ""
    )


@pytest.mark.parametrize(
    "operation,engine", [("bad", "atlas"), ("predict", "bad"), ("annotate", "bad")]
)
def test_unknown_provider_routes_are_rejected(*, operation, engine):
    """Invalid route names cannot silently enable a submission."""
    with pytest.raises(ResearchError, match="Unknown"):
        provider_problem(config=ResearchConfig(), operation=operation, engine=engine)
