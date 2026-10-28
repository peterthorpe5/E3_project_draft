"""Scientific provenance, coordinate preservation and usability of pocket upload exports."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO, StringIO
import json
from pathlib import Path
from zipfile import ZipFile

from Bio.PDB import MMCIFParser
from Bio.PDB.MMCIF2Dict import MMCIF2Dict
import pandas as pd
import pytest

from e3app.errors import AppError
from e3app.pocket_review import load_pocket_review
from e3app.protein_imager import prepare_protein_imager_data
from e3app.protein_imager_pockets import (
    PocketSource, export_recorded_pockets, load_pocket_source,
)
from test_pocket_review import make_pocket_review


def original_cif() -> bytes:
    """Return an atomistic model with author numbering different from label numbering."""
    return b"""data_original
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.B_iso_or_equiv
_atom_site.auth_seq_id
_atom_site.auth_asym_id
_atom_site.auth_comp_id
_atom_site.auth_atom_id
_atom_site.pdbx_PDB_model_num
ATOM 1 N N . ALA A 1 1 ? -1 0 0 1.0 81 101 X ALA N 1
ATOM 2 C CA . ALA A 1 1 ? 0 0 0 1.0 81 101 X ALA CA 1
ATOM 3 C CB . ALA A 1 1 ? 0 1 0 1.0 81 101 X ALA CB 1
ATOM 4 N N . GLY A 1 2 ? 1 0 0 1.0 91 102 X GLY N 1
ATOM 5 C CA . GLY A 1 2 ? 2 0 0 1.0 91 102 X GLY CA 1
ATOM 6 C C . GLY A 1 2 ? 3 0 0 1.0 91 102 X GLY C 1
ATOM 7 C CA . VAL A 1 3 ? 4 0 0 1.0 71 103 X VAL CA 1
ATOM 8 C CB . VAL A 1 3 ? 4 1 0 1.0 71 103 X VAL CB 1
#
"""


def pocket_source() -> PocketSource:
    """Create realistic recorded report evidence with overlapping pockets and a missing member."""
    pockets = [
        {"selection_rank": 1, "pocket_number": 7, "druggability_score": 0.75,
         "mapping_fraction": 1.0, "pocket_plddt_fraction": 0.9,
         "predictor_agreement": True, "structural_evidence_status": "ASSESSED"},
        {"selection_rank": 2, "pocket_number": 2, "druggability_score": 0.55,
         "mapping_fraction": 0.8, "pocket_plddt_fraction": 0.7,
         "predictor_agreement": False, "structural_evidence_status": "SENSITIVITY"},
    ]
    atoms = [
        {"chain": "A", "resi": 1, "resn": "ALA", "x": 0, "y": 0, "z": 0,
         "plddt": 81, "pockets": [{"selection_rank": 1, "pocket_number": 7}]},
        {"chain": "A", "resi": 2, "resn": "GLY", "x": 2, "y": 0, "z": 0,
         "plddt": 91, "pockets": [{"selection_rank": 1, "pocket_number": 7},
                                  {"selection_rank": 2, "pocket_number": 2}]},
        {"chain": "A", "resi": 3, "resn": "VAL", "x": 4, "y": 0, "z": 0,
         "plddt": 71, "pockets": [{"selection_rank": 2, "pocket_number": 2}]},
    ]
    return PocketSource(
        group_id="N0.HOG1", document_sha256="a" * 64,
        proteins=(
            {"accession": "Q9SA03", "model_sha256": sha256(original_cif()).hexdigest(),
             "atoms": atoms, "pockets": pockets},
            {"accession": "P38398", "atoms": [], "pockets": pockets[:1]},
        ),
    )


def make_pocket_report(*, parent: Path, group_id: str = "N0.HOG1") -> Path:
    """Add the real embedded-data contract to the existing portable review fixture."""
    root = make_pocket_review(parent)
    for path in root.rglob("*.tsv"):
        path.write_text(path.read_text().replace("P1", "Q9SA03").replace("P2", "P38398"))
        frame = pd.read_csv(path, sep="\t")
        if "primary_group_id" in frame.columns:
            frame["primary_group_id"] = group_id
            frame.to_csv(path, sep="\t", index=False)
    for path in list(root.rglob("*P1*")):
        if path.is_file():
            path.rename(path.with_name(path.name.replace("P1", "Q9SA03").replace("P2", "P38398")))
    source = pocket_source()
    payload = {"review_rank": 1, "group_key": {
        "primary_group_id": group_id, "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
        "cluster_id": "cluster_1",
    }, "proteins": source.proteins}
    page = next((root / "groups").iterdir())
    page.write_text(
        '<html><script type="application/json" id="reviewData">'
        + json.dumps(payload) + "</script></html>", encoding="utf-8",
    )
    return root


def test_original_model_exports_all_pocket_atoms_without_renumbering_or_moving() -> None:
    """Exact original bytes permit full-atom residue subsets with overlapping pocket membership."""
    result = export_recorded_pockets(
        source=pocket_source(), accessions=("Q9SA03",), models=(original_cif(),),
    )
    assert result.audit[0]["representation"] == "original_model_checksum_verified"
    assert result.audit[0]["exported_pockets"] == 2
    assert len(result.files) == 3
    for file, expected_count, expected_author_ids in zip(
        result.files, (8, 6, 5), ({"101", "102", "103"}, {"101", "102"}, {"102", "103"}),
        strict=True,
    ):
        structure = MMCIFParser(QUIET=True).get_structure("test", StringIO(file.data.decode()))
        assert len(list(structure.get_atoms())) == expected_count
        data = MMCIF2Dict(StringIO(file.data.decode()))
        assert set(data["_atom_site.auth_seq_id"]) == expected_author_ids
        assert data["_atom_site.auth_asym_id"] == ["X"] * expected_count
        assert data["_atom_site.label_asym_id"] == ["A"] * expected_count
    pocket_atoms = MMCIF2Dict(StringIO(result.files[1].data.decode()))
    assert pocket_atoms["_atom_site.Cartn_x"] == ["-1", "0", "0", "1", "2", "3"]
    assert "CB" in pocket_atoms["_atom_site.label_atom_id"]
    scores = pd.read_csv(BytesIO(result.tables["pocket_scores.tsv"]), sep="\t")
    assert scores["pocket_number"].tolist() == [7, 2]
    assert scores["druggability_score"].tolist() == [0.75, 0.55]
    residues = pd.read_csv(BytesIO(result.tables["pocket_residues.tsv"]), sep="\t")
    assert residues["residue_id"].tolist() == [1, 2, 2, 3]
    assert residues["recorded_plddt"].tolist() == [81, 91, 91, 71]


def test_newer_model_cannot_receive_historical_pockets_and_fallback_is_explicit() -> None:
    """A one-byte model difference forbids the atomistic route and exports labelled original CA."""
    result = export_recorded_pockets(
        source=pocket_source(), accessions=("Q9SA03", "P38398", "P12345"),
        models=(original_cif() + b"# newer version\n",),
    )
    assert [row["representation"] for row in result.audit] == [
        "CA_trace_only", "no_recorded_coordinates", "not_recorded",
    ]
    assert all("CA_only" in file.filename for file in result.files)
    for file, count in zip(result.files, (3, 2, 2), strict=True):
        parsed = MMCIF2Dict(StringIO(file.data.decode()))
        assert parsed["_atom_site.label_atom_id"] == ["CA"] * count
        assert parsed["_atom_site.B_iso_or_equiv"] == ["0.00"] * count
        assert len(list(MMCIFParser(QUIET=True).get_structure(
            "test", StringIO(file.data.decode()),
        ).get_atoms())) == count


@pytest.mark.parametrize("field,value", (
    ("x", 10), ("x", float("nan")), ("resn", "GLY"), ("chain", "B"),
))
def test_original_hash_alone_cannot_override_inconsistent_report_geometry(
    *, field: str, value: object,
) -> None:
    """Even checksum-matched models must agree with the report's complete original trace."""
    source = pocket_source()
    source.proteins[0]["atoms"][0][field] = value
    with pytest.raises(AppError):
        export_recorded_pockets(source=source, accessions=("Q9SA03",), models=(original_cif(),))


