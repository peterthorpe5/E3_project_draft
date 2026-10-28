"""Confidence preparation and complete batch reruns using labelled test evidence."""

import csv
import json
import os
import random
import shutil
import subprocess
from pathlib import Path

import duckdb
import gemmi
import numpy as np
import pytest
from openpyxl import load_workbook

from pocket_workbench import quality_rerun
from pocket_workbench.comparison import compare_pair
from pocket_workbench.core import (
    ComparisonSettings,
    WorkbenchError,
    digest_file,
    load_project,
)
from pocket_workbench.database import query_table, save_project
from pocket_workbench.importing import normalise_model
from pocket_workbench.quality import (
    CleaningSettings,
    find_pae_file,
    pocket_context,
    read_pae,
    select_regions,
    write_region_cif,
)
from pocket_workbench.quality_rerun import (
    discover_models,
    explicit_regions,
    main,
    plan_region_comparisons,
    prepare_inputs,
)


def residue_rows(scores):
    """Return deterministic CA positions and original labels for algorithm tests."""
    return [
        dict(
            plddt=float(score),
            xyz=[i * 3.8, 0, 0],
            residue_key=f"A_{i+1}",
            author_chain="B",
            author_residue_number=i + 101,
            insertion_code="",
            sequence_position=i + 1,
            model_position=i + 1,
            amino_acid="A",
        )
        for i, score in enumerate(scores)
    ]


@pytest.fixture
def raw_models(tmp_path):
    """Write two synthetic all-atom chains with two coherent confidence blocks."""
    source = tmp_path / "original_models"
    source.mkdir()
    sequences = {}
    generator = random.Random(42)
    base = "".join(generator.choice("ACDEFGHIKLMNPQRSTVWY") for _ in range(160))
    pae = np.full((160, 160), 25.0)
    pae[:60, :60] = 2
    pae[100:, 100:] = 2
    for replicate in range(2):
        sequence = base if replicate == 0 else "A" + base[1:]
        identifier = f"synthetic_model_{replicate}"
        sequences[f"sequence_{replicate}"] = sequence
        structure, model, chain = gemmi.Structure(), gemmi.Model("1"), gemmi.Chain("B")
        for index, aa in enumerate(sequence):
            residue = gemmi.Residue()
            residue.name = gemmi.expand_one_letter(aa, gemmi.ResidueKind.AA)
            residue.seqid = gemmi.SeqId(index + 101, " ")
            residue.het_flag = "A"
            point = np.array(
                [index * 1.8, np.sin(index * 0.6) * 5, np.cos(index * 0.6) * 5]
            )
            point += [replicate * 25, replicate * -12, replicate * 6]
            for name, offset in (
                ("N", [-0.7, 0, 0]),
                ("CA", [0, 0, 0]),
                ("C", [0.7, 0, 0]),
                ("O", [1, 0.5, 0]),
            ):
                atom = gemmi.Atom()
                atom.name, atom.element = name, gemmi.Element(name[0])
                atom.pos = gemmi.Position(*(point + offset))
                atom.b_iso, atom.occ = (90 if index < 60 or index >= 100 else 30), 1
                residue.add_atom(atom)
            chain.add_residue(residue)
        model.add_chain(chain)
        structure.add_model(model)
        structure.setup_entities()
        structure.make_mmcif_document().write_file(str(source / f"{identifier}.cif"))
        (source / f"synthetic_full_data_{replicate}.json").write_text(
            json.dumps(
                {
                    "pae": pae.tolist(),
                    "token_chain_ids": ["B"] * 160,
                }
            )
        )
    fasta = tmp_path / "representatives.fasta"
    sequences["unmodelled_representative"] = base[:-1] + (
        "A" if base[-1] != "A" else "C"
    )
    fasta.write_text("".join(f">{name}\n{seq}\n" for name, seq in sequences.items()))
    return source, fasta


