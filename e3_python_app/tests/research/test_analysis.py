"""Scientific denominator, exact-centroid audit and external command contracts."""

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from e3app.research import analysis
from e3app.research.analysis import (
    REALIGN_FIELDS,
    align_family,
    alignment_statistics,
    audit_subclusters,
    auspice_dataset,
    index_fasta,
    run_command,
    subcluster,
)
from e3app.research.common import ResearchError, iter_fasta


def test_fasta_index_and_command_failures(research_config, protein_fasta, tmp_path):
    """Disk indexing rejects duplicate IDs; shell-free tools propagate failures."""
    connection, count = index_fasta(
        source=protein_fasta, destination=tmp_path / "ids.sqlite", maximum=3
    )
    assert count == 3 and connection.execute("SELECT count(*) FROM sequences").fetchone()[0] == 3
    connection.close()
    with pytest.raises(ResearchError, match="sequence bound"):
        index_fasta(source=protein_fasta, destination=tmp_path / "small.sqlite", maximum=2)
    protein_fasta.write_text(">a\nACD\n>a\nACD\n")
    with pytest.raises(ResearchError, match="Duplicate"):
        index_fasta(source=protein_fasta, destination=tmp_path / "duplicate.sqlite", maximum=3)
    protein_fasta.write_text("")
    with pytest.raises(ResearchError, match="no records"):
        index_fasta(source=protein_fasta, destination=tmp_path / "empty.sqlite", maximum=3)
    run_command(
        arguments=[sys.executable, "-c", "print('ok')"], output=tmp_path, config=research_config
    )
    assert (tmp_path / "stdout.log").read_text() == "ok\n"
    with pytest.raises(ResearchError, match="unavailable"):
        run_command(
            arguments=["missing-executable-for-test"], output=tmp_path, config=research_config
        )
    with pytest.raises(ResearchError, match="failed"):
        run_command(
            arguments=[sys.executable, "-c", "raise SystemExit(4)"],
            output=tmp_path,
            config=research_config,
        )
    with pytest.raises(ResearchError, match="timeout"):
        run_command(
            arguments=[sys.executable, "-c", "import time; time.sleep(1)"],
            output=tmp_path,
            config=replace(research_config, command_timeout=0.01),
        )


def test_exact_subclusters_cover_every_member_and_rescue_failures(research_config, tmp_path):
    """Identity and both coverages must pass; failed assignments survive as singletons."""
    membership, exact, inputs = [tmp_path / name for name in ("native.tsv", "exact.tsv", "ids.tsv")]
    membership.write_text("centroid\tmember\na\ta\na\tb\na\tc\na\td\na\te\n")
    inputs.write_text("sequence_id\na\nb\nc\nd\ne\n")
    exact.write_text(
        "a\tb\t90\t100\t100\t1\t90\t1\t90\t90\t1e-20\t100\t81\n"
        "a\tc\t90\t100\t200\t1\t90\t1\t90\t90\t1e-20\t100\t81\n"
        "a\td\t90\t100\t100\t0\t90\t1\t90\t90\t1e-20\t100\t81\n"
    )
    result = audit_subclusters(
        membership=membership,
        realignments=exact,
        source_ids=inputs,
        output=tmp_path,
        identity=70,
        coverage=80,
        evalue=1e-10,
        config=research_config,
    )
    frame = pd.read_csv(result["membership.tsv"], sep="\t").set_index("sequence_id")
    assert len(frame) == 5 and frame.subcluster_id.nunique() == 4
    assert frame.loc["b", "alignment_status"] == "EXACT_THRESHOLDS_PASS"
    assert frame.loc["c", "alignment_status"] == "EXACT_THRESHOLDS_FAIL"
    assert frame.loc["d", "alignment_status"] == "INVALID_REALIGNMENT"
    assert frame.loc["e", "alignment_status"] == "NO_REALIGNMENT"
    assert frame.loc["a", "subcluster_id"] == frame.loc["b", "subcluster_id"]
    assert frame.loc["c", "audited_representative_id"] == "c"
    summary = pd.read_csv(result["subclusters.tsv"], sep="\t")
    assert summary.member_count.sum() == 5
    assert summary.loc[summary.representative_id == "c", "minimum_passing_identity"].isna().all()
    membership.write_text("centroid\tmember\na\ta\na\tb\na\tb\n")
    with pytest.raises(ResearchError, match="every input"):
        audit_subclusters(
            membership=membership,
            realignments=exact,
            source_ids=inputs,
            output=tmp_path,
            identity=70,
            coverage=80,
            evalue=1e-10,
            config=research_config,
        )
    membership.write_text("bad\tmember\na\ta\n")
    with pytest.raises(ResearchError, match="header"):
        audit_subclusters(
            membership=membership,
            realignments=exact,
            source_ids=inputs,
            output=tmp_path,
            identity=70,
            coverage=80,
            evalue=1e-10,
            config=research_config,
        )


