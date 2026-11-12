"""Subclustering execution across app-host and configured VM worker paths."""

from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
from xml.etree import ElementTree as ET

import pandas as pd
import pytest

from e3app.research.analysis import subcluster
from e3app.research.common import ResearchConfig, ResearchError, atomic_json, file_sha256
from e3app.research.guidance import job_label
from e3app.research.hog_context import hog_input_parameters
from e3app.research.jobs import artifact_path, claim_job, finish_job, get_job, job_directory
from e3app.research.jobs import submit_job
from e3app.research.local_worker import start_queued_subcluster, submit_local_subcluster
from e3app.research.subcluster_network import (
    MAX_NODES,
    load_network_members,
    network_edges,
    network_figure,
    network_graphml,
)
from e3app.research.subcluster_remote import write_vm_subclusters

FASTA = (
    ">a\nACDEFGHIKLMNPQRSTVWY\n>b\nACDEFGHIKLMNPQRSTVWF\n"
    ">c\nACDEFGHIKLMNPQHDFVRN\n>d\nMGKETVLYRDFLHKQCLTEA\n"
)
FAKE_DIAMOND = r'''
import os
from pathlib import Path
import sys

command, *args = sys.argv[1:]
if command == "version":
    print("diamond version " + os.environ.get("E3_TEST_DIAMOND_VERSION", "2.2.8"))
elif command == "makedb":
    assert Path(args[args.index("--in") + 1]).read_text().startswith(">a\n")
    Path(args[args.index("--db") + 1] + ".dmnd").touch()
else:
    assert Path(args[args.index("--db") + 1]).is_file()
    target = Path(args[args.index("--out") + 1])
    if command == "deepclust":
        assert args[args.index("--id") + 1] == "90.0"
        assert args[args.index("--mutual-cover") + 1] == "80.0"
        assert "--header" in args
        target.write_text("centroid\tmember\na\ta\na\tb\na\tc\nd\td\n")
    else:
        assert command == "realign"
        pairs = Path(args[args.index("--clusters") + 1]).read_text()
        assert pairs == "a\ta\na\tb\na\tc\nd\td\n"
        target.write_text(
            "a\tb\t95\t20\t20\t1\t20\t1\t20\t20\t1e-15\t55\t19\n"
            "a\tc\t70\t20\t20\t1\t20\t1\t20\t20\t1e-12\t40\t14\n"
        )
'''
FAKE_SSH = r'''
import os
import shlex
import sys

assert sys.argv[-2] == "e3-fixture"
remote = shlex.split(sys.argv[-1])
assert remote[-2:] == ["run-subcluster", "--request-stdin"]
os.execv(remote[0], remote)
'''


