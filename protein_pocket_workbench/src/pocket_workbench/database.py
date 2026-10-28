"""Versioned, materialised DuckDB tables and portable project exports."""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import duckdb
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from .core import WorkbenchError, inside, load_project, write_json, write_tsv

TABLES = {
    "models": [
        ("sample_id", "VARCHAR PRIMARY KEY"),
        ("group_id", "VARCHAR"),
        ("hog_id", "VARCHAR"),
        ("source_accession", "VARCHAR"),
        ("source_url", "VARCHAR"),
        ("sequence_id", "VARCHAR"),
        ("status", "VARCHAR"),
        ("mapping_status", "VARCHAR"),
        ("parent_sample_id", "VARCHAR"),
        ("input_scope", "VARCHAR"),
        ("region_name", "VARCHAR"),
        ("original_start", "INTEGER"),
        ("original_end", "INTEGER"),
        ("selection_source", "VARCHAR"),
        ("original_mapping_status", "VARCHAR"),
        ("residue_count", "INTEGER"),
        ("mean_plddt", "DOUBLE"),
        ("fraction_ge_threshold", "DOUBLE"),
        ("prepared_model", "VARCHAR"),
        ("record_json", "JSON"),
    ],
    "pockets": [
        ("sample_id", "VARCHAR"),
        ("method", "VARCHAR"),
        ("pocket_id", "INTEGER"),
        ("review_rank", "INTEGER"),
        ("score", "DOUBLE"),
        ("druggability_score", "DOUBLE"),
        ("p2rank_rescore_score", "DOUBLE"),
        ("probability", "DOUBLE"),
        ("volume_a3", "DOUBLE"),
        ("mean_plddt", "DOUBLE"),
        ("confidence_status", "VARCHAR"),
        ("quality_screen_pass", "BOOLEAN"),
        ("near_cut_boundary", "BOOLEAN"),
        ("cut_boundary_distance_a", "DOUBLE"),
        ("near_very_low_confidence", "BOOLEAN"),
        ("uncertain_context_distance_a", "DOUBLE"),
        ("residues", "JSON"),
        ("record_json", "JSON"),
    ],
    "residues": [
        ("sample_id", "VARCHAR"),
        ("residue_key", "VARCHAR"),
        ("author_chain", "VARCHAR"),
        ("author_residue_number", "VARCHAR"),
        ("insertion_code", "VARCHAR"),
        ("amino_acid", "VARCHAR"),
        ("sequence_position", "INTEGER"),
        ("plddt", "DOUBLE"),
        ("x", "DOUBLE"),
        ("y", "DOUBLE"),
        ("z", "DOUBLE"),
    ],
    "sequences": [("sequence_id", "VARCHAR PRIMARY KEY"), ("sequence", "VARCHAR")],
    "structure_alignments": [
        ("comparison_id", "VARCHAR PRIMARY KEY"),
        ("reference", "VARCHAR"),
        ("mobile", "VARCHAR"),
        ("engine", "VARCHAR"),
        ("status", "VARCHAR"),
        ("rmsd", "DOUBLE"),
        ("aligned_atoms", "INTEGER"),
        ("reference_coverage", "DOUBLE"),
        ("mobile_coverage", "DOUBLE"),
        ("tm_reference", "DOUBLE"),
        ("tm_mobile", "DOUBLE"),
        ("tool_version", "VARCHAR"),
        ("aligned_sequence_identity", "DOUBLE"),
        ("rotation", "JSON"),
        ("translation", "JSON"),
        ("settings", "JSON"),
        ("record_json", "JSON"),
    ],
    "pocket_matches": [
        ("comparison_id", "VARCHAR"),
        ("reference", "VARCHAR"),
        ("mobile", "VARCHAR"),
        ("reference_pocket", "INTEGER"),
        ("mobile_pocket", "INTEGER"),
        ("reference_rank", "INTEGER"),
        ("mobile_rank", "INTEGER"),
        ("centroid_distance", "DOUBLE"),
        ("symmetric_overlap", "DOUBLE"),
        ("mutual_match_fraction", "DOUBLE"),
        ("sequence_jaccard", "DOUBLE"),
        ("position_supported", "BOOLEAN"),
        ("fold_supported", "BOOLEAN"),
        ("complete_mapping", "BOOLEAN"),
        ("comparable_residue_pairs", "INTEGER"),
        ("residue_identity_fraction", "DOUBLE"),
        ("chemical_group_conservation", "DOUBLE"),
        ("record_json", "JSON"),
    ],
    "sequence_analyses": [
        ("analysis_id", "VARCHAR PRIMARY KEY"),
        ("alignment_method", "VARCHAR"),
        ("tree_method", "VARCHAR"),
        ("sequence_count", "INTEGER"),
        ("alignment_length", "INTEGER"),
        ("retained_columns", "INTEGER"),
        ("bootstrap_replicates", "INTEGER"),
        ("record_json", "JSON"),
    ],
    "project_info": [("key", "VARCHAR PRIMARY KEY"), ("value", "JSON")],
    "quality_models": [
        ("sample_id", "VARCHAR PRIMARY KEY"),
        ("sequence_id", "VARCHAR"),
        ("status", "VARCHAR"),
        ("mean_plddt", "DOUBLE"),
        ("residue_count", "INTEGER"),
        ("retained_regions", "INTEGER"),
        ("retained_residues", "INTEGER"),
        ("excluded_residues", "INTEGER"),
        ("original_mapping_status", "VARCHAR"),
        ("pae_mapping_basis", "VARCHAR"),
        ("error", "VARCHAR"),
        ("record_json", "JSON"),
    ],
    "quality_regions": [
        ("sample_id", "VARCHAR PRIMARY KEY"),
        ("parent_sample_id", "VARCHAR"),
        ("sequence_id", "VARCHAR"),
        ("region_name", "VARCHAR"),
        ("selection_source", "VARCHAR"),
        ("model_start", "INTEGER"),
        ("model_end", "INTEGER"),
        ("sequence_start", "INTEGER"),
        ("sequence_end", "INTEGER"),
        ("residue_count", "INTEGER"),
        ("core_residues", "INTEGER"),
        ("core_fraction", "DOUBLE"),
        ("mean_plddt", "DOUBLE"),
        ("pae_fraction", "DOUBLE"),
        ("median_core_pae", "DOUBLE"),
        ("artificial_n_terminus", "BOOLEAN"),
        ("artificial_c_terminus", "BOOLEAN"),
        ("status", "VARCHAR"),
        ("reason", "VARCHAR"),
        ("record_json", "JSON"),
    ],
    "quality_exclusions": [
        ("sample_id", "VARCHAR"),
        ("model_start", "INTEGER"),
        ("model_end", "INTEGER"),
        ("residue_count", "INTEGER"),
        ("reason", "VARCHAR"),
    ],
    "region_comparison_plan": [
        ("reference", "VARCHAR"),
        ("mobile", "VARCHAR"),
        ("corresponding_residues", "INTEGER"),
        ("reference_region_coverage", "DOUBLE"),
        ("mobile_region_coverage", "DOUBLE"),
        ("eligible", "BOOLEAN"),
    ],
}
OPTIONAL_TABLES = {
    "quality_models",
    "quality_regions",
    "quality_exclusions",
    "region_comparison_plan",
}