@pytest.mark.parametrize(
    "options",
    [
        {"core_plddt": float("nan")},
        {"max_low_gap": True},
        {"min_core": 0},
        {"pae_fraction": 0},
        {"max_pae": -1},
        {"require_pae": "yes"},
    ],
)
def test_invalid_cleaning_settings(options):
    """Invalid thresholds fail before any input is written."""
    with pytest.raises(WorkbenchError):
        CleaningSettings(**options)


def test_contiguous_regions_keep_short_loops_and_do_not_stitch():
    """A 40-residue uncertain linker separates two independently retained regions."""
    rows = residue_rows([90] * 60 + [30] * 40 + [90] * 60)
    rows[25]["plddt"] = rows[26]["plddt"] = 45
    pae = np.full((160, 160), 25.0)
    pae[:60, :60] = pae[100:, 100:] = 2
    regions = select_regions(residues=rows, pae=pae, settings=CleaningSettings())
    assert [(r["model_start"], r["model_end"]) for r in regions] == [(1, 65), (96, 160)]
    assert all(r["status"] == "retained" for r in regions)
    assert regions[0]["residue_count"] == 65
    assert regions[0]["core_residues"] == 58
    assert regions[0]["artificial_c_terminus"]
    assert regions[1]["artificial_n_terminus"]
    assert regions[0]["end_index"] < regions[1]["start_index"]


def test_pae_splits_high_confidence_regions_and_missing_pae_is_explicit():
    """Confident local structure alone does not justify one rigid region."""
    rows = residue_rows([90] * 120)
    pae = np.full((120, 120), 25.0)
    pae[:60, :60] = pae[60:, 60:] = 2
    regions = select_regions(residues=rows, pae=pae, settings=CleaningSettings())
    assert [(r["model_start"], r["model_end"]) for r in regions] == [(1, 60), (61, 120)]
    rejected = select_regions(residues=rows, pae=None, settings=CleaningSettings())
    assert rejected[0]["reason"] == "pae_unassessed"
    allowed = select_regions(
        residues=rows, pae=None, settings=CleaningSettings(require_pae=False)
    )
    assert allowed[0]["status"] == "retained"
    screened = pocket_context(
        pocket={
            "residues": ["A_40"],
            "confidence_status": "meets_local_confidence_rule",
        },
        residues=rows,
        region=allowed[0],
        settings=CleaningSettings(),
    )
    assert screened["quality_screen_pass"] is False


def test_invalid_geometry_and_backbone_breaks_are_not_hidden():
    """Cuts and explicit rejections retain a broken-backbone reason."""
    rows = residue_rows([90] * 120)
    for row in rows[60:]:
        row["xyz"][0] += 20
    explicit = [dict(start_index=0, end_index=119, region_name="curated")]
    result = select_regions(
        residues=rows,
        pae=np.ones((120, 120)),
        settings=CleaningSettings(),
        explicit=explicit,
    )
    assert "backbone_gap" in result[0]["reason"]
    with pytest.raises(WorkbenchError, match="finite"):
        select_regions(
            residues=rows, pae=np.full((120, 120), np.nan), settings=CleaningSettings()
        )
    with pytest.raises(WorkbenchError, match="No residues"):
        select_regions(residues=[], pae=None, settings=CleaningSettings())


def test_pae_sidecars_reconcile_chain_tokens_and_reject_ambiguity(tmp_path):
    """Ligand/other-chain tokens cannot silently shift the selected chain matrix."""
    model = tmp_path / "job_model_0.cif"
    sidecar = tmp_path / "job_full_data_0.json"
    rows = residue_rows([90] * 3)
    matrix = np.arange(25).reshape(5, 5)
    sidecar.write_text(
        json.dumps(
            {
                "pae": matrix.tolist(),
                "token_chain_ids": ["X", "B", "B", "B", "X"],
            }
        )
    )
    assert find_pae_file(model_path=model) == sidecar
    selected, basis = read_pae(path=sidecar, residues=rows)
    assert np.array_equal(selected, matrix[1:4, 1:4])
    assert basis == "validated_selected_chain_token_order"
    rows[1]["author_residue_number"] += 10
    with pytest.raises(WorkbenchError, match="missing residues"):
        read_pae(path=sidecar, residues=rows)
    (tmp_path / "job_confidences_0.json").write_text("{}")
    with pytest.raises(WorkbenchError, match="Ambiguous"):
        find_pae_file(model_path=model)


