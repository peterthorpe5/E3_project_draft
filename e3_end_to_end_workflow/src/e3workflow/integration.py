"""Final evidence integration, prioritisation and application hand-off."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb

from e3workflow import __version__
from e3workflow.config import WorkflowConfig
from e3workflow.errors import StageError
from e3workflow.io_utils import atomic_write_json, sha256_file, utc_now, write_tsv
from e3workflow.production import find_one
from e3workflow.tabular import quote_identifier, quote_literal

FINAL_FIELDS = (
    "final_rank",
    "stringent_rank",
    "recommendation_status",
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "candidate_accessions",
    "prestructure_score",
    "ligandability_score",
    "pocket_conservation_score",
    "structural_score",
    "final_score",
    "target_species_fraction",
    "mandatory_species_fraction",
    "domain_species_fraction",
    "expression_species_fraction",
    "structural_species_fraction",
    "minimum_druggability_score",
    "mean_pairwise_region_overlap",
    "mean_chemical_group_conservation",
    "mean_pocket_plddt_fraction",
    "predictor_agreement_fraction",
    "grant_aligned_prestructure_pass",
    "grant_aligned_final_pass",
    "conservation_status",
    "inclusion_reasons",
    "exclusion_reasons",
    "missing_evidence",
    "structural_exclusion_reasons",
    "profile_name",
    "interpretation",
)


def _final_query(config: WorkflowConfig, prestructure: Path, conservation: Path) -> str:
    """Return the final transparent scoring query."""
    settings = config.analysis.prioritisation
    ligandability = config.analysis.ligandability
    return (
        "WITH pre AS (SELECT * FROM read_parquet("
        f"{quote_literal(prestructure)})), pockets AS (SELECT * FROM read_parquet("
        f"{quote_literal(conservation)})), joined AS (SELECT p.*, "
        "COALESCE(c.structured_species_count, 0) AS structured_species_count, "
        "COALESCE(c.conserved_component_species_count, 0) AS conserved_component_species_count, "
        "COALESCE(c.conserved_component_fraction, 0.0) AS conserved_component_fraction, "
        "COALESCE(c.mean_pairwise_region_overlap, 0.0) AS mean_pairwise_region_overlap, "
        "COALESCE(c.mean_chemical_group_conservation, 0.0) AS "
        "mean_chemical_group_conservation, COALESCE(c.minimum_druggability_score, 0.0) AS "
        "minimum_druggability_score, COALESCE(c.mean_druggability_score, 0.0) AS "
        "mean_druggability_score, COALESCE(c.mean_pocket_plddt_fraction, 0.0) AS "
        "mean_pocket_plddt_fraction, COALESCE(c.predictor_agreement_fraction, 0.0) AS "
        "predictor_agreement_fraction, COALESCE(c.conserved_pocket_score, 0.0) AS "
        "pocket_conservation_score, COALESCE(c.conservation_status, "
        "'NO_STRUCTURAL_EVIDENCE') AS conservation_status, "
        "COALESCE(c.all_assessed_members_pass_druggability, false) AS "
        "all_assessed_members_pass_druggability, COALESCE(c.all_assessed_members_pass_mapping, "
        "false) AS all_assessed_members_pass_mapping FROM pre p LEFT JOIN pockets c "
        "USING (cluster_id, primary_group_type, primary_group_id)), components AS (SELECT *, "
        "(minimum_druggability_score + mean_pocket_plddt_fraction + "
        "CAST(all_assessed_members_pass_mapping AS INTEGER) + predictor_agreement_fraction) / 4.0 "
        "AS ligandability_score, conserved_component_species_count::DOUBLE / "
        "NULLIF(target_species_total, 0) AS structural_species_fraction FROM joined), scores AS ("
        "SELECT *, ligandability_score * "
        f"{settings.ligandability_weight} + pocket_conservation_score * "
        f"{settings.pocket_conservation_weight} AS structural_score FROM components), decisions "
        "AS (SELECT *, prestructure_score * "
        f"{settings.prestructure_final_weight} + structural_score * "
        f"{settings.structural_final_weight} AS final_score, "
        "CAST(grant_aligned_stringent_pass AS BOOLEAN) AS grant_aligned_prestructure_pass, "
        "CASE WHEN CAST(grant_aligned_stringent_pass AS BOOLEAN) AND conservation_status = "
        "'CONSERVED_REGION_SUPPORTED' AND minimum_druggability_score >= "
        f"{ligandability.minimum_druggability_score} AND all_assessed_members_pass_druggability "
        "AND all_assessed_members_pass_mapping AND structural_species_fraction >= "
        f"{settings.minimum_structural_species_fraction} THEN true ELSE false END AS "
        "grant_aligned_final_pass, concat_ws(';', CASE WHEN conservation_status <> "
        "'CONSERVED_REGION_SUPPORTED' THEN 'conserved_pocket_region_not_supported' END, CASE "
        "WHEN minimum_druggability_score < "
        f"{ligandability.minimum_druggability_score} THEN 'minimum_druggability_below_threshold' "
        "END, CASE WHEN NOT all_assessed_members_pass_druggability THEN "
        "'not_all_assessed_members_pass_druggability' END, CASE WHEN NOT "
        "all_assessed_members_pass_mapping THEN 'not_all_assessed_members_pass_mapping' END, "
        "CASE WHEN structural_species_fraction < "
        f"{settings.minimum_structural_species_fraction} THEN "
        "'structural_species_fraction_below_threshold' END) AS structural_exclusion_reasons "
        "FROM scores), ranked AS (SELECT *, row_number() OVER (ORDER BY "
        "grant_aligned_final_pass DESC, final_score DESC, evidence_completeness_fraction DESC, "
        "cluster_id) AS final_rank, CASE WHEN grant_aligned_final_pass THEN row_number() OVER "
        "(PARTITION BY grant_aligned_final_pass ORDER BY final_score DESC, cluster_id) END AS "
        "stringent_rank FROM decisions) SELECT final_rank, stringent_rank, CASE WHEN "
        "grant_aligned_final_pass AND stringent_rank <= "
        f"{settings.final_candidate_limit} THEN 'PRIORITY_RECOMMENDATION' WHEN "
        "grant_aligned_final_pass THEN 'STRINGENT_PASS_OUTSIDE_TOP_LIMIT' ELSE "
        "'FURTHER_EVIDENCE_OR_REVIEW_REQUIRED' END AS recommendation_status, cluster_id, "
        "primary_group_type, primary_group_id, candidate_accessions, prestructure_score, "
        "ligandability_score, pocket_conservation_score, structural_score, final_score, "
        "target_species_fraction, mandatory_species_fraction, domain_species_fraction, "
        "expression_species_fraction, structural_species_fraction, minimum_druggability_score, "
        "mean_pairwise_region_overlap, mean_chemical_group_conservation, "
        "mean_pocket_plddt_fraction, predictor_agreement_fraction, "
        "grant_aligned_prestructure_pass, "
        "grant_aligned_final_pass, conservation_status, inclusion_reasons, exclusion_reasons, "
        "missing_evidence, structural_exclusion_reasons, profile_name, "
        "'computational evidence prioritisation; experimental E3 activity, binding and "
        "degradation remain unvalidated' AS interpretation FROM ranked ORDER BY final_rank"
    )


def _copy_query_tsv(
    *, connection: duckdb.DuckDBPyConnection, query: str, path: Path
) -> None:
    """Atomically publish a DuckDB query as tab-separated text."""
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    temporary.unlink(missing_ok=True)
    try:
        connection.execute(
            f"COPY ({query}) TO {quote_literal(temporary)} "
            "(FORMAT CSV, DELIMITER '\t', HEADER TRUE, QUOTE '" + '"' + "')"
        )
        temporary.replace(destination)
    except duckdb.Error as exc:
        temporary.unlink(missing_ok=True)
        raise StageError(f"Could not publish TSV query {destination}: {exc}") from exc


def _create_table_from_parquet(
    *,
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    path: Path,
) -> None:
    """Materialise one Parquet authority in the integrated DuckDB."""
    connection.execute(
        f"CREATE TABLE {quote_identifier(table_name)} AS SELECT * FROM read_parquet("
        f"{quote_literal(path)})"
    )


def _resource_tables(config: WorkflowConfig) -> list[tuple[str, Path]]:
    """Resolve the completed workflow authorities included in the final database."""
    roots_and_names = (
        ("candidate_evidence", "03_candidate_evidence", "e3_cluster_candidate_evidence.parquet"),
        ("candidate_orthology", "05_orthology", "candidate_membership_mapping.parquet"),
        ("orthogroup_membership", "05_orthology", "orthogroup_membership.parquet"),
        ("hierarchical_membership", "05_orthology", "hierarchical_membership.parquet"),
        (
            "candidate_orthology_summary",
            "05_orthology",
            "candidate_cluster_orthology_summary.parquet",
        ),
        ("domain_hits", "06_domains", "domain_hits.parquet"),
        ("domain_summary", "06_domains", "domain_summary.parquet"),
        ("candidate_identifier_aliases", "07_expression", "candidate_identifier_aliases.parquet"),
        ("candidate_expression_mapping", "07_expression", "candidate_expression_mapping.parquet"),
        ("candidate_expression_summary", "07_expression", "candidate_expression_summary.parquet"),
        ("prestructure_ranking", "08_shortlist_gate", "computational_prestructure_ranking.parquet"),
        (
            "structural_analysis_accessions",
            "08_shortlist_gate",
            "structural_analysis_accessions.parquet",
        ),
        ("selected_pockets", "09_ligandability", "selected_pockets.parquet"),
        (
            "structural_prediction_status",
            "09_ligandability",
            "structural_prediction_status.parquet",
        ),
        ("pocket_conservation_summary", "09_ligandability", "pocket_conservation_summary.parquet"),
        ("pocket_conservation_members", "09_ligandability", "pocket_conservation_members.parquet"),
    )
    return [
        (table_name, find_one(root=config.run_root / stage_name, name=filename))
        for table_name, stage_name, filename in roots_and_names
    ]


def _bar_chart(records: Sequence[Mapping[str, Any]], width: int = 900) -> str:
    """Return an embedded SVG chart for the highest-ranked final scores."""
    selected = list(records[:20])
    if not selected:
        return "<p>No prioritisation rows were available.</p>"
    row_height = 30
    left = 190
    chart_width = width - left - 80
    height = 35 + row_height * len(selected)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Final candidate score chart">'
    ]
    for index, record in enumerate(selected):
        y = 25 + index * row_height
        score = max(0.0, min(1.0, float(record["final_score"])))
        colour = "#216e39" if record["grant_aligned_final_pass"] else "#7a5b16"
        parts.append(
            f'<text x="0" y="{y + 15}" font-size="13">'
            f'{html.escape(str(record["cluster_id"]))}</text>'
        )
        parts.append(
            f'<rect x="{left}" y="{y}" width="{score * chart_width:.2f}" height="19" '
            f'fill="{colour}" rx="3" />'
        )
        parts.append(
            f'<text x="{left + score * chart_width + 7:.2f}" y="{y + 15}" '
            f'font-size="12">{score:.3f}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _table(records: Sequence[Mapping[str, Any]]) -> str:
    """Return a bounded HTML table of final candidate results."""
    columns = (
        "final_rank",
        "recommendation_status",
        "cluster_id",
        "primary_group_id",
        "final_score",
        "target_species_fraction",
        "expression_species_fraction",
        "structural_species_fraction",
        "conservation_status",
    )
    header = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body = []
    for record in records[:25]:
        cells = []
        for column in columns:
            value = record.get(column, "")
            if isinstance(value, float):
                value = f"{value:.4f}"
            cells.append(f"<td>{html.escape(str(value))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def write_prioritisation_report(
    *, config: WorkflowConfig, records: Sequence[Mapping[str, Any]], path: Path
) -> None:
    """Write a self-contained verbose scientific prioritisation report."""
    stringent = [record for record in records if record["grant_aligned_final_pass"]]
    recommendations = [
        record for record in records if record["recommendation_status"] == "PRIORITY_RECOMMENDATION"
    ]
    prestructure = [record for record in records if record["grant_aligned_prestructure_pass"]]
    no_conserved_structure = [
        record
        for record in records
        if record["conservation_status"] != "CONSERVED_REGION_SUPPORTED"
    ]
    missing_evidence = [record for record in records if record.get("missing_evidence")]
    body = f"""<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width">
