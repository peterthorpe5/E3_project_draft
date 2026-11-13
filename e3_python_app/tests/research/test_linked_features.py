"""Verify the exact joins between an E3 release, its pocket review and Nightingale."""

from hashlib import md5, sha256
import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from e3app.config import AppConfig
from e3app.errors import AppError
from e3app.external_hog import released_member_sequence
from e3app.navigation import CANDIDATE_STAGE
from e3app.research.common import ResearchError, atomic_json, file_sha256
from e3app.research.jobs import claim_job, finish_job, job_directory, submit_job
from e3app.research.linked_features import (
    linked_domain_features,
    linked_review_evidence,
    model_residues,
    read_group_evidence,
)

HOG = "N0.HOG0001"
ACCESSION = "Q9SA03"
SPECIES = "Arabidopsis_thaliana"
RAW_ID = "sp|Q9SA03|FB27_ARATH"
SEQUENCE = "MSTNPKPN"
PAGE = "groups/example.html"


@pytest.fixture
def linked_review(*, tmp_path):
    """Create a small portable report with discontinuous pockets and missing pLDDT."""
    root = tmp_path / "pocket_review"
    (root / "tables").mkdir(parents=True)
    (root / "groups").mkdir()
    (root / "tables" / "review_report_index.tsv").write_text(
        f"primary_group_id\tgroup_review_html\n{HOG}\t{PAGE}\n", encoding="utf-8",
    )
    atoms = [
        {"chain": "A", "resi": str(i), "resn": residue, "x": i, "y": 2, "z": 3,
         "plddt": None if i == 3 else 81.4, "pockets": []}
        for i, residue in enumerate(
            ["MET", "SER", "THR", "ASN", "PRO", "LYS", "PRO", "ASN"], start=1,
        )
    ]
    annotations = []
    for position in (2, 5, 6):
        annotations.append({
            "fasta_position": position, "fasta_residue": SEQUENCE[position - 1],
            "structure_label_chain": "A", "structure_label_seq_id": str(position),
            "selection_rank": 1, "pocket_number": 7,
        })
    for position in (2, 5):
        atoms[position - 1]["pockets"] = [{"selection_rank": 1, "pocket_number": 7}]
    group = {
        "group_key": {"primary_group_id": HOG},
        "proteins": [{
            "accession": ACCESSION, "species": SPECIES, "atoms": atoms, "model_sha256": "a" * 64,
        }],
        "alignment": {"records": [{
            "accession": ACCESSION, "species": SPECIES, "sequence": "MS-TNPKPN",
            "pocket_annotations": annotations,
        }]},
    }
    write_group(root=root, group=group)
    return root, group


def write_group(*, root: Path, group: dict) -> None:
    """Write the same inert JSON contract used by the pocket-review exporter."""
    (root / PAGE).write_text(
        '<script id="reviewData" type="application/json">' + json.dumps(group) + "</script>"
        '<script>throw new Error("the report code must not be embedded");</script>',
        encoding="utf-8",
    )


def test_pocket_review_requires_exact_member_and_residue_matches(*, linked_review):
    """Link only mapped pocket residues with confirmed C-alpha locations."""
    root, group = linked_review
    config = AppConfig(pocket_review_dir=root)
    values = {"config": config, "accession": ACCESSION, "group_id": HOG, "species": SPECIES}
    evidence = linked_review_evidence(**values, sequence=SEQUENCE)
    assert evidence["sequence"] == SEQUENCE
    assert evidence["pockets"][0]["positions"] == [2, 5]
    assert evidence["model"][2]["plddt"] is None
    assert evidence["model"][1]["position"] == 2 and evidence["model"][1]["plddt"] == 81.4
    assert evidence["model_sha256"] == "a" * 64
    assert linked_review_evidence(**values, sequence="ASTNPKPN") is None
    assert linked_review_evidence(
        **{**values, "species": "Homo_sapiens"}, sequence=SEQUENCE,
    ) is None
    assert read_group_evidence(review_dir=root, group_id="unknown") is None
    group["alignment"]["records"][0]["pocket_annotations"][0]["structure_label_seq_id"] = "3"
    write_group(root=root, group=group)
    evidence = linked_review_evidence(**values, sequence=SEQUENCE)
    assert evidence["pockets"][0]["positions"] == [5]


