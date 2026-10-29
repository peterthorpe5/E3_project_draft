"""External hand-offs preserve saved identities, sequences, ranks and transforms."""

import copy
import hashlib
import io
import json
import zipfile
from urllib.parse import parse_qs, urlparse

import gemmi
import numpy as np
import pytest

from pocket_workbench import external_tools
from pocket_workbench.core import WorkbenchError, load_project
from pocket_workbench.external_tools import (
    RESIDUE_COLUMNS,
    bundle_model_file,
    canonical_uniprot,
    emerald_pair_url,
    external_records,
    fasta_record,
    model_file,
    pair_fasta,
    pocket_tables,
    prepare_external_bundle,
    public_model_links,
    record_sequence,
    table_tsv,
)
from pocket_workbench.external_ui import selection_signature


@pytest.mark.parametrize("value", ["P38398", "q9h9q2", " A0A023GPI8 "])
def test_canonical_accessions_produce_only_explicit_database_links(value):
    """Supported complete UniProt accessions are encoded into documented routes."""
    accession = value.strip().upper()
    assert canonical_uniprot(value=value) == accession
    links = public_model_links(accession=value)
    assert links["alphafold"] == f"https://alphafold.ebi.ac.uk/entry/{accession}"
    assert parse_qs(urlparse(links["molstar"]).query) == {"afdb": [accession]}


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        123,
        "",
        "NP_001394510",
        "XP_001394510",
        "P38398-2",
        "fold_P38398_19102026_model_0",
        "sp|P38398|BRCA1_HUMAN",
        "../P38398",
    ],
)
def test_accession_links_never_strip_isoforms_or_extract_a_guess(value):
    """RefSeq, local names and embedded accessions retain their manual-file route."""
    assert canonical_uniprot(value=value) is None
    assert public_model_links(accession=value) == {"molstar": None, "alphafold": None}
    assert emerald_pair_url(first=value, second="P38398") is None


def test_emerald_url_keeps_pair_roles_and_parameters():
    """The pre-filled link has the selected order and no local sequence/path payload."""
    url = emerald_pair_url(first="P38398", second="P51587", alpha=0.8, delta=16)
    assert parse_qs(urlparse(url).query) == {
        "seqA": ["P38398"],
        "seqB": ["P51587"],
        "alpha": ["0.8"],
        "delta": ["16"],
    }
    assert emerald_pair_url(first="P38398", second="P38398") is None


@pytest.mark.parametrize(
    ("alpha", "delta"),
    [
        (True, 8),
        (float("nan"), 8),
        (float("inf"), 8),
        (-0.1, 8),
        (1.1, 8),
        ("0.75", 8),
        (0.75, True),
        (0.75, 8.0),
        (0.75, -1),
        (0.75, 101),
    ],
)
def test_emerald_rejects_invalid_numeric_options(alpha, delta):
    """Invalid ranges and truth values cannot enter an apparently valid link."""
    with pytest.raises(WorkbenchError):
        emerald_pair_url(first="P38398", second="P51587", alpha=alpha, delta=delta)


def test_inventory_keeps_replicates_fasta_only_and_explicit_source_identity(project):
    """Groups cannot borrow FASTA-only rows or silently replace source accessions."""
    data = load_project(root=project)
    data["models"][0].update(source_accession="P38398")
    data["models"][1].update(source_accession="NP_000000", sequence_id="P51587")
    data["sequences"]["P04637"] = "ACDEFG"
    original = copy.deepcopy(data)
    records = external_records(data=data)
    by_id = {r["record_id"]: r for r in records}
    assert len(records) == 5  # Original now-unrepresented FASTA plus the added record.
    assert (
        by_id["model:" + data["models"][0]["sample_id"]]["canonical_accession"]
        == "P38398"
    )
    assert (
        by_id["model:" + data["models"][1]["sample_id"]]["canonical_accession"] is None
    )
    assert by_id["sequence:P04637"]["coordinates_available"] is False
    assert len(external_records(data=data, group="synthetic")) == 3
    assert external_records(data=data, group="absent_group") == []
    assert data == original