def test_explicit_pae_ids_support_missing_residues_without_guessing(tmp_path):
    """Explicit selected-chain residue IDs permit safe non-contiguous token mapping."""
    rows = residue_rows([90] * 3)
    rows[1]["author_residue_number"] = 104
    rows[2]["author_residue_number"] = 107
    path = tmp_path / "pae.json"
    path.write_text(
        json.dumps(
            {
                "pae": np.ones((4, 4)).tolist(),
                "token_chain_ids": ["B"] * 4,
                "token_res_ids": [101, 104, 106, 107],
            }
        )
    )
    matrix, basis = read_pae(path=path, residues=rows)
    assert matrix.shape == (3, 3)
    assert basis == "explicit_chain_and_residue_tokens"
    rows[0]["insertion_code"] = "A"
    with pytest.raises(WorkbenchError, match="Insertion"):
        read_pae(path=path, residues=rows)


def test_cut_boundary_and_uncertain_context_screen_preserves_evidence():
    """CA distance flags screen interpretation without deleting a pocket."""
    rows = residue_rows([90] * 60)
    region = dict(
        artificial_n_terminus=True, artificial_c_terminus=False, pae_fraction=1.0
    )
    pocket = {"residues": ["A_2"], "confidence_status": "meets_local_confidence_rule"}
    flagged = pocket_context(
        pocket=pocket, residues=rows, region=region, settings=CleaningSettings()
    )
    assert flagged["near_cut_boundary"] and not flagged["quality_screen_pass"]
    pocket["residues"] = ["A_30"]
    clear = pocket_context(
        pocket=pocket, residues=rows, region=region, settings=CleaningSettings()
    )
    assert clear["quality_screen_pass"]
    rows[30]["plddt"] = 30
    uncertain = pocket_context(
        pocket=pocket, residues=rows, region=region, settings=CleaningSettings()
    )
    assert (
        uncertain["near_very_low_confidence"] and not uncertain["quality_screen_pass"]
    )
    pocket["residues"].append("A_999")
    assert not pocket_context(
        pocket=pocket, residues=rows, region=region, settings=CleaningSettings()
    )["quality_screen_pass"]


@pytest.mark.parametrize(
    "changes",
    [
        {"token_chain_ids": "BBB"},
        {"token_res_ids": [101, 102.5, 103]},
    ],
)
def test_invalid_token_identifiers_cannot_be_guessed(tmp_path, changes):
    """Malformed token arrays or fractional residue IDs fail reconciliation."""
    payload = dict(
        pae=np.ones((3, 3)).tolist(),
        token_chain_ids=["B"] * 3,
        token_res_ids=[101, 102, 103],
    )
    payload.update(changes)
    path = tmp_path / "bad_tokens.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(WorkbenchError):
        read_pae(path=path, residues=residue_rows([90] * 3))


def test_legacy_resources_without_quality_tables_remain_readable(project):
    """Additional optional tables do not force an old database rebuild."""
    from pocket_workbench.database import OPTIONAL_TABLES

    with duckdb.connect(str(project / "pocket_workbench.duckdb")) as database:
        for table in OPTIONAL_TABLES:
            database.execute(f'DROP TABLE "{table}"')
    before = digest_file(path=project / "pocket_workbench.duckdb")
    assert query_table(root=project, table="quality_models") == []
    assert query_table(root=project, table="models")
    assert digest_file(path=project / "pocket_workbench.duckdb") == before


