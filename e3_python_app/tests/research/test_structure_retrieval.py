"""Check public accession identity, model parsing and both retrieval workflows."""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import parse_qs
from zipfile import ZipFile

import duckdb
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from e3app.alphafold_hog_bundle import AlphaFoldBundleRecord, AlphaFoldHogBundle
from e3app.errors import AppError
from e3app.navigation import CANDIDATE_STAGE
from e3app.research import retrieval_ui, sequence_retrieval
from e3app.research.common import ResearchError
from e3app.research.linked_features import monomer_view_payload
from e3app.research.providers import mmcif_evidence
from e3app.research.sequence_retrieval import ProteinSequence, fetch_protein_sequence
from e3app.research.sequence_retrieval import sequence_lookup_target


@pytest.mark.parametrize(("value", "expected"), [
    (" ref|NP_000001.2| ", ("NCBI Protein", "NP_000001.2")),
    ("gi|123|ref|NP_000001.2|", ("NCBI Protein", "NP_000001.2")),
    ("ABC1234567.1", ("NCBI Protein", "ABC1234567.1")),
    ("sp|Q9SA03|FB27_ARATH", ("UniProt", "Q9SA03")),
    ("P38398-2", ("UniProt", "P38398-2")),
    ("AT3G12200.1", None), ("Q9SA03-0", None), ("NP_000001.0", None),
    ("WP_123456789.1 and others", None), ("http://example.org", None), ("", None),
])
def test_only_exact_protein_identifiers_are_routed(*, value, expected):
    """Keep accession versions and isoforms, with explicit namespaces for FASTA IDs."""
    assert sequence_lookup_target(identifier=value) == expected