<title>ARIA E3 computational prioritisation</title><style>
body{{font-family:system-ui,sans-serif;max-width:1180px;margin:2rem auto;
padding:0 1rem;color:#17202a}}
h1,h2{{color:#173f5f}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}}
.card{{border:1px solid #ccd6dd;border-radius:8px;padding:1rem;background:#f8fafb}}
.number{{font-size:2rem;font-weight:700}}
table{{border-collapse:collapse;width:100%;font-size:.88rem}}
th,td{{border:1px solid #d5dde3;padding:.45rem;text-align:left;vertical-align:top}}
th{{background:#edf3f7}}
.warning{{border-left:5px solid #a66a00;background:#fff7e6;padding:1rem}}
code{{word-break:break-all}}
svg{{width:100%;height:auto}}
@media(max-width:800px){{.cards{{grid-template-columns:1fr 1fr}}}}
</style></head><body>
<h1>ARIA plant E3 computational prioritisation</h1>
<p><strong>Run:</strong> {html.escape(config.run_name)}<br><strong>Profile:</strong>
{html.escape(config.analysis.prioritisation.profile_name)}<br><strong>Generated:</strong>
{html.escape(utc_now())}</p>
<div class="cards">
<div class="card"><div class="number">{len(records)}</div>candidate groups ranked</div>
<div class="card"><div class="number">{len(prestructure)}</div>
grant-aligned pre-structure passes</div>
<div class="card"><div class="number">{len(stringent)}</div>final stringent passes</div>
<div class="card"><div class="number">{len(recommendations)}</div>
priority recommendations</div></div>
<h2>Direct result</h2><p>The workflow ranked {len(records)} candidate groups and identified
{len(recommendations)} candidates within the configured
top-{config.analysis.prioritisation.final_candidate_limit} priority recommendation limit.
A recommendation requires broad target and mandatory-crop coverage,
broad mapped Expression Atlas support, conserved E3-domain support,
reusable high-quality pocket evidence
and a pocket-bearing aligned region supported across the configured structural species fraction.</p>
<div class="warning"><strong>Interpretation boundary.</strong>
These are computational recommendations. Neither AlphaFold confidence, domain annotation,
OrthoFinder grouping, RNA expression, fpocket/P2Rank scores nor aligned pocket-region
conservation proves E3 activity, compound binding or target degradation.
Human structural, biological and chemistry review remains required.</div>
<h2>Top final scores</h2>{_bar_chart(records)}
<h2>Top candidate table</h2>{_table(records)}
<h2>Evidence and thresholds</h2><ul>
<li>Target plants:
{html.escape('; '.join(config.analysis.prioritisation.target_species))}</li>
<li>Mandatory crop panel:
{html.escape('; '.join(config.analysis.prioritisation.mandatory_species))}</li>
<li>Minimum target-species fraction:
{config.analysis.prioritisation.minimum_target_species_fraction:.3f}</li>
<li>Minimum expression-species fraction:
{config.analysis.prioritisation.minimum_expression_species_fraction:.3f}</li>
<li>Minimum domain-species fraction:
{config.analysis.prioritisation.minimum_domain_species_fraction:.3f}</li>
<li>Minimum structural-species fraction:
{config.analysis.prioritisation.minimum_structural_species_fraction:.3f}</li>
<li>Minimum fpocket/P2Rank druggability score:
{config.analysis.ligandability.minimum_druggability_score:.3f}</li>
</ul>
<h2>Coverage limitations</h2><p>{len(no_conserved_structure)} ranked groups lacked a supported
multi-member conserved-pocket region, and {len(missing_evidence)} ranked groups had at least one
explicit missing-evidence state. A configured species without a compatible domain annotation or
Expression Atlas resource remains unavailable rather than becoming a biological negative.</p>
<h2>Authoritative outputs</h2><p>The complete row-level evidence, scores,
inclusion/exclusion reasons, missing-data states, provenance and source tables are stored in
<code>duckdb/e3_integrated_resource.duckdb</code>
and the matching TSV/Parquet final ranking.</p></body></html>"""
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    temporary.write_text(body, encoding="utf-8")
    temporary.replace(destination)


def run_integrated_stage(*, config: WorkflowConfig, stage_root: Path) -> None:
    """Build the portable integrated DuckDB, final ranking and scientific HTML report."""
    prestructure = find_one(
        root=config.run_root / "08_shortlist_gate",
        name="computational_prestructure_ranking.parquet",
    )
    conservation = find_one(
        root=config.run_root / "09_ligandability", name="pocket_conservation_summary.parquet"
    )
    final_query = _final_query(
        config=config, prestructure=prestructure, conservation=conservation
    )
    database_path = stage_root / "duckdb" / "e3_integrated_resource.duckdb"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_database = database_path.with_name(f".{database_path.name}.partial")
    temporary_database.unlink(missing_ok=True)
    connection = duckdb.connect(str(temporary_database))
    try:
        for table_name, source_path in _resource_tables(config=config):
            _create_table_from_parquet(
                connection=connection, table_name=table_name, path=source_path
            )
        connection.execute(
            f"CREATE TABLE final_candidate_prioritisation AS {final_query}"
        )
        connection.execute(
            "CREATE TABLE resource_metadata AS SELECT ? AS resource_name, ? AS package_version, "
            "? AS run_name, ? AS configuration_digest, ? AS scoring_profile, ? AS created_at",
            [
                "ARIA E3 integrated prioritisation resource",
                __version__,
                config.run_name,
                config.digest,
                config.analysis.prioritisation.profile_name,
                utc_now(),
            ],
        )
        final_rows = connection.execute(
            "SELECT * FROM final_candidate_prioritisation ORDER BY final_rank"
        ).fetchall()
        final_columns = [str(item[0]) for item in connection.description]
        _copy_query_tsv(
            connection=connection,
            query="SELECT * FROM final_candidate_prioritisation ORDER BY final_rank",
            path=stage_root / "tables" / "final_candidate_prioritisation.tsv",
        )
        connection.execute(
            "COPY final_candidate_prioritisation TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(stage_root / "tables" / "final_candidate_prioritisation.parquet")],
        )
        connection.execute("CHECKPOINT")
    except duckdb.Error as exc:
        connection.close()
        temporary_database.unlink(missing_ok=True)
        raise StageError(f"Could not build integrated DuckDB: {exc}") from exc
    finally:
        try:
            connection.close()
        except duckdb.Error:
            pass
    temporary_database.replace(database_path)
    records = [dict(zip(final_columns, row)) for row in final_rows]
    if not records:
        raise StageError("Final integrated prioritisation contains no candidate rows")
    report_path = stage_root / "reports" / "final_computational_prioritisation.html"
    write_prioritisation_report(config=config, records=records, path=report_path)
    summary = {
        "run_name": config.run_name,
        "profile_name": config.analysis.prioritisation.profile_name,
        "candidate_count": len(records),
        "prestructure_pass_count": sum(
            bool(record["grant_aligned_prestructure_pass"]) for record in records
        ),
        "final_stringent_pass_count": sum(
            bool(record["grant_aligned_final_pass"]) for record in records
        ),
        "priority_recommendation_count": sum(
            record["recommendation_status"] == "PRIORITY_RECOMMENDATION"
            for record in records
        ),
        "database_sha256": sha256_file(database_path),
        "report_sha256": sha256_file(report_path),
        "interpretation": (
            "computational recommendations requiring human and experimental validation"
        ),
    }
    atomic_write_json(stage_root / "provenance" / "integrated_resource_manifest.json", summary)
    write_tsv(
        stage_root / "qc" / "integrated_resource_validation.tsv",
        [summary],
        (
            "run_name",
            "profile_name",
            "candidate_count",
            "prestructure_pass_count",
            "final_stringent_pass_count",
            "priority_recommendation_count",
            "database_sha256",
            "report_sha256",
            "interpretation",
        ),
    )


def run_app_ready_stage(*, config: WorkflowConfig, stage_root: Path) -> None:
    """Publish stable configuration hand-offs for the R Shiny and Python applications."""
    integrated_stage = config.run_root / "10_integrated_resource"
    database = integrated_stage / "duckdb" / "e3_integrated_resource.duckdb"
    report = integrated_stage / "reports" / "final_computational_prioritisation.html"
    final_table = integrated_stage / "tables" / "final_candidate_prioritisation.parquet"
    for path in (database, report, final_table):
        if not path.is_file() or path.stat().st_size == 0:
            raise StageError(f"Application hand-off input is missing or empty: {path}")
    rows = [
        {
            "run_name": config.run_name,
            "mode": config.mode,
            "production_eligible": "true",
            "resource_duckdb": database,
            "resource_duckdb_sha256": sha256_file(database),
            "final_ranking_parquet": final_table,
            "final_report_html": report,
            "python_app_root": config.project_root / "e3_python_app",
            "r_shiny_app_root": config.project_root / "E3_shiny_app",
            "read_only_required": "true",
        }
    ]
    write_tsv(
        stage_root / "app_handoff.tsv",
        rows,
        (
            "run_name",
            "mode",
            "production_eligible",
            "resource_duckdb",
            "resource_duckdb_sha256",
            "final_ranking_parquet",
            "final_report_html",
            "python_app_root",
            "r_shiny_app_root",
            "read_only_required",
        ),
    )
    (stage_root / "config").mkdir(parents=True, exist_ok=True)
    (stage_root / "config" / "python_app.env").write_text(
        f"E3_RESOURCE_DUCKDB={database}\nE3_MAX_ROWS=10000\n",
        encoding="utf-8",
    )
    write_tsv(
        stage_root / "config" / "shiny_app_config.tsv",
        [
            {"setting": "resource_duckdb", "value": database},
            {"setting": "expression_duckdb", "value": ""},
            {"setting": "max_preview_rows", "value": 10000},
        ],
        ("setting", "value"),
    )
    atomic_write_json(
        stage_root / "app_release_manifest.json",
        {
            "run_name": config.run_name,
            "resource_duckdb": str(database),
            "resource_duckdb_sha256": sha256_file(database),
            "final_report_html": str(report),
            "created_at": utc_now(),
            "status": "READY_FOR_READ_ONLY_APPLICATIONS",
        },
    )