def project_tables(*, root: Path, data: dict) -> dict[str, list[dict]]:
    """Collect relational records, retaining full original records as JSON.

    Args:
        root: Project file root.
        data: Loaded project.

    Returns:
        Table names mapped to row dictionaries.
    """
    records = {name: [] for name in TABLES}
    records["models"] = [dict(row, record_json=row) for row in data["models"]]
    records["pockets"] = [dict(row, record_json=row) for row in data["pockets"]]
    quality = data.get("quality_preparation", {})
    records["quality_models"] = [
        dict(row, record_json=row) for row in quality.get("model_qc", [])
    ]
    records["quality_regions"] = [
        dict(row, record_json=row) for row in quality.get("region_decisions", [])
    ]
    records["quality_exclusions"] = quality.get("exclusions", [])
    records["region_comparison_plan"] = quality.get("comparison_plan", [])
    records["sequences"] = [
        {"sequence_id": key, "sequence": value}
        for key, value in data["sequences"].items()
    ]
    for model in data["models"]:
        if not model.get("coordinates"):
            continue
        coordinates = json.loads(
            inside(root=root, relative=model["coordinates"]).read_text()
        )
        for row in coordinates:
            x, y, z = row["xyz"]
            records["residues"].append(dict(row, x=x, y=y, z=z))
    for summary in data["comparisons"]:
        path = inside(root=root, relative=summary["result_path"])
        result = json.loads(path.read_text())
        records["structure_alignments"].append(dict(result, record_json=result))
        for row in result.get("pocket_matches", []):
            records["pocket_matches"].append(
                dict(
                    row,
                    comparison_id=result["comparison_id"],
                    reference=result["reference"],
                    mobile=result["mobile"],
                    record_json=row,
                )
            )
    records["sequence_analyses"] = [
        dict(row, record_json=row) for row in data["sequence_analyses"]
    ]
    records["project_info"] = [
        {"key": key, "value": value}
        for key, value in data.items()
        if key
        not in {"models", "pockets", "sequences", "comparisons", "sequence_analyses"}
    ]
    return records