def test_subcluster_command_contract(research_config, protein_fasta, tmp_path, monkeypatch):
    """Worker invokes actual DeepClust and native exact realignment contracts."""
    output = tmp_path / "out"
    output.mkdir()
    calls = []

    def fake_command(*, arguments, output, config, stdout=None):
        calls.append(arguments)
        if stdout:
            stdout.write_text("DIAMOND 2.2.1\n")
        if "deepclust" in arguments:
            (output / "native_membership.tsv").write_text("centroid\tmember\na\ta\na\tb\nc\tc\n")
        if "realign" in arguments:
            (output / "exact_alignments.tsv").write_text(
                "a\tb\t100\t20\t20\t1\t20\t1\t20\t20\t1e-20\t100\t20\n"
            )

    monkeypatch.setattr(analysis, "run_command", fake_command)
    result = subcluster(config=research_config, source=protein_fasta, output=output, parameters={})
    assert "membership.parquet" in result
    deepclust = next(call for call in calls if "deepclust" in call)
    assert "--mutual-cover" in deepclust and "--id" in deepclust
    realign = next(call for call in calls if "realign" in call)
    fields_start = -len(REALIGN_FIELDS) - 2
    assert realign[fields_start:-2] == list(REALIGN_FIELDS)
    assert json.loads(result["subcluster_settings.json"].read_text())["input_sequences"] == 3


def test_alignment_denominators_reference_positions_and_unknowns(tmp_path):
    """Statistics use canonical comparable positions and one-based reference coordinates."""
    path = tmp_path / "msa.fasta"
    path.write_text(">ref\nAC-X\n>member\nADDX\n")
    result = alignment_statistics(
        alignment=path, reference_id="ref", maximum_cells=8, output=tmp_path
    )
    members = pd.read_csv(result["alignment_members.tsv"], sep="\t").set_index("sequence_id")
    assert members.loc["member", "comparable_residue_count"] == 2
    assert members.loc["member", "identity_to_reference_fraction"] == 0.5
    assert members.loc["member", "reference_overlap_fraction"] == 1
    columns = pd.read_csv(result["alignment_columns.tsv"], sep="\t")
    assert columns.loc[2, "gap_fraction"] == 0.5
    assert pd.isna(columns.loc[2, "reference_position"])
    assert pd.isna(columns.loc[3, "consensus_residue"])
    with pytest.raises(ResearchError, match="size bound"):
        alignment_statistics(alignment=path, reference_id="ref", maximum_cells=7, output=tmp_path)
    for text in (">a\nACD\n>b\nAC\n", ">a\nACD\n>a\nACD\n", ""):
        path.write_text(text)
        with pytest.raises(ResearchError):
            alignment_statistics(
                alignment=path, reference_id="a", maximum_cells=100, output=tmp_path
            )


def test_auspice_has_real_divergence_and_no_fabricated_dates():
    """Actual branch lengths and reviewed traits are preserved in v2 JSON."""
    value = auspice_dataset(
        newick="(a:0.1,(b:0.2,c:0.3):0.1);",
        metadata={"a": {"species": "Human", "taxon_id": 9606}},
        title="Family",
    )
    assert value["version"] == "v2"
    assert value["tree"]["children"][0]["node_attrs"]["div"] == 0.1
    assert value["tree"]["children"][0]["node_attrs"]["species"]["value"] == "Human"
    assert "num_date" not in json.dumps(value)
    for newick in ("(a:-0.1,b:0.1);", "(a:0.1,a:0.2);", "(a:0.1,):0.2;"):
        with pytest.raises(ResearchError):
            auspice_dataset(newick=newick, metadata={}, title="Bad")


def test_alignment_selection_sampling_and_sequence_integrity(
    research_config, protein_fasta, tmp_path, monkeypatch
):
    """Sampling is explicit and retains the reference; tools may not alter the proteins."""
    calls = []

    def fake_command(*, arguments, output, config, stdout=None):
        calls.append(arguments)
        if "--version" in arguments:
            stdout.write_text("MAFFT v7\n")
        elif "--auto" in arguments:
            stdout.write_text(Path(arguments[-1]).read_text())
        elif "-wag" in arguments:
            stdout.write_text("(a:0.1,b:0.1,c:0.2);\n")

    monkeypatch.setattr(analysis, "run_command", fake_command)
    output = tmp_path / "full"
    output.mkdir()
    result = align_family(
        config=research_config,
        source=protein_fasta,
        output=output,
        parameters={"reference_id": "b"},
    )
    assert (
        "auspice.json" in result
        and list(dict(iter_fasta(path=result["sequences.fasta"])))[0] == "b"
    )
    selection = pd.read_csv(result["selection.tsv"], sep="\t")
    assert selection.loc[0, "sampling"] == "ALL_SELECTED"
    sample = tmp_path / "sample"
    sample.mkdir()
    result = align_family(
        config=research_config,
        source=protein_fasta,
        output=sample,
        parameters={"sample_size": 2, "allow_sampling": True, "reference_id": "c"},
    )
    assert len(dict(iter_fasta(path=result["sequences.fasta"]))) == 2
    assert "c" in dict(iter_fasta(path=result["sequences.fasta"]))
    assert "tree.nwk" not in result
    for i, parameters in enumerate(
        ({"sample_size": 2}, {"reference_id": "missing"}, {"subcluster_id": "missing"})
    ):
        directory = tmp_path / f"invalid{i}"
        directory.mkdir()
        with pytest.raises(ResearchError):
            align_family(
                config=research_config,
                source=protein_fasta,
                output=directory,
                parameters=parameters,
            )

    def changed_command(*, arguments, output, config, stdout=None):
        stdout.write_text(
            "changed"
            if "--version" in arguments
            else ">a\nAAAAAAAAAAAAAAAAAAAA\n>b\nACDEFGHIKLMNPQRSTVWY\n>c\nACDEFGHIKLMNPQRSTVWF\n"
        )

    monkeypatch.setattr(analysis, "run_command", changed_command)
    directory = tmp_path / "changed"
    directory.mkdir()
    with pytest.raises(ResearchError, match="changed a selected protein"):
        align_family(config=research_config, source=protein_fasta, output=directory, parameters={})