def test_pair_fasta_distinguishes_cropped_inputs_from_full_representatives(project):
    """The download's two exact sequences follow the explicitly chosen input scope."""
    data = load_project(root=project)
    record = next(m for m in data["models"] if m["sample_id"] == "synthetic_reference")
    full = record["sequence"]
    record.update(
        sequence=full[4:16],
        input_scope="cleaned_region",
        original_start=5,
        original_end=16,
    )
    ids = {"first": "model:synthetic_reference", "second": "model:synthetic_mobile"}
    local = pair_fasta(data=data, **ids, scope="model_input").decode()
    representative = pair_fasta(data=data, **ids, scope="representative_fasta").decode()
    assert local.splitlines()[1] == full[4:16]
    assert representative.splitlines()[1] == full
    assert "input_scope=cleaned_region" in local.splitlines()[0]
    assert "scope=representative_fasta" in representative.splitlines()[0]
    assert local.count(">") == 2
    reverse = pair_fasta(
        data=data, first=ids["second"], second=ids["first"], scope="model_input"
    ).decode()
    assert "synthetic_mobile" in reverse.splitlines()[0]
    data["sequences"]["FASTA_only"] = "MNPQRSTVWY"
    assert (
        "MNPQRSTVWY" in pair_fasta(
            data=data,
            first=ids["first"],
            second="sequence:FASTA_only",
            scope="model_input",
        ).decode()
    )
    with pytest.raises(WorkbenchError):
        pair_fasta(
            data=data, first=ids["first"], second=ids["first"], scope="model_input"
        )
    with pytest.raises(WorkbenchError):
        pair_fasta(data=data, first=ids["first"], second="unknown", scope="model_input")


def test_sequence_exports_reject_missing_invalid_or_substituted_inputs(project):
    """Missing model-input sequence never falls back to its full parent FASTA."""
    record = external_records(data=load_project(root=project))[0]
    record["input_sequence"] = None
    with pytest.raises(WorkbenchError, match="No exact"):
        record_sequence(record=record, scope="model_input")
    assert record_sequence(record=record, scope="representative_fasta")[0]
    record["input_sequence"] = "ACD-*"
    with pytest.raises(WorkbenchError, match="Invalid"):
        record_sequence(record=record, scope="model_input")
    with pytest.raises(WorkbenchError, match="Choose"):
        record_sequence(record=record, scope="guess")
    record.update(
        input_sequence="ACD", record_id="model:local\n>bad", sequence_id="seq\tother"
    )
    assert (
        fasta_record(record=record, scope="model_input", role="first").count(">") == 1
    )


def test_complete_model_download_preserves_atoms_and_prepared_residue_labels(
    project, monkeypatch
):
    """PDB is the saved file and mmCIF retains all atoms, not only a CA rendering."""
    data = load_project(root=project)
    model = data["models"][0]
    original = (project / model["prepared_model"]).read_bytes()
    assert model_file(root=project, model=model, file_format="pdb") == original
    cif = model_file(root=project, model=model)
    structure = gemmi.make_structure_from_block(
        gemmi.cif.read_string(cif.decode()).sole_block()
    )
    assert structure[0].count_atom_sites() == 128
    assert structure[0][0][1].seqid.num == 2
    with pytest.raises(WorkbenchError):
        model_file(root=project, model={}, file_format="cif")
    with pytest.raises(WorkbenchError):
        model_file(root=project, model=model, file_format="csv")
    with pytest.raises(WorkbenchError):
        model_file(root=project, model=dict(model, prepared_model="../outside.pdb"))
    monkeypatch.setattr(external_tools, "MAX_MODEL_BYTES", 10)
    with pytest.raises(WorkbenchError, match="64 MiB"):
        model_file(root=project, model=model)


def test_pocket_tsv_uses_exact_tool_author_and_fasta_labels_without_rank_changes(
    project,
):
    """An unmapped lining residue is retained as unknown, never guessed from its ID."""
    data = load_project(root=project)
    model = data["models"][0]
    pocket = next(p for p in data["pockets"] if p["sample_id"] == model["sample_id"])
    pocket.update(review_rank=3, quality_screen_pass=False, near_cut_boundary=True)
    pocket["residues"].append("A_99999")
    path = project / model["coordinates"]
    coordinates = json.loads(path.read_text())
    coordinates[1].update(
        author_chain="Z", author_residue_number=115, insertion_code="A"
    )
    path.write_text(json.dumps(coordinates))
    tables = pocket_tables(root=project, data=data, model_ids=[model["sample_id"]])
    mapped = next(r for r in tables["residues"] if r["residue_key"] == "A_2")
    assert (mapped["tool_chain"], mapped["tool_residue_number"]) == ("A", 2)
    assert (
        mapped["author_chain"],
        mapped["author_residue_number"],
        mapped["insertion_code"],
    ) == ("Z", 115, "A")
    assert mapped["review_rank"] == 3 and mapped["quality_screen_pass"] is False
    missing = next(r for r in tables["residues"] if r["residue_key"] == "A_99999")
    assert (
        missing["mapping_status"] == "unmapped"
        and missing["tool_residue_number"] is None
    )
    content = table_tsv(rows=tables["residues"], columns=RESIDUE_COLUMNS).decode()
    assert "\t" in content.splitlines()[0]
    assert table_tsv(rows=[], columns=("a", "b")) == b"a\tb\n"
    with pytest.raises(WorkbenchError):
        pocket_tables(root=project, data=data, model_ids=["unknown"])