def test_ncbi_and_uniprot_fetch_preserve_returned_accession(*, monkeypatch):
    """Issue bounded requests for accession data only and check the returned identity."""
    responses = iter((b">ref|NP_000001.2| description\nMSTN\n",
                      b">sp|P38398-2|description\nMAAAN\n"))
    calls = []

    def http(**kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(sequence_retrieval, "http_request", http)
    monkeypatch.setattr(sequence_retrieval, "_NCBI_NEXT_REQUEST", 0)
    monkeypatch.setattr(sequence_retrieval, "monotonic", lambda: 100.0)
    monkeypatch.setenv("E3_NCBI_EMAIL", "test@example.org")
    result = fetch_protein_sequence(identifier="NP_000001")
    assert result == ProteinSequence(accession="NP_000001.2", sequence="MSTN",
                                     source="NCBI Protein")
    assert calls[0]["method"] == "POST"
    assert parse_qs(calls[0]["body"].decode()) == {
        "db": ["protein"], "id": ["NP_000001"], "rettype": ["fasta"], "retmode": ["text"],
        "tool": ["e3_python_app"], "email": ["test@example.org"],
    }
    result = fetch_protein_sequence(identifier="P38398-2")
    assert result.accession == "P38398-2" and result.sequence == "MAAAN"
    assert calls[1]["url"] == sequence_retrieval.UNIPROT_FASTA + "P38398-2.fasta"
    with pytest.raises(AppError, match="Wait a moment"):
        fetch_protein_sequence(identifier="NP_000002")
    assert len(calls) == 2


@pytest.mark.parametrize(("accession", "response"), [
    ("NP_000001.2", b">NP_000001.3\nACD\n"),
    ("P38398-2", b">sp|P38398|canonical\nACD\n"),
    ("P38398", b">P38398\nACD\n>Q9SA03\nACD\n"),
    ("P38398", b">P38398\nA---C\n"),
    ("P38398", b"\xff"),
    ("P38398", b""),
])
def test_invalid_or_unrelated_public_fasta_is_rejected(*, accession, response, monkeypatch):
    """Prevent wrong records, changed versions and malformed results entering an alignment."""
    monkeypatch.setattr(sequence_retrieval, "http_request", lambda **kwargs: response)
    monkeypatch.setattr(sequence_retrieval, "_NCBI_NEXT_REQUEST", 0)
    with pytest.raises(AppError, match=f"Could not retrieve {accession}"):
        fetch_protein_sequence(identifier=accession)


def _model_cif(*, sequence: tuple[str, ...], position_offset: int = 0) -> bytes:
    """Write a minimal C-alpha mmCIF using standard author and label identifiers."""
    fields = (
        "group_PDB", "id", "type_symbol", "label_atom_id", "label_alt_id", "label_comp_id",
        "label_asym_id", "label_seq_id", "pdbx_PDB_ins_code", "Cartn_x", "Cartn_y", "Cartn_z",
        "occupancy", "B_iso_or_equiv", "auth_seq_id", "auth_asym_id", "pdbx_PDB_model_num",
    )
    header = "data_test\nloop_\n" + "\n".join(f"_atom_site.{field}" for field in fields)
    body = "\n".join(
        f"ATOM {index} C CA . {residue} A {index + position_offset} ? "
        f"{index}.0 0 0 1.00 82.0 {index} A 1"
        for index, residue in enumerate(sequence, start=1)
    )
    return f"{header}\n{body}\n#\n".encode()


def test_mmcif_trace_checks_sequence_order_and_confidence():
    """Use the label axis and decline mismatched or incomplete coordinate models."""
    model = _model_cif(sequence=("ALA", "CYS"))
    records = mmcif_evidence(cif=model, expected_sequence="AC")
    assert [record["residue"] for record in records] == ["A", "C"]
    payload = monomer_view_payload(residues=pd.DataFrame(records[::-1]))
    assert payload["sequence"] == "AC"
    assert [item["position"] for item in payload["model"]] == [1, 2]
    assert payload["model"][0]["plddt"] == 82
    assert mmcif_evidence(cif=model, expected_sequence=None) == records
    for malformed, expected in (
        (model, "AD"), (_model_cif(sequence=("ALA",), position_offset=1), None),
        (b"", None), (b"\xff", None), (b"data_test", None),
    ):
        with pytest.raises(ResearchError):
            mmcif_evidence(cif=malformed, expected_sequence=expected)
    for corrupt in (
        pd.DataFrame(), pd.DataFrame(records).assign(chain_id=["A", "B"]),
        pd.DataFrame(records).assign(confidence_b_factor=101),
        pd.DataFrame(records).assign(residue_index=[1, 3]),
        pd.DataFrame(records).assign(x=float("inf")),
    ):
        with pytest.raises(ResearchError):
            monomer_view_payload(residues=corrupt)


def _app(*, resource_db, monkeypatch, tmp_path, page):
    """Start the candidate discovery surface with an isolated research workspace."""
    profile = tmp_path / "research.toml"
    profile.write_text(f"workspace={json.dumps(str(tmp_path / 'research'))}\n", encoding="utf-8")
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(profile))
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    script = Path(__file__).parents[2] / "src/e3app/streamlit_app.py"
    app = AppTest.from_file(str(script), default_timeout=25).run()
    app.radio(key="e3_navigation_stage").set_value(CANDIDATE_STAGE).run()
    return app.radio(key=f"e3_navigation_page_{CANDIDATE_STAGE}").set_value(page).run()