@pytest.mark.parametrize("mutation", (
    "duplicate_atom", "unknown_pocket", "duplicate_pocket", "bad_rank", "empty_locator",
    "bad_residue",
))
def test_invalid_pocket_evidence_never_produces_a_misleading_upload(*, mutation: str) -> None:
    """Ambiguous geometry, membership or ranks fail instead of guessing."""
    source = pocket_source()
    protein = source.proteins[0]
    if mutation == "duplicate_atom":
        protein["atoms"].append(deepcopy(protein["atoms"][0]))
    elif mutation == "unknown_pocket":
        protein["atoms"][0]["pockets"][0]["pocket_number"] = 99
    elif mutation == "duplicate_pocket":
        protein["pockets"].append(deepcopy(protein["pockets"][0]))
    elif mutation == "bad_rank":
        protein["pockets"][0]["selection_rank"] = 1.5
    elif mutation == "empty_locator":
        protein["atoms"][0]["chain"] = "?"
    else:
        protein["atoms"][0]["resi"] = "1A"
    with pytest.raises(AppError):
        export_recorded_pockets(source=source, accessions=("Q9SA03",))


def test_unmapped_pockets_keep_their_scores_and_explicit_counts() -> None:
    """A retained pocket without mapped geometry is not silently presented as exported."""
    source = pocket_source()
    for atom in source.proteins[0]["atoms"]:
        atom["pockets"] = [item for item in atom["pockets"] if item["selection_rank"] == 1]
    result = export_recorded_pockets(source=source, accessions=("Q9SA03",))
    assert result.audit[0]["recorded_pockets"] == 2
    assert result.audit[0]["exported_pockets"] == 1
    assert len(pd.read_csv(BytesIO(result.tables["pocket_scores.tsv"]), sep="\t")) == 2


