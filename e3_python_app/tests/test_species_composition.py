"""Exercise complete species counts, chart scopes and Streamlit exports."""

import duckdb
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from e3app.errors import AppError
from e3app.group_lookup import quick_group_profile
from e3app.species_composition import member_species_counts, species_count_figure


def test_member_counts_distinguish_unknown_and_selected_sequences():
    """Count paralogues individually and retain missing assignments."""
    rows = pd.DataFrame({"taxon": ["Plant_a", None, "Plant_a", "unknown", "Plant_b"]})
    counts = member_species_counts(
        rows=rows, species_column="taxon",
        subsets={"selected": pd.Series([True, False, False, True, True])},
    )
    assert counts.set_index("species").to_dict(orient="index") == {
        "Plant_a": {"sequence_count": 2, "selected": 1},
        "Unclassified": {"sequence_count": 2, "selected": 1},
        "Plant_b": {"sequence_count": 1, "selected": 1},
    }
    assert member_species_counts(rows=rows, species_column="missing").empty
    for masks in ({"wrong": pd.Series([True])}, {"wrong": pd.Series(range(5))},
                  {"sequence_count": pd.Series([True] * 5)}):
        with pytest.raises(AppError):
            member_species_counts(rows=rows, species_column="taxon", subsets=masks)


def test_search_profile_counts_all_rows_even_with_one_preview():
    """Group species totals stay independent of the table preview and scope."""
    with duckdb.connect(config={"threads": 1}) as connection:
        connection.execute(
            "CREATE TABLE hierarchical_membership(group_id VARCHAR, species VARCHAR, "
            "raw_identifier VARCHAR)"
        )
        connection.execute(
            "INSERT INTO hierarchical_membership VALUES "
            "('N0.HOG1', 'Plant_a', 'a'), ('N0.HOG1', 'Plant_a', 'b'), "
            "('N0.HOG1', NULL, 'c'), ('N0.HOG1', 'Plant_b', 'd'), ('N0.HOG2', 'Plant_b', 'e')"
        )
        profile = quick_group_profile(connection=connection, group_id="N0.HOG1", maximum_rows=1)
    assert len(profile["members"]) == 1 and profile["member_count"] == 4
    assert profile["species_count"] == 2
    assert profile["species_composition"].set_index("species")["sequence_count"].to_dict() == {
        "Plant_a": 2, "Plant_b": 1, "Unclassified": 1,
    }


def test_species_chart_bounds_bars_and_keeps_full_table():
    """Large selections show the leading 25 species while TSV and table retain every count."""
    counts = pd.DataFrame({"species": [f"Plant_{i}" for i in range(30)], "count": range(30)})
    figure = species_count_figure(counts=counts, series={"count": "Aligned"})
    assert len(figure.data[0].x) == 25
    assert figure.data[0].y[-1] == "Plant 0"
    app = AppTest.from_string(
        "import pandas as pd\n"
        "from e3app.species_composition import render_species_counts\n"
        "counts=pd.DataFrame({'species': [f'Plant_{i}' for i in range(30)], "
        "'sequence_count': range(30)})\n"
        "render_species_counts(counts=counts, key='test', description='Example')\n"
        "render_species_counts(counts=counts.iloc[0:0], key='empty', description='No rows')\n",
    ).run()
    assert len(app.dataframe[0].value) == 30
    assert app.get("download_button")[0].label == "Download species counts (TSV)"
    assert app.selectbox(key="test_species_page").options == ["1–25 of 30", "26–30 of 30"]
    app.selectbox(key="test_species_page").set_value(25).run()
    assert len(app.dataframe[0].value) == 30
    assert any("unavailable" in item.value for item in app.info)
    assert not app.exception
