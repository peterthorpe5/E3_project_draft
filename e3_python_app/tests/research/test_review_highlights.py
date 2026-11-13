"""Check residue and provenance joins used by other native structural viewers."""

import json

import duckdb

from e3app.pocket_review import add_terminal_trimming_controls
from e3app.research.review_highlights import add_review_highlights, review_highlight_payload


def test_review_highlights_validate_models_and_keep_roles_separate():
    """Match domains and sequence to one exact member and map each pair role separately."""
    atom = {"resi": 1, "chain": "A", "resn": "ALA", "x": 1, "y": 0, "z": 0}
    group = {
        "alignment": {"records": [
            {"accession": "P12345", "species": "Plant_a", "sequence": "A-C"},
            {"accession": "P12345", "species": "Plant_b", "sequence": "G-C"},
        ]},
        "proteins": [{"accession": "P12345", "species": "Plant_a", "atoms": [atom]}],
    }
    pair = {"reference": [atom], "mobile": [atom],
            "metadata": {"reference": "P12345", "mobile": "P12345"}}
    with duckdb.connect(config={"threads": 1}) as connection:
        connection.execute(
            "CREATE TABLE domain_hits AS SELECT 'P12345' AS member_accession, "
            "'Plant_a' AS species_column, 'N0.HOG1' AS primary_group_id, "
            "1 AS location_start, 2 AS location_end, 2 AS protein_length, "
            "'PF001' AS entry_accession, 'Domain' AS entry_name"
        )
        payload = review_highlight_payload(
            group=group, pair=pair, group_id="N0.HOG1", connection=connection,
            pair_members={"reference": ("P12345", "Plant_a"), "mobile": ("P12345", "Plant_b")},
        )
    assert list(payload) == ["reference"]
    assert payload["reference"]["sequence"] == "AC"
    assert payload["reference"]["features"][0]["provenance"] == "recorded_coordinates"
    group["proteins"].append({"accession": "P12345", "species": "Plant_b", "atoms": [atom]})
    assert review_highlight_payload(
        group=group, pair=None, group_id="N0.HOG1", connection=None,
    ) == {}


def test_compatible_document_gets_offline_controls_and_inert_json():
    """Upgrade recognised report HTML once, and preserve unrelated or malformed pages."""
    atom = {"resi": 1, "chain": "A", "resn": "ALA", "x": 1, "y": 0, "z": 0}
    group = {
        "alignment": {"records": [{"accession": "P12345", "species": "Plant_a",
                                   "sequence": "AC"}]},
        "proteins": [{"accession": "P12345", "species": "Plant_a", "atoms": [atom]}],
    }
    document = (
        '<html><body><canvas id="viewer"></canvas><aside></aside>'
        '<script id="reviewData" type="application/json">' + json.dumps(group)
        + '</script></body></html>'
    )
    original = add_terminal_trimming_controls(document)
    upgraded = add_review_highlights(document=original, group_id="N0.HOG1")
    assert 'id="e3ReviewHighlights"' in upgraded
    assert '"sequence": "AC"' in upgraded
    assert "Download 3D view (PDF)" in upgraded
    assert add_review_highlights(document=upgraded, group_id="N0.HOG1") == upgraded
    assert add_review_highlights(document=document, group_id="N0.HOG1") == document
    broken = original.replace(json.dumps(group), "invalid")
    assert add_review_highlights(document=broken, group_id="N0.HOG1") == broken
    group["group_key"] = {"primary_group_id": "N0.HOG2"}
    other = original.replace(json.dumps({
        name: value for name, value in group.items() if name != "group_key"
    }), json.dumps(group))
    assert add_review_highlights(document=other, group_id="N0.HOG1") == other