def test_linked_view_can_use_the_other_review(*, linked_review, tmp_path):
    """An unusable plant review cannot hide a valid human-and-plant entry."""
    root, _ = linked_review
    invalid = tmp_path / "old_review"
    (invalid / "tables").mkdir(parents=True)
    (invalid / "tables" / "review_report_index.tsv").write_text(
        f"primary_group_id\tgroup_review_html\n{HOG}\t{PAGE}\n", encoding="utf-8",
    )
    evidence = linked_review_evidence(
        config=AppConfig(pocket_review_dir=invalid, human_plant_review_dir=root),
        accession=ACCESSION, group_id=HOG, species=SPECIES, sequence=SEQUENCE,
    )
    assert evidence["model_source"] == root.name


@pytest.mark.parametrize("failure", ["traversal", "group", "script"])
def test_review_payload_rejects_mismatched_or_uncontained_group(*, linked_review, failure):
    """Read one contained inert data block belonging to the selected group."""
    root, group = linked_review
    if failure == "traversal":
        (root / "tables" / "review_report_index.tsv").write_text(
            f"primary_group_id\tgroup_review_html\n{HOG}\t../unrelated.html\n", encoding="utf-8",
        )
    elif failure == "group":
        group["group_key"]["primary_group_id"] = "WRONG"
        write_group(root=root, group=group)
    else:
        (root / PAGE).write_text("<script id='reviewData'>{}</script>", encoding="utf-8")
    with pytest.raises(AppError):
        read_group_evidence(review_dir=root, group_id=HOG)


@pytest.mark.parametrize(
    "override",
    [{"resi": "1A"}, {"resn": "SER"}, {"plddt": 101}, {"x": float("inf")}, {"chain": "B"}],
)
def test_structure_rejects_ambiguous_or_incompatible_coordinates(*, linked_review, override):
    """A sequence match alone cannot validate erroneous or mixed-chain structure rows."""
    _, group = linked_review
    atoms = group["proteins"][0]["atoms"]
    atoms[0].update(override)
    with pytest.raises(ResearchError):
        model_residues(atoms=atoms, sequence=SEQUENCE)


def test_linked_domain_coordinates_preserve_sequence_evidence():
    """Label same-length historical intervals and omit conflicting sequence evidence."""
    values = {
        "member_accession": ACCESSION, "primary_group_id": HOG, "species_column": SPECIES,
        "entry_accession": "PF_TEST", "entry_name": "Test domain", "location_start": 2,
        "location_end": 5, "protein_length": len(SEQUENCE), "source_database": "pfam",
    }
    sha = sha256(SEQUENCE.encode()).hexdigest()
    digest = md5(SEQUENCE.encode(), usedforsecurity=False).hexdigest()
    rows = pd.DataFrame([
        {**values, "entry_accession": "PF_LEGACY"},
        {**values, "entry_accession": "PF_LEGACY"},
        {**values, "entry_accession": "PF_WRONG", "sequence_sha256": "a" * 64},
        {**values, "entry_accession": "PF_CONFLICT", "sequence_sha256": sha,
         "sequence_md5": "b" * 32},
        {**values, "entry_accession": "PF_LENGTH", "sequence_sha256": sha, "protein_length": 9},
        {**values, "entry_accession": "PF_MD5", "sequence_md5": digest},
        {**values, "entry_accession": "PF_BAD_START", "location_start": 2.5},
        {**values, "entry_accession": "PF_BAD_END", "location_end": 9},
        {**values, "entry_accession": "PF_LEGACY", "location_start": 6, "location_end": 7},
        values,
        {**values, "sequence_sha256": sha},
    ])
    features = linked_domain_features(rows=rows, sequence=SEQUENCE)
    assert [(item["accession"], item["provenance"]) for item in features] == [
        ("PF_MD5", "sequence_verified"), ("PF_TEST", "sequence_verified"),
        ("PF_LEGACY", "recorded_coordinates"), ("PF_LEGACY", "recorded_coordinates"),
    ]
    assert linked_domain_features(rows=pd.DataFrame(), sequence=SEQUENCE) == []
    assert linked_domain_features(rows=rows, sequence="MST") == []


def test_exact_worker_hit_replaces_only_the_same_domain_interval():
    """Preserve separate recorded intervals when one domain gains exact-sequence evidence."""
    base = {"member_accession": ACCESSION, "primary_group_id": HOG, "species_column": SPECIES,
            "entry_accession": "PF_TEST", "entry_name": "Test domain", "protein_length": 8,
            "location_start": 2, "location_end": 5}
    exact = [{"accession": "PF_TEST", "description": "Verified domain", "color": "#5852a3",
              "locations": [{"fragments": [{"start": 2, "end": 5}]}]}]
    rows = pd.DataFrame([base, {**base, "location_start": 6, "location_end": 8}])
    features = linked_domain_features(rows=rows, sequence=SEQUENCE, annotations=exact)
    assert len(features) == 2
    assert features[0]["provenance"] == "sequence_verified"
    assert features[1]["provenance"] == "recorded_coordinates"
    assert features[1]["locations"][0]["fragments"] == [{"start": 6, "end": 8}]