def test_saved_alignment_bundle_reuses_exact_transform_and_leaves_project_unchanged(
    project,
):
    """The exported mobile is already fitted, and every audited file hash matches."""
    data = load_project(root=project)
    comparison = data["comparisons"][0]
    result = json.loads((project / comparison["result_path"]).read_text())
    before = {
        p.relative_to(project): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in project.rglob("*")
        if p.is_file()
    }
    bundle = prepare_external_bundle(
        root=project,
        data=data,
        model_ids=["synthetic_mobile", "synthetic_reference"],
        comparison_id=comparison["comparison_id"],
    )
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        audit = json.loads(archive.read("handoff.json"))
        assert audit["coordinate_frame"] == "saved_alignment"
        assert audit["model_ids"] == ["synthetic_reference", "synthetic_mobile"]
        assert (
            audit["analysis_recomputed"] is False and audit["automatic_upload"] is False
        )
        assert {
            "pockets.tsv",
            "pocket_residues.tsv",
            "model_inputs.fasta",
            "saved_comparison.json",
            "sequence_audit.tsv",
        } <= set(archive.namelist())
        for name, expected in audit["file_sha256"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected
        assert archive.read("model_inputs.fasta").count(b">") == 2
        assert not any(n.endswith(".csv") for n in archive.namelist())
    content, filename = bundle_model_file(bundle=bundle, sample_id="synthetic_mobile")
    assert filename == "workbench_model_1.cif"
    actual = gemmi.make_structure_from_block(
        gemmi.cif.read_string(content.decode()).sole_block()
    )
    expected = gemmi.read_structure(str(project / result["mobile_aligned"]))
    a, b = actual[0][0][1]["CA"][0].pos, expected[0][0][1]["CA"][0].pos
    assert np.allclose([a.x, a.y, a.z], [b.x, b.y, b.z])
    assert before == {
        p.relative_to(project): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in project.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize("ids", [[], ["missing"], ["synthetic_reference"] * 2])
def test_invalid_bundle_model_selections_fail_before_preparation(project, ids):
    """Empty, duplicate or absent model selections cannot produce a misleading ZIP."""
    with pytest.raises(WorkbenchError):
        prepare_external_bundle(
            root=project, data=load_project(root=project), model_ids=ids
        )


def test_independent_bundle_and_missing_or_wrong_saved_alignment(project):
    """Independent coordinates are labelled explicitly and cannot borrow another fit."""
    data = load_project(root=project)
    bundle = prepare_external_bundle(
        root=project, data=data, model_ids=["synthetic_reference"]
    )
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert (
            json.loads(archive.read("handoff.json"))["coordinate_frame"]
            == "original_prepared_models"
        )
    for comparison_id in ["missing_fit", data["comparisons"][0]["comparison_id"]]:
        with pytest.raises(WorkbenchError):
            prepare_external_bundle(
                root=project,
                data=data,
                model_ids=["synthetic_reference", "synthetic_variant"],
                comparison_id=comparison_id,
            )
    for model in data["models"]:
        model["prepared_model"] = ""
    with pytest.raises(WorkbenchError, match="no saved atomic"):
        prepare_external_bundle(
            root=project, data=data, model_ids=["synthetic_reference"]
        )


def test_bundle_model_hash_verification_rejects_tampered_or_missing_files(project):
    """The individual-download path verifies its model against the ZIP audit."""
    bundle = prepare_external_bundle(
        root=project, data=load_project(root=project), model_ids=["synthetic_reference"]
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bundle)) as original, zipfile.ZipFile(
        stream, "w"
    ) as changed:
        for name in original.namelist():
            changed.writestr(
                name,
                b"tampered" if name == "workbench_model_0.cif" else original.read(name),
            )
    with pytest.raises(WorkbenchError, match="differs"):
        bundle_model_file(bundle=stream.getvalue(), sample_id="synthetic_reference")
    with pytest.raises(WorkbenchError):
        bundle_model_file(bundle=bundle, sample_id="missing")
    with pytest.raises(WorkbenchError):
        bundle_model_file(bundle=b"not a ZIP", sample_id="synthetic_reference")


def test_prepared_download_signature_changes_with_selection_frame_and_source_files(
    project,
):
    """A previous download cannot stay labelled as the newly chosen inputs."""
    data = load_project(root=project)
    kwargs = dict(
        root=project,
        data=data,
        model_ids=["synthetic_reference", "synthetic_mobile"],
        comparison_id=None,
    )
    first = selection_signature(**kwargs)
    assert selection_signature(**kwargs) == first
    assert (
        selection_signature(
            **dict(kwargs, comparison_id=data["comparisons"][0]["comparison_id"])
        )
        != first
    )
    assert selection_signature(**dict(kwargs, model_ids=["synthetic_variant"])) != first
    (project / "project.json").write_text((project / "project.json").read_text() + "\n")
    assert selection_signature(**kwargs) != first
