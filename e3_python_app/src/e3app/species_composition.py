"""Count recorded members by species and display complete composition tables."""

from __future__ import annotations

from typing import Mapping

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from e3app.errors import AppError


def member_species_counts(
    *, rows: pd.DataFrame, species_column: str, subsets: Mapping[str, pd.Series] | None = None,
) -> pd.DataFrame:
    """Count one row per member, retaining records without assigned species.

    Args:
        rows: Complete member rows from one defined scope.
        species_column: Column containing the recorded species label.
        subsets: Optional named boolean masks aligned with the member rows.

    Returns:
        Counts by recorded species, with the total followed by requested subsets.

    Raises:
        AppError: If a subset is not a boolean mask for these member rows.
    """
    fields = ["species", "sequence_count", *(subsets or {})]
    if species_column not in rows:
        return pd.DataFrame(columns=fields)
    species = rows[species_column].fillna("").astype(str).str.strip()
    unknown = species.str.upper().isin(("", "UNCLASSIFIED", "UNKNOWN", "NAN"))
    members = pd.DataFrame({"species": species.mask(unknown, "Unclassified"), "sequence_count": 1})
    for name, mask in (subsets or {}).items():
        if name in {"species", "sequence_count"} or not mask.index.equals(rows.index):
            raise AppError("Species subset must identify rows in the same member table")
        if not pd.api.types.is_bool_dtype(mask):
            raise AppError("Species subset must be a boolean mask")
        members[name] = mask.fillna(False).astype(int)
    return members.groupby("species", as_index=False).sum().sort_values(
        ["sequence_count", "species"], ascending=[False, True],
    ).reset_index(drop=True)


def species_count_figure(*, counts: pd.DataFrame, series: Mapping[str, str]) -> go.Figure:
    """Build a grouped horizontal bar chart for the leading species.

    Args:
        counts: Complete species counts in desired display order.
        series: Count column names mapped to legend labels.

    Returns:
        Figure for up to 25 species, with integer sequence counts on the x-axis.
    """
    displayed = counts.head(25).iloc[::-1]
    figure = go.Figure()
    for name, label in series.items():
        figure.add_bar(
            x=displayed[name], y=displayed["species"].str.replace("_", " ", regex=False),
            name=label, orientation="h", hovertemplate="%{y}<br>%{x:,} sequences<extra></extra>",
        )
    figure.update_layout(
        barmode="group", height=max(230, 105 + 24 * len(displayed)),
        showlegend=len(series) > 1, margin={"l": 10, "r": 15, "t": 15, "b": 15},
        xaxis={"title": "Protein sequences", "rangemode": "tozero", "tickformat": ",d"},
        yaxis={"title": None, "type": "category", "automargin": True},
        legend={"orientation": "h", "y": 1.0, "yanchor": "bottom"},
    )
    return figure


def render_species_counts(
    *, counts: pd.DataFrame, key: str, description: str,
    series: Mapping[str, str] | None = None, expanded: bool = False,
    label: str = "Species composition",
) -> None:
    """Show a species graph, its complete table and an export for the same scope.

    Args:
        counts: Complete count table for the selected member set.
        key: Unique widget and filename stem.
        description: The source and scope of the counted proteins.
        series: Optional comparison columns and their labels.
        expanded: Show the plot and table immediately.
        label: Heading describing the selected count scope.
    """
    with st.expander(label, expanded=expanded):
        st.caption(description)
        if counts.empty:
            st.info("Species counts are unavailable for this selection.")
            return
        labels = series or {"sequence_count": "Protein sequences"}
        first = next(iter(labels))
        ordered = counts.sort_values([first, "species"], ascending=[False, True])
        displayed = ordered
        if len(ordered) > 25:
            start = st.selectbox(
                "Species shown in the chart", options=list(range(0, len(ordered), 25)),
                format_func=lambda start: f"{start + 1:,}–{min(start + 25, len(ordered)):,}"
                f" of {len(ordered):,}",
                key=f"{key}_species_page",
            )
            displayed = ordered.iloc[start:start + 25]
        st.plotly_chart(
            species_count_figure(counts=displayed, series=labels), key=f"{key}_species_plot",
        )
        table = ordered.assign(species=ordered["species"].str.replace("_", " ", regex=False))
        st.dataframe(
            table.rename(columns={
                "species": "Species", "reviewed_taxon_id": "Reviewed taxon ID", **labels,
            }),
            hide_index=True, height=min(350, 38 + 35 * len(table)),
        )
        st.download_button(
            "Download species counts (TSV)", data=ordered.to_csv(sep="\t", index=False),
            file_name=f"{key}_species_counts.tsv", mime="text/tab-separated-values",
            key=f"{key}_species_tsv", on_click="ignore",
        )