def test_linked_view_uses_release_and_existing_annotation_jobs(
    *, resource_db, linked_review, tmp_path, monkeypatch,
):
    """Display both historical coordinates and exact worker hits in the linked view."""
    root, _ = linked_review
    workspace = tmp_path / "research"
    profile = tmp_path / "research.toml"
    profile.write_text(f"workspace={json.dumps(str(workspace))}\n", encoding="utf-8")
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(profile))
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    monkeypatch.setenv("E3_POCKET_REVIEW_DIR", str(root))
    with duckdb.connect(database=str(resource_db)) as connection:
        assert released_member_sequence(
            connection=connection, hog_id=HOG, species=SPECIES, raw_identifier=RAW_ID,
        ) == SEQUENCE
        assert released_member_sequence(
            connection=connection, hog_id=HOG, species="Wrong_species", raw_identifier=RAW_ID,
        ) == ""
        connection.execute(
            "CREATE TABLE domain_hits AS SELECT ? AS member_accession, ? AS primary_group_id, "
            "? AS species_column, ? AS raw_identifier, 8 AS protein_length, "
            "2 AS location_start, 6 AS location_end, 'PF_LEGACY' AS entry_accession, "
            "'Recorded legacy domain' AS entry_name",
            [ACCESSION, HOG, SPECIES, RAW_ID],
        )
    job = submit_job(workspace=workspace, operation="annotate", parameters={})
    claim_job(workspace=workspace, job_id=job)
    directory = job_directory(workspace=workspace, job_id=job)
    annotations = directory / "annotations.tsv"
    digest = sha256(SEQUENCE.encode()).hexdigest()
    annotations.write_text(
        "sequence_id\tsequence_sha256\tstart\tend\tsignature_accession\tdescription\n"
        f"original_job_id\t{digest}\t2\t5\tPF_EXACT\tVerified domain\n"
        f"another_id\t{'0' * 64}\t2\t5\tPF_WRONG\tDifferent sequence\n", encoding="utf-8",
    )
    atomic_json(path=directory / "manifest.json", value={
        "job_id": job, "operation": "annotate", "artifacts": {
            "annotations.tsv": {"path": annotations.name, "sha256": file_sha256(path=annotations)},
        },
    })
    finish_job(workspace=workspace, job_id=job)

    script = Path(__file__).parents[2] / "src/e3app/streamlit_app.py"
    app = AppTest.from_file(str(script), default_timeout=30).run()
    app.radio(key="e3_navigation_stage").set_value(CANDIDATE_STAGE).run()
    page = app.radio(key=f"e3_navigation_page_{CANDIDATE_STAGE}")
    page.set_value("Protein feature browser").run()
    app.selectbox(key="recorded_feature_hog_picker").set_value(HOG).run()
    app.selectbox(key=f"recorded_feature_hog_protein_{HOG}").set_value(
        (ACCESSION, HOG, SPECIES, RAW_ID),
    ).run()
    assert "PF_LEGACY" in app.get("iframe")[0].proto.srcdoc
    app.radio(key="recorded_feature_view").set_value("Linked structure and pockets").run()
    document = app.get("iframe")[0].proto.srcdoc
    assert '"positions": [2, 5]' in document
    assert "PF_LEGACY" in document and '"provenance": "recorded_coordinates"' in document
    assert "Verified sequence axis" in document
    app.selectbox(key="linked_annotation_job").set_value(job).run()
    document = app.get("iframe")[0].proto.srcdoc
    assert "PF_EXACT" in document and "PF_WRONG" not in document
    assert '"provenance": "sequence_verified"' in document
    assert "PF_LEGACY" in document
    assert not app.exception and not app.error

    app.selectbox(key="linked_annotation_job").set_value(None).run()
    app.button(key="linked_feature_annotate").click().run()
    assert app.radio(key="research_section").value == "Annotations"
    assert app.radio(key="annotate_route").value == "Prepared FASTA"
    assert app.session_state["research_prepared_fasta"][1] == f">{ACCESSION}\n{SEQUENCE}\n"