def test_preparation_preserves_inputs_author_numbers_and_reports(raw_models, tmp_path):
    """A complete quality audit accompanies every retained original-numbered CIF."""
    source, fasta = raw_models
    paths = discover_models(directory=source)
    hashes = {str(p): digest_file(path=p) for p in source.iterdir()}
    root = tmp_path / "run"
    root.mkdir()
    result = prepare_inputs(
        paths=paths,
        root=root,
        fasta=fasta,
        mapping=None,
        regions_file=None,
        settings=CleaningSettings(),
        chain="",
    )
    assert len(result["regions"]) == 4
    assert all(row["status"] == "prepared" for row in result["model_qc"])
    assert hashes == {str(p): digest_file(path=p) for p in source.iterdir()}
    assert (root / "01_quality/index.html").is_file()
    book = load_workbook(root / "01_quality/quality_audit.xlsx")
    assert {"Model_QC", "Region_decisions", "Excluded_ranges"} <= set(book.sheetnames)
    first = next(iter(result["regions"]))
    chain = gemmi.read_structure(str(root / "02_cleaned_models" / f"{first}.cif"))[0][0]
    assert chain.name == "B" and chain[0].seqid.num == 101
    assert len(chain) == 65 and chain[-1].seqid.num == 165
    assert chain[0].find_atom("CA", "*").b_iso == 90
    assert chain[-1].find_atom("CA", "*").b_iso == 30
    rows, _ = normalise_model(
        source=source / "synthetic_model_0.cif",
        destination=tmp_path / "full.pdb",
        sample_id="parent",
        chain="",
        confidence="plddt",
    )
    with pytest.raises(WorkbenchError, match="bounds"):
        write_region_cif(
            prepared_pdb=tmp_path / "full.pdb",
            residues=rows,
            start=0,
            end=999,
            output=tmp_path / "invalid.cif",
        )


def test_derived_sequences_never_become_supplied_fasta_matches(raw_models, tmp_path):
    """Identical unmatched replicas keep an explicit unmapped-parent status."""
    source, _ = raw_models
    shutil.copyfile(source / "synthetic_model_0.cif", source / "synthetic_model_1.cif")
    root = tmp_path / "derived"
    root.mkdir()
    result = prepare_inputs(
        paths=discover_models(directory=source),
        root=root,
        fasta=None,
        mapping=None,
        regions_file=None,
        settings=CleaningSettings(),
        chain="",
    )
    assert {p["original_mapping_status"] for p in result["parents"].values()} == {
        "no_exact_fasta_match"
    }
    assert len({p["sequence_id"] for p in result["parents"].values()}) == 1


def test_preparation_carries_explicit_hog_and_source_metadata(raw_models, tmp_path):
    """Cropped model mappings retain supplied HOG/accession/external-source evidence."""
    source, fasta = raw_models
    mapping = tmp_path / "parent_mapping.tsv"
    mapping.write_text(
        "sample_id\tsequence_id\tchain\thog_id\tsource_accession\tsource_url\n"
        "synthetic_model_0\tsequence_0\tB\tHOG_TEST\tTEST_SOURCE\thttps://example.org/test\n"
    )
    root = tmp_path / "mapped"
    root.mkdir()
    result = prepare_inputs(
        paths=discover_models(directory=source),
        root=root,
        fasta=fasta,
        mapping=mapping,
        regions_file=None,
        settings=CleaningSettings(),
        chain="",
    )
    with Path(result["mapping"]).open() as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    explicit = [r for r in rows if r["sample_id"].startswith("synthetic_model_0")]
    assert len(explicit) == 2
    assert all(
        r["hog_id"] == "HOG_TEST" and r["source_url"] == "https://example.org/test"
        for r in explicit
    )