def save_project(*, root: Path, data: dict) -> None:
    """Atomically rebuild typed DuckDB tables, rejecting stale concurrent writes.

    Args:
        root: Project root.
        data: Updated project loaded at the current revision.
    """
    import fcntl

    root.mkdir(parents=True, exist_ok=True)
    with (root / ".write.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = root / "project.json"
        if current.is_file():
            revision = json.loads(current.read_text()).get("revision", 0)
            if revision != data.get("revision", 0):
                raise WorkbenchError(
                    "Project changed during this task; reload before retrying"
                )
        data["revision"] = data.get("revision", 0) + 1
        records = project_tables(root=root, data=data)
        temporary = root / "database.tmp.duckdb"
        temporary.unlink(missing_ok=True)
        try:
            with duckdb.connect(str(temporary)) as db:
                db.execute("BEGIN TRANSACTION")
                for name, schema in TABLES.items():
                    columns = ", ".join(f'"{key}" {kind}' for key, kind in schema)
                    if name == "pockets":
                        columns += ", PRIMARY KEY (sample_id, method, pocket_id)"
                    elif name == "residues":
                        columns += ", PRIMARY KEY (sample_id, residue_key)"
                    db.execute(f'CREATE TABLE "{name}" ({columns})')
                    values = []
                    for row in records[name]:
                        values.append(
                            [
                                (
                                    json.dumps(row.get(key), allow_nan=False)
                                    if kind == "JSON"
                                    else row.get(key)
                                )
                                for key, kind in schema
                            ]
                        )
                    if values:
                        frame = pd.DataFrame(values, columns=[key for key, _ in schema])
                        db.register("_incoming_rows", frame)
                        db.execute(f'INSERT INTO "{name}" SELECT * FROM _incoming_rows')
                        db.unregister("_incoming_rows")
                db.execute(
                    "CREATE VIEW v_best_pocket_per_model AS SELECT * FROM pockets WHERE"
                    " method='fpocket' AND review_rank=1"
                )
                db.execute(
                    "CREATE VIEW v_quality_screened_pockets AS SELECT * FROM pockets"
                    " WHERE quality_screen_pass IS TRUE"
                )
                db.execute(
                    "CREATE VIEW v_supported_pocket_matches AS SELECT * FROM"
                    " pocket_matches WHERE position_supported AND complete_mapping"
                )
                db.execute(
                    "CREATE VIEW v_model_summary AS SELECT m.*, (SELECT count(*) FROM"
                    " pockets p WHERE p.sample_id=m.sample_id AND p.method='fpocket')"
                    " AS fpocket_count FROM models m"
                )
                db.execute("COMMIT")
            os.replace(temporary, root / "pocket_workbench.duckdb")
            write_json(path=current, value=data)
        finally:
            temporary.unlink(missing_ok=True)


def query_table(*, root: Path, table: str) -> list[dict]:
    """Read a supported materialised app table using a fixed identifier whitelist.

    Args:
        root: Project root.
        table: Table name from the stable public schema.

    Returns:
        Records with native Python numeric values.
    """
    if table not in TABLES:
        raise WorkbenchError("Choose a documented workbench table")
    with duckdb.connect(
        str(root / "pocket_workbench.duckdb"),
        read_only=True,
        config={"enable_external_access": False},
    ) as db:
        if (
            table in OPTIONAL_TABLES
            and not db.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='main' AND table_name=?",
                [table],
            ).fetchone()[0]
        ):
            return []
        cursor = db.execute(
            f'SELECT * EXCLUDE (record_json) FROM "{table}"'
            if any(key == "record_json" for key, _ in TABLES[table])
            else f'SELECT * FROM "{table}"'
        )
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def workbook_bytes(*, tables: dict[str, list[dict]], notes: str) -> bytes:
    """Create formatted numeric Excel tables with safe literal text cells.

    Args:
        tables: Parallel tables for workbook sheets.
        notes: Methods/context for the first sheet.

    Returns:
        Complete XLSX bytes.
    """
    book = Workbook()
    cover = book.active
    cover.title = "README"
    cover.append(["Protein pocket workbench"])
    cover.append([notes])
    cover["A1"].font = Font(size=18, bold=True, color="17384D")
    cover["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    cover.column_dimensions["A"].width = 110
    cover.row_dimensions[2].height = 100
    if len(notes) > 600:
        cover["A2"] = (
            "Methods and interpretation notes are provided in the Methods sheet. Tables"
            " retain numeric metrics and literal text. Complete records are available"
            " in DuckDB and TSV."
        )
        cover["A2"].alignment = Alignment(wrap_text=True, vertical="top")
        method_sheet = book.create_sheet("Methods")
        method_sheet.column_dimensions["A"].width = 110
        for index, paragraph in enumerate(notes.splitlines(), start=1):
            cell = method_sheet.cell(index, 1, paragraph)
            cell.data_type = "s"
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            method_sheet.row_dimensions[index].height = max(
                18, 15 * (len(paragraph) // 100 + 1)
            )
    for number, (name, rows) in enumerate(tables.items(), start=1):
        sheet = book.create_sheet(name[:31])
        columns = list(
            dict.fromkeys(key for row in rows for key in row if key != "record_json")
        )
        if not columns:
            columns = ["status"]
        if len(rows) > 1048575:
            raise WorkbenchError("Excel row limit exceeded; download the TSV or DuckDB")
        sheet.append(columns)
        for row in rows:
            values = []
            for key in columns:
                value = row.get(key)
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=True)
                if isinstance(value, str) and len(value) > 32767:
                    value = value[:32700] + " [complete value in DuckDB/TSV]"
                values.append(value)
            sheet.append(values)
            for cell in sheet[sheet.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        sheet.freeze_panes = "C2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="17384D")
        for index, key in enumerate(columns, start=1):
            sheet.column_dimensions[get_column_letter(index)].width = min(
                48, max(15, len(key) + 2)
            )
            for cells in sheet.iter_cols(min_col=index, max_col=index, min_row=2):
                for cell in cells:
                    if isinstance(cell.value, float):
                        cell.number_format = (
                            "0.0%"
                            if any(
                                token in key
                                for token in (
                                    "fraction",
                                    "overlap",
                                    "coverage",
                                    "jaccard",
                                )
                            )
                            else "0.000"
                        )
        if rows:
            if columns == ["term", "definition"]:
                sheet.column_dimensions["A"].width = 34
                sheet.column_dimensions["B"].width = 110
                for row_index, row in enumerate(rows, start=2):
                    sheet.cell(row_index, 2).alignment = Alignment(
                        wrap_text=True, vertical="top"
                    )
                    sheet.row_dimensions[row_index].height = (
                        18 * (len(str(row.get("definition", ""))) // 100 + 1) + 6
                    )
            table = Table(displayName=f"Data{number}", ref=sheet.dimensions)
            table.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium2", showRowStripes=True
            )
            sheet.add_table(table)
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def export_tables(*, root: Path, output: Path) -> None:
    """Export all public tables and one formatted workbook.

    Args:
        root: Resource directory.
        output: New export directory.
    """
    if output.exists():
        raise WorkbenchError("Choose a new export directory")
    output.mkdir(parents=True)
    tables = {name: query_table(root=root, table=name) for name in TABLES}
    for name, rows in tables.items():
        write_tsv(
            path=output / f"{name}.tsv",
            rows=rows,
            columns=[key for key, _ in TABLES[name] if key != "record_json"],
        )
    (output / "pocket_workbench.xlsx").write_bytes(
        workbook_bytes(
            tables={key: value for key, value in tables.items() if key != "residues"},
            notes=(
                "All imported evidence and completed comparisons. Pocket scores have"
                " method-specific meanings. Spatial matches compare C-alpha lining"
                " residues, not cavity volumes. See Methods and Glossary."
            ),
        )
    )


def pack_project(*, root: Path, output: Path) -> Path:
    """Write a portable ZIP containing the complete project and local viewers.

    Args:
        root: Resource directory.
        output: New ZIP outside the resource root.

    Returns:
        Archive path.
    """
    load_project(root=root)
    output = output.resolve()
    if output.exists() or output.is_relative_to(root.resolve()):
        raise WorkbenchError("Choose a new ZIP path outside the project")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise WorkbenchError("A project archive cannot contain symbolic links")
            if (
                path.is_file()
                and not path.name.startswith(".")
                and ".tmp" not in path.name
            ):
                archive.write(
                    path, arcname=f"{root.name}/{path.relative_to(root).as_posix()}"
                )
    return output