def test_pocket_package_and_individual_files_are_auditable_when_database_model_is_missing() -> None:
    """The original-model upload route works even when the current provider has no model."""
    def reader(url, limit):
        """Return an empty AlphaFold metadata response without downloading another model."""
        assert "/api/prediction/" in url
        return b"[]"

    data = prepare_protein_imager_data(
        group_id="N0.HOG1", accessions=("Q9SA03",), reader=reader,
        pocket_source=pocket_source(), original_models=(original_cif(),),
    )
    assert not data.files and len(data.pocket_files) == 3
    with ZipFile(BytesIO(data.payload)) as archive:
        assert archive.testzip() is None
        for file in data.pocket_files:
            assert archive.read("pockets/" + file.filename) == file.data
        manifest = pd.read_csv(BytesIO(archive.read("pocket_files.tsv")), sep="\t")
        for row in manifest.to_dict(orient="records"):
            assert sha256(archive.read(row["upload_file"])).hexdigest() == row["sha256"]
        readme = archive.read("README.txt").decode()
        assert "RECORDED POCKETS INCLUDED" in readme and "without separate alignment" in readme
        assert "side-chain" in readme and "not read by the external viewer" in readme
    with pytest.raises(AppError, match="group does not match"):
        prepare_protein_imager_data(
            group_id="N0.HOG2", accessions=("Q9SA03",), pocket_source=pocket_source(),
            reader=lambda *args: pytest.fail("Must fail before retrieval"),
        )
    one = prepare_protein_imager_data(
        group_id="Q9SA03", accessions=("Q9SA03",), reader=reader, pocket_source=pocket_source(),
    )
    assert one.pocket_files


def test_indexed_pocket_source_load_and_legacy_missing_data(*, tmp_path: Path) -> None:
    """Only the selected indexed group supplies evidence, and legacy pages are explicit."""
    root = make_pocket_report(parent=tmp_path)
    bundle = load_pocket_review(root)
    page = str(bundle.index.iloc[0]["group_review_html"])
    source = load_pocket_source(bundle=bundle, group_page=page)
    assert source.group_id == "N0.HOG1"
    document = root.joinpath(page).read_text()
    assert source.document_sha256 == sha256(document.encode()).hexdigest()
    for wrong in (document.replace("N0.HOG1", "N0.HOG2"),
                  document.replace('"review_rank": 1', '"review_rank": 2'),
                  '<script id="reviewData">invalid</script>',
                  '<script id="reviewData">{}</script>' * 2):
        root.joinpath(page).write_text(wrong)
        with pytest.raises(AppError, match="Invalid recorded"):
            load_pocket_source(bundle=bundle, group_page=page)
    root.joinpath(page).write_text("<html>legacy</html>")
    assert load_pocket_source(bundle=bundle, group_page=page) is None


def test_input_and_output_bounds_are_enforced(*, monkeypatch: pytest.MonkeyPatch) -> None:
    """Oversized original inputs and generated bundles fail within the documented budget."""
    monkeypatch.setattr("e3app.protein_imager_pockets.MAX_BUNDLE_BYTES", 1)
    with pytest.raises(AppError, match="inputs exceed"):
        export_recorded_pockets(source=pocket_source(), accessions=("Q9SA03",), models=(b"ab",))
    with pytest.raises(AppError, match="upload files exceed"):
        export_recorded_pockets(source=pocket_source(), accessions=("Q9SA03",))


def test_current_model_is_eligible_only_when_its_exact_original_checksum_matches() -> None:
    """A matching current download needs no separate upload, while new bytes use CA-only data."""
    def reader(url, limit):
        """Serve a valid complete matching current mmCIF and its approved model reference."""
        if "/api/prediction/" in url:
            return json.dumps([{
                "uniprotAccession": "Q9SA03",
                "cifUrl": "https://alphafold.ebi.ac.uk/files/AF-Q9SA03-F1-model_v6.cif",
            }]).encode()
        return original_cif()

    prepared = prepare_protein_imager_data(
        group_id="N0.HOG1", accessions=("Q9SA03",), reader=reader, pocket_source=pocket_source(),
    )
    assert len(prepared.files) == 1
    assert prepared.pocket_audit[0]["representation"] == "original_model_checksum_verified"
    assert len(prepared.pocket_files) == 3
    with ZipFile(BytesIO(prepared.payload)) as archive:
        assert archive.read("models/Q9SA03.cif") == original_cif()


def test_pocket_expansion_is_bounded_while_building_the_upload_files(
    *, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop as soon as pocket subsets exceed the budget, even when the protein trace fits."""
    reference = export_recorded_pockets(source=pocket_source(), accessions=("Q9SA03",))
    budget = len(reference.files[0].data) + len(reference.files[1].data) - 1
    monkeypatch.setattr("e3app.protein_imager_pockets.MAX_BUNDLE_BYTES", budget)
    with pytest.raises(AppError, match="Pocket upload files exceed"):
        export_recorded_pockets(source=pocket_source(), accessions=("Q9SA03",))