def test_curated_regions_validate_coordinates_and_overlap():
    """Curated ranges map through audited sequence positions and cannot overlap."""
    residues = residue_rows([90] * 120)
    parent = dict(
        sample_id="a", sequence_id="seq", original_mapping_status="exact_sequence"
    )
    records = [dict(sequence_id="seq", start="10", end="60", region_name="unit")]
    assert (
        explicit_regions(rows=records, parent=parent, residues=residues)[0][
            "start_index"
        ]
        == 9
    )
    with pytest.raises(WorkbenchError, match="overlap"):
        explicit_regions(rows=records * 2, parent=parent, residues=residues)
    parent["original_mapping_status"] = "no_exact_fasta_match"
    with pytest.raises(WorkbenchError, match="exact supplied"):
        explicit_regions(rows=records, parent=parent, residues=residues)
    records[0]["coordinate_system"] = "model"
    assert len(explicit_regions(rows=records, parent=parent, residues=residues)) == 1


def test_corresponding_regions_are_not_paired_by_ordinal_names():
    """One region per model is not enough to equate opposite protein ends."""
    sequence = "ACDEFGHIKLMNPQRSTVWY" * 8
    preparation = {
        "parents": {k: {"sequence": sequence} for k in ("a", "b", "c")},
        "regions": {
            "a1": dict(
                parent_sample_id="a",
                sequence_start=1,
                sequence_end=60,
                residue_count=60,
                mean_plddt=90,
                selection_source="automatic_confidence_candidate",
                region_name="candidate_001",
            ),
            "b1": dict(
                parent_sample_id="b",
                sequence_start=101,
                sequence_end=160,
                residue_count=60,
                mean_plddt=95,
                selection_source="automatic_confidence_candidate",
                region_name="candidate_001",
            ),
            "c1": dict(
                parent_sample_id="c",
                sequence_start=1,
                sequence_end=60,
                residue_count=60,
                mean_plddt=85,
                selection_source="automatic_confidence_candidate",
                region_name="candidate_002",
            ),
        },
    }
    pairs, groups, audit = plan_region_comparisons(
        preparation=preparation, mode="matched_reference"
    )
    assert pairs == [("a1", "c1")]
    assert groups["a1"] == groups["c1"] != groups["b1"]
    assert len(audit) == 3
    assert plan_region_comparisons(preparation=preparation, mode="matched_all")[0] == [
        ("a1", "c1")
    ]
    assert not plan_region_comparisons(preparation=preparation, mode="none")[0]
    with pytest.raises(WorkbenchError):
        plan_region_comparisons(preparation=preparation, mode="invalid")


def test_comparisons_use_quality_screen_and_label_region_scope(project):
    """A screened-out original rank one cannot be promoted by another cavity."""
    data = load_project(root=project)
    for model in data["models"]:
        model["input_scope"] = "cleaned_region"
    for pocket in data["pockets"]:
        pocket["quality_screen_pass"] = pocket["review_rank"] == 2
    save_project(root=project, data=data)
    result = compare_pair(
        root=project,
        data=load_project(root=project),
        reference="synthetic_reference",
        mobile="synthetic_mobile",
        settings=ComparisonSettings(
            engine="sequence_kabsch", quality_screen_only=True, top_pockets=1
        ),
    )
    assert result["pocket_matches"] == []
    assert query_table(root=project, table="pockets")[0]["quality_screen_pass"] is False


def fake_prediction(*, samples, output, tools, settings, resume):
    """Replace only third-party predictors with explicitly synthetic test records."""
    output.mkdir(parents=True, exist_ok=True)
    records, pockets = [], []
    for sample in samples:
        shutil.copy2(sample.model_path, output / f"{sample.sample_id}.cif")
        records.append(
            {
                "sample_id": sample.sample_id,
                "status": "complete",
                "cluster": "synthetic",
                "warnings": "Synthetic predictor fixture; not biological evidence",
            }
        )
        for method in ("fpocket", "p2rank", "p2rank_rescore"):
            for pocket_id, positions in ((1, range(20, 26)), (2, range(1, 4))):
                pockets.append(
                    {
                        "sample_id": sample.sample_id,
                        "method": method,
                        "pocket_id": pocket_id,
                        "review_rank": pocket_id,
                        "ranking_basis": "synthetic test evidence",
                        "confidence_status": "meets_local_confidence_rule",
                        "mean_plddt": 90.0,
                        "residues": [f"A_{i}" for i in positions],
                        "score": 1.0,
                    }
                )
    report = {
        "samples": records,
        "pockets": pockets,
        "ranked": [p for p in pockets if p["method"] == "fpocket"],
        "methods": [],
        "manifest": {"synthetic": True},
    }
    (output / "report.html").write_text(
        '<script id="data" type="application/json">' + json.dumps(report) + "</script>"
    )
    return 0