def test_missing_ncbi_sequence_can_enter_a_hog_alignment(*, resource_db, monkeypatch, tmp_path):
    """Fetch one missing accession, keep its provenance and queue the reviewed input."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "UPDATE hierarchical_membership SET raw_identifier='ref|NP_000001.2|' "
            "WHERE species='Homo_sapiens'"
        )
    requests = []

    def fetch(*, identifier):
        requests.append(identifier)
        return ProteinSequence(accession=identifier, sequence="MAAAN", source="NCBI Protein")

    monkeypatch.setattr(retrieval_ui, "fetch_protein_sequence", fetch)
    app = _app(
        resource_db=resource_db, monkeypatch=monkeypatch, tmp_path=tmp_path, page="JBrowse MSA",
    )
    app.selectbox(key="msa_hog_selector").set_value("N0.HOG0001").run()
    assert not requests
    app.button(key="msa_hog_fetch_sequence").click().run()
    assert requests == ["NP_000001.2"]
    assert any(button.label == "Download retrieved FASTA" for button in app.get("download_button"))
    app.button(key="msa_queue_alignment").click().run()
    job = next((tmp_path / "research" / "jobs").iterdir())
    parameters = json.loads((job / "request.json").read_text())["parameters"]
    assert list(parameters["e3_retrieved_sequences"].values()) == [
        {"accession": "NP_000001.2", "source": "NCBI Protein"},
    ]
    assert "MAAAN" in (job / "input.fasta").read_text()
    assert not app.exception and not app.error


def test_retrieved_alphafold_model_opens_in_feature_browser(*, resource_db, monkeypatch, tmp_path):
    """Reuse the AlphaFold downloader and inspect a verified current model without a review."""
    model = _model_cif(sequence=("MET", "SER", "THR", "ASN", "PRO", "LYS", "PRO", "ASN"))
    calls = []

    def prepare(*, hog_id, accessions, include_pae):
        calls.append((hog_id, accessions, include_pae))
        output = BytesIO()
        with ZipFile(output, mode="w") as archive:
            archive.writestr(f"e3_{hog_id}_model_0.cif", model)
        return AlphaFoldHogBundle(payload=output.getvalue(), records=(AlphaFoldBundleRecord(
            model_index=0, accession=accessions[0], species="Arabidopsis_thaliana",
            status="included",
            model_url="https://alphafold.ebi.ac.uk/files/AF-Q9SA03-F1-model_v6.cif",
            model_bytes=len(model), model_sha256=sha256(model).hexdigest(),
            pae_status="not_requested", pae_url="", detail="",
        ),))

    monkeypatch.setattr(retrieval_ui, "build_alphafold_hog_bundle", prepare)
    app = _app(resource_db=resource_db, monkeypatch=monkeypatch, tmp_path=tmp_path,
               page="Protein feature browser")
    app.selectbox(key="recorded_feature_hog_picker").set_value("N0.HOG0001").run()
    app.selectbox(key="recorded_feature_hog_protein_N0.HOG0001").set_value(
        ("Q9SA03", "N0.HOG0001", "Arabidopsis_thaliana", "sp|Q9SA03|FB27_ARATH"),
    ).run()
    app.radio(key="recorded_feature_view").set_value("Linked structure and pockets").run()
    assert not calls and not app.get("iframe")
    app.button(key="linked_protein_fetch_alphafold").click().run()
    assert calls == [("N0.HOG0001", ["Q9SA03"], False)]
    document = app.get("iframe")[0].proto.srcdoc
    assert '"sequence": "MSTNPKPN"' in document and "Download 3D view (PDF)" in document
    assert any(button.label == "Download AlphaFold model (mmCIF)"
               for button in app.get("download_button"))
    assert not app.exception and not app.error


def test_hog_alignment_offers_only_members_without_a_published_model(
    *, resource_db, monkeypatch, tmp_path,
):
    """Check the configured model inventory and the shared alignment retrieval form."""
    root = tmp_path / "review"
    (root / "tables").mkdir(parents=True)
    inventory = root / "tables" / "protein_model_inventory.tsv"
    inventory.write_text(
        "primary_group_id\tcandidate_accession\tspecies_column\tmodel_status\n"
        "N0.HOG0001\tQ9SA03\tArabidopsis_thaliana\tMODEL_AVAILABLE\n"
        "N0.HOG0001\tP38398\tHomo_sapiens\tMODEL_UNAVAILABLE\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("E3_POCKET_REVIEW_DIR", str(root))
    app = _app(
        resource_db=resource_db, monkeypatch=monkeypatch, tmp_path=tmp_path, page="JBrowse MSA",
    )
    app.selectbox(key="msa_hog_selector").set_value("N0.HOG0001").run()
    options = app.selectbox(key="msa_hog_alphafold_member").options
    assert len(options) == 1 and options[0].startswith("P38398")
    assert not app.exception and not app.error