@pytest.fixture
def subcluster_tools(*, tmp_path, monkeypatch):
    """Install isolated DIAMOND and SSH executables for real worker subprocess tests.

    Args:
        tmp_path: Private test directory.
        monkeypatch: Scoped executable path update.

    Returns:
        DIAMOND executable and VM CLI paths.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, program in {
        "diamond": FAKE_DIAMOND, "ssh": FAKE_SSH,
        "remote-e3": "from e3app.research.cli import main\nraise SystemExit(main())\n",
    }.items():
        executable = bin_dir / name
        executable.write_text(f"#!{sys.executable}\n{program}", encoding="utf-8")
        executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    return bin_dir / "diamond", bin_dir / "remote-e3"


@pytest.mark.parametrize("route", ["local", "saved", "vm"])
def test_subclustering_workers_build_database_and_publish_audited_network(
    *, route, tmp_path, monkeypatch, subcluster_tools,
):
    """Run the actual one-shot CLI and verify the native pipeline on both routes."""
    diamond, remote_cli = subcluster_tools
    workspace = tmp_path / "app_jobs"
    vm_profile = tmp_path / "vm.toml"
    vm_workspace = tmp_path / "vm_jobs"
    vm_profile.write_text(
        f"workspace={json.dumps(str(vm_workspace))}\ndiamond={json.dumps(str(diamond))}\n",
        encoding="utf-8",
    )
    profile = tmp_path / "app.toml"
    settings = {
        "workspace": str(workspace),
        "diamond": str(tmp_path / "unavailable") if route == "vm" else str(diamond),
        "remote_host": "e3-fixture", "remote_config": str(vm_profile),
        "remote_executable": str(remote_cli),
    }
    profile.write_text(
        "".join(f"{key}={json.dumps(value)}\n" for key, value in settings.items()),
        encoding="utf-8",
    )
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(profile))
    config = ResearchConfig(**{**settings, "workspace": workspace})
    unrelated = submit_job(workspace=workspace, operation="align", parameters={}, fasta=FASTA)
    thresholds = {"identity": 90, "mutual_coverage": 80, "evalue": 1e-10}
    hog = hog_input_parameters(
        hog_id="N0.HOG0000390", members=pd.DataFrame({
            "fasta_identifier": ["a", "b", "c", "d"],
            "member_species": [
                "Hordeum_vulgare", "Hordeum_vulgare", "Physcomitrella_patens", "Glycine_max",
            ],
        }),
    )
    if route == "saved":
        job_id = submit_job(
            workspace=workspace, operation="subcluster", parameters=thresholds, fasta=FASTA,
        )
        start_queued_subcluster(config=config, job_id=job_id)
    elif route == "vm":
        source_job = submit_job(workspace=workspace, operation="align", parameters={}, fasta=FASTA)
        claim_job(workspace=workspace, job_id=source_job)
        prior = job_directory(workspace=workspace, job_id=source_job)
        source = prior / "sequences.fasta"
        source.write_text(FASTA, encoding="utf-8")
        atomic_json(path=prior / "manifest.json", value={
            "parameters": hog,
            "artifacts": {
                "sequences.fasta": {"path": source.name, "sha256": file_sha256(path=source)},
            },
        })
        finish_job(workspace=workspace, job_id=source_job)
        job_id = submit_local_subcluster(
            config=config, external_vm=True, fasta=None,
            parameters={**thresholds, "source_job": source_job, "source_artifact": source.name},
        )
    else:
        job_id = submit_local_subcluster(
            config=config, parameters={**thresholds, **hog}, fasta=FASTA,
        )
    deadline = time.monotonic() + 45
    job = get_job(workspace=workspace, job_id=job_id)
    while job["status"] in {"QUEUED", "RUNNING"} and time.monotonic() < deadline:
        time.sleep(0.05)
        job = get_job(workspace=workspace, job_id=job_id)
    directory = job_directory(workspace=workspace, job_id=job_id)
    assert job["status"] == "COMPLETE", (job, (directory / "local_worker.log").read_text())
    assert get_job(workspace=workspace, job_id=unrelated)["status"] == "QUEUED"
    if route != "saved":
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        assert job_label(job_id=job_id, record=manifest, workspace=workspace).startswith(
            "N0.HOG0000390 · "
        )
        metadata = pd.read_csv(artifact_path(
            workspace=workspace, job_id=job_id, artifact="member_taxonomy.tsv",
        ), sep="\t").set_index("sequence_id")
        assert metadata.loc["b", "taxon_id"] == 4513
        assert metadata.loc["c", "species"] == "Physcomitrella_patens"
        assert metadata.loc["c", "mapping_status"] == "RECORDED_SPECIES"
        counts = pd.read_csv(artifact_path(
            workspace=workspace, job_id=job_id, artifact="cluster_species.tsv",
        ), sep="\t")
        assert counts.set_index("species")["member_count"].to_dict() == {
            "Hordeum_vulgare": 2, "Physcomitrella_patens": 1, "Glycine_max": 1,
        }
    command_file = "vm_commands.jsonl" if route == "vm" else "commands.jsonl"
    path = artifact_path(workspace=workspace, job_id=job_id, artifact=command_file)
    commands = [json.loads(line)["argv"] for line in path.read_text().splitlines()]
    assert [arguments[1] for arguments in commands] == [
        "version", "makedb", "deepclust", "realign",
    ]
    makedb, cluster, realign = commands[1:]
    database = Path(makedb[makedb.index("--db") + 1] + ".dmnd")
    assert cluster[cluster.index("--db") + 1] == realign[realign.index("--db") + 1] == str(database)
    assert not database.exists()
    if route == "vm":
        assert (directory / "subcluster_ssh.log").is_file()
        assert not list(vm_workspace.glob("subcluster-ssh-*"))
    summary = pd.read_csv(directory / "subclusters.tsv", sep="\t")
    members = load_network_members(
        path=directory / "membership.parquet", subclusters=summary["subcluster_id"].tolist(),
    )
    assert members["role"].value_counts().to_dict() == {"Singleton": 2, "Centroid": 1, "Member": 1}
    assert network_edges(members=members)["sequence_id"].tolist() == ["b"]
    assert members.set_index("sequence_id").loc["c", "alignment_status"] == "EXACT_THRESHOLDS_FAIL"
    figure = network_figure(members=members)
    assert figure.layout.dragmode == "pan"
    assert "Exact identity 95.0%" in figure.data[2].hovertext[0]
    tree = ET.fromstring(network_graphml(members=members))
    nodes = tree.findall(".//{*}node")
    edges = tree.findall(".//{*}edge")
    assert len(nodes) == 4 and len(edges) == 1
    assert edges[0].find("{*}data[@key='pident']").text == "95.0"


def test_missing_and_older_diamond_have_actionable_errors(
    *, tmp_path, monkeypatch, subcluster_tools,
):
    """Explain tool availability or version errors before starting any clustering."""
    config = ResearchConfig(workspace=tmp_path / "jobs", diamond=str(tmp_path / "missing"))
    with pytest.raises(ResearchError, match="DIAMOND is unavailable on the app host"):
        submit_local_subcluster(config=config, parameters={}, fasta=FASTA)
    fasta = tmp_path / "input.fasta"
    fasta.write_text(FASTA, encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setenv("E3_TEST_DIAMOND_VERSION", "2.1.25")
    with pytest.raises(ResearchError, match=r"DIAMOND 2\.2\.1 or newer"):
        subcluster(
            config=replace(config, diamond=str(subcluster_tools[0])),
            source=fasta, output=output, parameters={},
        )
    assert not (output / "input.sqlite").exists()


@pytest.mark.parametrize(
    "problem, message",
    [("checksum", "checksum differs"), ("size", "transfer_max_bytes"),
     ("control", "audit thresholds")],
)
def test_vm_rejects_invalid_request(*, tmp_path, problem, message):
    """Reject unsafe controls, altered input and transfers beyond the VM limit."""
    raw = FASTA.encode()
    header = {"fasta_sha256": hashlib.sha256(raw).hexdigest(), "parameters": {}}
    config = ResearchConfig(workspace=tmp_path)
    if problem == "checksum":
        raw += b"\n"
    elif problem == "size":
        config = replace(config, transfer_max_bytes=1)
    else:
        header["parameters"]["workspace"] = str(tmp_path)
    with pytest.raises(ResearchError, match=message):
        write_vm_subclusters(
            config=config, source=io.BytesIO(json.dumps(header).encode() + b"\n" + raw),
            destination=io.BytesIO(),
        )


def test_network_preview_keeps_centroid_and_complete_group_size(*, tmp_path):
    """Bound the plot while keeping its central protein and reporting actual group size."""
    size = MAX_NODES + 10
    path = tmp_path / "membership.tsv"
    frame = pd.DataFrame({
        "sequence_id": [f"a_{index:03}" for index in range(size - 1)] + ["z_centroid"],
        "subcluster_id": "sub_A", "audited_representative_id": "z_centroid",
        "alignment_status": ["EXACT_THRESHOLDS_PASS"] * (size - 1) + ["CENTROID_SELF"],
        "pident": 95, "representative_coverage": 98, "member_coverage": 100,
        "evalue": 1e-20, "bitscore": 100,
    })
    frame.to_csv(path, sep="\t", index=False)
    members = load_network_members(path=path, subclusters=["sub_A"])
    assert len(members) == MAX_NODES and members.iloc[0]["sequence_id"] == "z_centroid"
    assert members["cluster_size"].unique().tolist() == [size]
    assert len(network_edges(members=members)) == MAX_NODES - 1
    with pytest.raises(ResearchError, match="distinct audited subclusters"):
        load_network_members(path=path, subclusters=["sub_A", "sub_A"])
    frame[["sequence_id", "subcluster_id"]].to_csv(path, sep="\t", index=False)
    with pytest.raises(ResearchError, match="lacks exact centroid audit fields"):
        load_network_members(path=path, subclusters=["sub_A"])