def test_complete_quality_run_resume_and_isolation(raw_models, tmp_path, monkeypatch):
    """The real preparation/import/MSA/tree/export path resumes without repredicting."""
    source, fasta = raw_models
    root = tmp_path / "separate_results"
    previous = tmp_path / "pockets_all_models_v1"
    previous.mkdir()
    (previous / "untouched.txt").write_text("original evidence")
    calls = []

    def predict(**options):
        """Count third-party fixture calls to verify completed-stage reuse."""
        calls.append(options)
        return fake_prediction(**options)

    monkeypatch.setattr(
        quality_rerun, "inspect_tools", lambda **_: {"synthetic_test": True}
    )
    monkeypatch.setattr(quality_rerun, "run_pipeline", predict)
    options = [
        "--models",
        str(source),
        "--output",
        str(root),
        "--fasta",
        str(fasta),
        "--threads",
        "1",
        "--workers",
        "1",
        "--bootstrap",
        "0",
        "--comparison-mode",
        "none",
    ]
    assert main(argv=options + ["--prepare-only"]) == 0
    assert not calls and not (root / "03_pocket_predictions").exists()
    assert main(argv=options + ["--resume"]) == 0
    assert len(calls) == 1
    outputs = json.loads((root / "latest_outputs.json").read_text())
    resource, review = Path(outputs["resource"]), Path(outputs["review_directory"])
    data = load_project(root=resource)
    assert len(data["models"]) == 4 and len(data["pockets"]) == 24
    assert len(query_table(root=resource, table="quality_models")) == 2
    assert len(query_table(root=resource, table="quality_regions")) == 4
    assert len(query_table(root=resource, table="region_comparison_plan")) == 4
    assert all(m["input_scope"] == "cleaned_region" for m in data["models"])
    assert any(p["quality_screen_pass"] for p in data["pockets"])
    assert any(p["near_cut_boundary"] for p in data["pockets"])
    assert len(data["sequence_analyses"]) == 1
    assert data["sequence_analyses"][0]["tree_path"]
    assert (review / "quality/quality_audit.xlsx").is_file()
    assert (review / "app_resource.zip").is_file()
    assert "quality/index.html" in (review / "index.html").read_text()
    assert (review / "tables/pocket_workbench.xlsx").is_file()
    assert Path(outputs["review_zip"]).is_file()
    assert (previous / "untouched.txt").read_text() == "original evidence"
    from streamlit.testing.v1 import AppTest

    from pocket_workbench import ui

    monkeypatch.setenv("POCKET_WORKBENCH_RESOURCE", str(resource))
    monkeypatch.setenv("POCKET_WORKBENCH_WORKSPACE", str(tmp_path / "ui_workspace"))
    app = AppTest.from_file(str(Path(ui.__file__)), default_timeout=20).run()
    app.sidebar.radio[0].set_value("Input quality").run()
    assert not app.exception and not app.error
    assert len(app.expander) == 4
    app.sidebar.radio[0].set_value("Models & pockets").run()
    assert not app.exception and not app.error
    assert any(c.value for c in app.checkbox if "quality screen" in c.label)
    assert main(argv=options + ["--resume"]) == 0
    assert len(calls) == 1
    assert (root / "05_review_002.zip").is_file()
    assert main(argv=options + ["--resume", "--padding", "6"]) == 1
    assert main(argv=options) == 1
    changed = next((root / "02_cleaned_models").glob("*.cif"))
    changed.write_text(changed.read_text() + "\n# edited\n")
    assert main(argv=options + ["--resume"]) == 1