def test_single_family_selection_and_empty_native_alignments(
    research_config, protein_fasta, tmp_path, monkeypatch
):
    """Singleton families stay analysable and absent realignments preserve all members."""
    membership = tmp_path / "audited.tsv"
    membership.write_text("subcluster_id\tsequence_id\none\ta\nother\tb\nother\tc\n")

    def fake_command(*, arguments, output, config, stdout=None):
        if "--version" in arguments:
            stdout.write_text("v7\n")
        else:
            stdout.write_text(Path(arguments[-1]).read_text())

    monkeypatch.setattr(analysis, "run_command", fake_command)
    output = tmp_path / "single"
    output.mkdir()
    result = align_family(
        config=research_config,
        source=protein_fasta,
        output=output,
        parameters={"subcluster_id": "one"},
        membership=membership,
    )
    assert dict(iter_fasta(path=result["alignment.fasta"])) == {"a": "ACDEFGHIKLMNPQRSTVWY"}
    output = tmp_path / "absent"
    output.mkdir()
    with pytest.raises(ResearchError, match="No proteins"):
        align_family(
            config=research_config,
            source=protein_fasta,
            output=output,
            parameters={"subcluster_id": "absent"},
            membership=membership,
        )
    output = tmp_path / "oversize"
    output.mkdir()
    with pytest.raises(ResearchError, match="matrix size"):
        align_family(
            config=replace(research_config, max_alignment_cells=1),
            source=protein_fasta,
            output=output,
            parameters={},
        )
    native, realign, inputs = [tmp_path / name for name in ("n.tsv", "r.tsv", "i.tsv")]
    native.write_text("representative\tmember\na\ta\na\tb\n")
    realign.touch()
    inputs.write_text("sequence_id\na\nb\n")
    result = audit_subclusters(
        membership=native,
        realignments=realign,
        source_ids=inputs,
        output=tmp_path,
        identity=70,
        coverage=80,
        evalue=1e-10,
        config=research_config,
    )
    table = pd.read_csv(result["membership.tsv"], sep="\t")
    assert table.subcluster_id.nunique() == 2


def test_tree_invalid_branches_tip_collision_support_and_depth():
    """Portable phylogeny JSON rejects unusable trees and keeps genuine support values."""
    value = auspice_dataset(newick="(INTERNAL_1:0.1,b:0.2)90:0.0;", metadata={}, title="Supported")
    assert value["tree"]["name"] != "INTERNAL_1"
    assert value["tree"]["node_attrs"]["local_support"]["value"] == 90
    deep = "(" * 402 + "a:0.1,b:0.2" + ")" * 402 + ";"
    with pytest.raises(ResearchError, match="nesting"):
        auspice_dataset(newick=deep, metadata={}, title="Too deep")
    with pytest.raises(ResearchError):
        auspice_dataset(newick="((a,b);", metadata={}, title="Malformed")


def test_exact_identity_uses_counts_instead_of_rounded_percent(research_config, tmp_path):
    """Rounded pident cannot promote a member across a strict identity cutoff."""
    membership, exact, inputs = [tmp_path / name for name in ("native.tsv", "exact.tsv", "ids.tsv")]
    membership.write_text("centroid\tmember\na\ta\na\tb\n")
    inputs.write_text("sequence_id\na\nb\n")
    exact.write_text("a\tb\t70.0\t10000\t10000\t1\t10000\t1\t10000\t10000\t1e-20\t100\t6999\n")
    result = audit_subclusters(
        membership=membership,
        realignments=exact,
        source_ids=inputs,
        output=tmp_path,
        identity=70,
        coverage=80,
        evalue=1e-10,
        config=research_config,
    )
    frame = pd.read_csv(result["membership.tsv"], sep="\t").set_index("sequence_id")
    assert frame.loc["b", "pident"] == pytest.approx(69.99)
    assert frame.loc["b", "alignment_status"] == "EXACT_THRESHOLDS_FAIL"
    assert frame.loc["b", "audited_representative_id"] == "b"