def test_prepare_only_missing_pae_is_visible_partial_result(raw_models, tmp_path):
    """Missing PAE yields a useful rejection audit before any tools are needed."""
    source, fasta = raw_models
    for path in source.glob("*.json"):
        path.unlink()
    root = tmp_path / "no_pae"
    options = [
        "--models",
        str(source),
        "--fasta",
        str(fasta),
        "--output",
        str(root),
        "--threads",
        "1",
        "--workers",
        "1",
        "--prepare-only",
    ]
    assert main(argv=options) == 2
    rows = list(
        csv.DictReader(
            (root / "01_quality/Region_decisions.tsv").open(), delimiter="\t"
        )
    )
    assert rows and all("pae_unassessed" in row["reason"] for row in rows)
    assert not json.loads((root / "preparation.json").read_text())["regions"]


@pytest.mark.skipif(
    not os.getenv("POCKET_WORKBENCH_TEST_USALIGN")
    or not os.getenv("POCKET_WORKBENCH_TEST_TMALIGN"),
    reason="Requires real structural aligners",
)
def test_quality_batch_with_both_real_structural_aligners(
    raw_models, tmp_path, monkeypatch
):
    """Both real aligners consume cleaned regions; prediction alone is a fixture."""
    source, fasta = raw_models
    monkeypatch.setattr(
        quality_rerun, "inspect_tools", lambda **_: {"synthetic_test": True}
    )
    monkeypatch.setattr(quality_rerun, "run_pipeline", fake_prediction)
    root = tmp_path / "real_aligners"
    assert (
        main(
            argv=[
                "--models",
                str(source),
                "--fasta",
                str(fasta),
                "--output",
                str(root),
                "--threads",
                "1",
                "--workers",
                "2",
                "--bootstrap",
                "0",
                "--usalign",
                os.environ["POCKET_WORKBENCH_TEST_USALIGN"],
                "--tmalign",
                os.environ["POCKET_WORKBENCH_TEST_TMALIGN"],
            ]
        )
        == 0
    )
    data = load_project(root=root / "04_workbench")
    assert len(data["comparisons"]) == 4
    assert {r["engine"] for r in data["comparisons"]} == {"usalign", "tmalign"}
    for summary in data["comparisons"]:
        result = json.loads(
            (root / "04_workbench" / summary["result_path"]).read_text()
        )
        assert result["scope"] == "cleaned_region" and result["status"] == "complete"
        assert result["settings"]["quality_screen_only"] is True
        assert result["rmsd"] < 0.01


def test_slurm_script_passes_quoted_paths_and_resume_options(tmp_path):
    """The submitted shell calls the installed workflow with separate argv tokens."""
    package = Path(__file__).resolve().parents[1]
    project = tmp_path / "project with spaces"
    (project / "alpha_fold_models").mkdir(parents=True)
    (project / "BRCA1_all_reps.fasta").write_text(">a\nACDE\n")
    argv_path = tmp_path / "arguments.txt"
    conda = tmp_path / "fake_conda"
    conda.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$TEST_ARGV_PATH"\n')
    conda.chmod(0o755)
    script = package / "scripts/run_maddy_quality_pockets.slurm.sh"
    subprocess.run(["bash", "-n", str(script)], check=True)
    subprocess.run(
        ["bash", str(script), "--resume"],
        check=True,
        env=dict(
            os.environ,
            MADDY_PROJECT=str(project),
            CONDA_EXE=str(conda),
            TEST_ARGV_PATH=str(argv_path),
        ),
    )
    arguments = argv_path.read_text().splitlines()
    assert arguments[arguments.index("--models") + 1] == str(
        project / "alpha_fold_models"
    )
    assert arguments[arguments.index("--output") + 1] == str(
        project / "results/pockets_quality_regions_v1"
    )
    assert arguments[-1] == "--resume" and "pocket-workbench-rerun" in arguments
