"""Portable, offline review exports built from completed analytical evidence."""

from __future__ import annotations

import hashlib
import html
import json
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path

from .annotations import pocket_alignment_data, pocket_alignment_document
from .core import WorkbenchError, digest_file, inside, load_project, utc_now, write_tsv
from .database import export_tables, pack_project, workbook_bytes
from .evidence import aligner_agreement, comparison_audit
from .groups import AF3_INSPECTOR_URL, inspector_bundle
from .help_content import glossary_rows, methods_text
from .importing import read_fasta
from .sequences import fasta_text
from .viewers import model_viewer_records, structure_document

LOGGER = logging.getLogger(__name__)
STYLE = """
body{font:15px system-ui;color:#17384d;background:#f3f7fa;margin:0}
header{background:#12394e;color:white;padding:28px max(24px,5vw)}
main{max-width:1500px;margin:auto;padding:24px}h1{margin:0 0 8px}
section{background:white;border:1px solid #dae4ec;border-radius:10px;
padding:18px;margin-bottom:18px;overflow:auto}table{border-collapse:collapse;
width:100%;font-size:12px}th,td{text-align:left;padding:9px;border-bottom:1px solid
#e0e8ed;vertical-align:top}th{background:#e9f2f7;position:sticky;top:0}
a{color:#076b9a}p{line-height:1.55}input{padding:9px;width:350px;max-width:100%}
.count{display:inline-block;padding:8px 16px;background:#e7f3f8;
border-radius:7px;margin:5px}.note{font-size:12px;color:#48677b}
"""


def html_table(*, rows: list[dict], columns: list[str]) -> str:
    """Encode a review table with literal, escaped values.

    Args:
        rows: JSON-compatible records.
        columns: Ordered keys to display.

    Returns:
        Searchable HTML table with no executable input content.
    """
    headings = "".join(f"<th>{html.escape(k.replace('_', ' '))}</th>" for k in columns)
    cells = "".join(
        "<tr>"
        + "".join(
            "<td>"
            + html.escape(str(row.get(k) if row.get(k) is not None else "Unknown"))
            + "</td>"
            for k in columns
        )
        + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{headings}</tr></thead><tbody>{cells}</tbody></table>"


def export_review(*, root: Path, output: Path) -> Path:
    """Publish a complete HTML/Excel/DuckDB review and reusable project archive.

    Args:
        root: Completed resource, including coordinates and computed analyses.
        output: New review directory outside the source resource.

    Returns:
        Review directory; a sibling ZIP is published at the same time.
    """
    root, output = root.resolve(), output.expanduser().resolve()
    data = load_project(root=root)
    archive_path = output.with_suffix(".zip")
    if (
        output.exists()
        or archive_path.exists()
        or output.is_relative_to(root)
        or root.is_relative_to(output)
    ):
        raise WorkbenchError("Choose a new review directory outside the resource")
    for path in (root / "jobs").glob("*/status.json"):
        status = json.loads(path.read_text())
        if (
            status.get("status") in {"queued", "running"}
            and status.get("task") != "review"
        ):
            raise WorkbenchError("Finish active analysis jobs before exporting")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".review_", dir=output.parent))
    temporary_zip = staging.with_suffix(".zip")
    try:
        LOGGER.info("Exporting tables and formatted Excel")
        export_tables(root=root, output=staging / "tables")
        shutil.copy2(
            root / "pocket_workbench.duckdb", staging / "pocket_workbench.duckdb"
        )
        (staging / "representatives.fasta").write_text(
            fasta_text(records=data["sequences"])
        )
        (staging / "METHODS.txt").write_text(methods_text())
        if data.get("quality_preparation"):
            quality = inside(
                root=root, relative=data["quality_preparation"]["audit_directory"]
            )
            if quality.is_dir():
                shutil.copytree(quality, staging / "quality")
        write_tsv(
            path=staging / "tables" / "glossary.tsv",
            rows=glossary_rows(),
            columns=["term", "definition"],
        )
        audit = comparison_audit(root=root, data=data)
        agreement = aligner_agreement(rows=audit)
        write_tsv(
            path=staging / "tables" / "aligner_agreement.tsv",
            rows=agreement,
            columns=list(agreement[0]) if agreement else ["reference", "mobile"],
        )
        write_tsv(
            path=staging / "tables" / "rank_one_top_k_audit.tsv",
            rows=audit,
            columns=list(audit[0]) if audit else ["comparison_id", "status"],
        )
        (staging / "review_evidence.xlsx").write_bytes(
            workbook_bytes(
                tables={
                    "Rank_one_top_k": audit,
                    "Aligner_agreement": agreement,
                    "Glossary": glossary_rows(),
                },
                notes=methods_text(),
            )
        )
        model_links, comparison_links, alignment_links, group_links = [], [], [], []
        model_lookup = {row["sample_id"]: row for row in data["models"]}
        for model in data["models"]:
            identifier = model["sample_id"]
            if not model.get("prepared_model"):
                model_links.append(
                    f"<li>{html.escape(identifier)} — coordinates unavailable</li>"
                )
                continue
            directory = staging / "models"
            directory.mkdir(exist_ok=True)
            pdb = inside(root=root, relative=model["prepared_model"]).read_text()
            document = structure_document(
                reference_pdb=pdb,
                reference_label=identifier,
                reference_metadata=model_viewer_records(
                    root=root, model=model, pockets=data["pockets"]
                ),
                summary=(
                    (
                        "Cropped contiguous-region input; inspect the quality audit and"
                        " pocket context flags. All predicted pockets remain visible. "
                        if model.get("input_scope") == "cleaned_region"
                        else ""
                    )
                    + "Imported per-model pocket evidence. Ranks apply within this"
                    " model."
                ),
            )
            (directory / f"{identifier}.html").write_text(document)
            (directory / f"{identifier}.pdb").write_text(pdb)
            model_links.append(
                f'<li><a href="models/{identifier}.html">{html.escape(identifier)}</a>'
                f' · <a href="models/{identifier}.pdb">PDB</a></li>'
            )
        for summary in data["comparisons"]:
            if summary["status"] != "complete":
                continue
            result = json.loads(
                inside(root=root, relative=summary["result_path"]).read_text()
            )
            identifier = result["comparison_id"]
            directory = staging / "comparisons" / identifier
            directory.mkdir(parents=True)
            reference = model_lookup[result["reference"]]
            mobile = model_lookup[result["mobile"]]
            document = structure_document(
                reference_pdb=inside(
                    root=root, relative=reference["prepared_model"]
                ).read_text(),
                mobile_pdb=inside(
                    root=root, relative=result["mobile_aligned"]
                ).read_text(),
                reference_label=result["reference"],
                mobile_label=result["mobile"],
                reference_metadata=model_viewer_records(
                    root=root, model=reference, pockets=data["pockets"]
                ),
                mobile_metadata=model_viewer_records(
                    root=root, model=mobile, pockets=data["pockets"]
                ),
                match=next(iter(result["pocket_matches"]), None),
                summary=(
                    f"{result['engine']} · {result['scope']} · RMSD"
                    f" {result['rmsd']:.3f} Å · {result['aligned_atoms']} aligned Cα"
                    " atoms."
                ),
            )
            (directory / "viewer.html").write_text(document)
            shutil.copy2(
                inside(root=root, relative=result["result_path"]),
                directory / "result.json",
            )
            shutil.copy2(
                inside(root=root, relative=result["mobile_aligned"]),
                directory / "mobile_aligned.pdb",
            )
            comparison_links.append(
                f'<li><a href="comparisons/{identifier}/viewer.html">'
                f'{html.escape(result["reference"])} / {html.escape(result["mobile"])}'
                f' · {html.escape(result["engine"])} · {html.escape(result["scope"])}'
                "</a></li>"
            )
        for analysis in data["sequence_analyses"]:
            directory = staging / "alignments" / analysis["analysis_id"]
            source = inside(root=root, relative=analysis["alignment_path"]).parent
            shutil.copytree(source, directory)
            payload = pocket_alignment_data(
                root=root,
                data=data,
                aligned_records=read_fasta(
                    path=inside(root=root, relative=analysis["alignment_path"]),
                    aligned=True,
                ),
            )
            (directory / "pocket_alignment.html").write_text(
                pocket_alignment_document(payload=payload)
            )
            write_tsv(
                path=directory / "pocket_annotations.tsv",
                rows=payload["annotations"],
                columns=(
                    list(payload["annotations"][0])
                    if payload["annotations"]
                    else ["sample_id", "alignment_column"]
                ),
            )
            prefix = f"alignments/{analysis['analysis_id']}"
            alignment_links.append(
                f'<li>{html.escape(analysis["analysis_id"])} · <a'
                f' href="{prefix}/pocket_alignment.html">Pocket-annotated FASTA</a> ·'
                f' <a href="{prefix}/alignment_tree.html">Alignment and tree</a> · <a'
                f' href="{prefix}/pocket_annotations.tsv">Residue audit TSV</a></li>'
            )
        LOGGER.info("Packing the reusable app resource")
        groups = sorted(
            {
                m.get("hog_id") or m.get("group_id") or "Ungrouped"
                for m in data["models"]
            }
        )
        (staging / "model_groups").mkdir()
        for group in groups:
            members = [
                m
                for m in data["models"]
                if (m.get("hog_id") or m.get("group_id") or "Ungrouped") == group
            ]
            filename = (
                "group_"
                + hashlib.sha256(group.encode()).hexdigest()[:12]
                + "_inspector.zip"
            )
            (staging / "model_groups" / filename).write_bytes(
                inspector_bundle(root=root, models=members)
            )
            group_links.append(
                f'<li>{html.escape(group)} · <a href="model_groups/{filename}">Model'
                f" ZIP for manual Inspector upload</a> · {len(members)} models</li>"
            )
        pack_project(root=root, output=staging / "app_resource.zip")
        glossary_html = html_table(rows=glossary_rows(), columns=["term", "definition"])
        (staging / "methods_glossary.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>Methods and glossary</title>"
            f"<style>{STYLE}</style><main><h1>Methods and glossary</h1>"
            f"<section><pre style='white-space:pre-wrap'>{html.escape(methods_text())}"
            f"</pre></section><section>{glossary_html}</section></main>"
        )
        evidence = html_table(
            rows=audit,
            columns=[
                "reference",
                "mobile",
                "engine",
                "scope",
                "status",
                "rank_one_position",
                "rank_one_position_and_fold",
                "top_k_position",
                "top_k_tested_pairs",
                "minimum_tm",
                "best_tested_overlap",
            ],
        )
        title = html.escape(data["title"])
        index = (
            "<!doctype html><html lang='en-GB'><meta charset='utf-8'><meta"
            " name='viewport'"
            f" content='width=device-width,initial-scale=1'><title>{title}</title>"
            f"<style>{STYLE}</style><header><h1>{title}</h1>Portable"
            " protein pocket review</header><main><section><span"
            f" class='count'>{len(data['models'])} models</span><span"
            f" class='count'>{len(data['sequences'])} sequences</span><span"
            f" class='count'>{len(data['comparisons'])} comparisons</span><p>Unzip this"
            " entire folder, then open index.html. Interactive pages work offline in a"
            " browser with WebGL. No cluster account is required.</p><p><a"
            " href='tables/pocket_workbench.xlsx'>Complete Excel results</a> · <a"
            " href='review_evidence.xlsx'>Review audit and glossary Excel</a> · <a"
            " href='pocket_workbench.duckdb'>DuckDB</a> · <a"
            " href='representatives.fasta'>Representative FASTA</a> · <a"
            " href='methods_glossary.html'>Methods and glossary</a> · <a"
            " href='app_resource.zip'>Reopen in the"
            " app</a></p>"
            + (
                "<p><a href='quality/index.html'>Input quality and region audit</a> ·"
                " <a href='quality/quality_audit.xlsx'>Quality audit Excel</a>."
                " Automatically selected regions are candidates, not annotated domains."
                " Fit coverage refers to the cropped input region. All predicted"
                " pockets are retained; comparisons screen cut ends and uncertain"
                " context.</p>"
                if data.get("quality_preparation")
                else ""
            )
            + "</section><section><h2>Find a model, comparison or"
            " sequence</h2><input id='search' type='search' placeholder='Search"
            " identifiers'><p class='note'>Rank one and alternative-pocket sensitivity"
            " are separate. Not assessed is retained when the requested ranks,"
            " coordinates or fit are unavailable. Position and fold evidence do not"
            " establish binding.</p></section><section><h2>Models and predicted"
            f" pockets</h2><ul>{''.join(model_links)}</ul></section>"
            "<section><h2>Structure"
            " alignments and"
            f" pockets</h2><ul>{''.join(comparison_links)}</ul></section>"
            "<section><h2>FASTA"
            " alignments and"
            f" trees</h2><ul>{''.join(alignment_links)}</ul></section>"
            "<section><h2>Structural"
            f" evidence audit</h2>{evidence}</section><section><h2>HOG / model group"
            f" comparison</h2><p><a href='{AF3_INSPECTOR_URL}'>Open the external"
            " AlphaFold 3 Multi-Model Inspector</a>. Download a group ZIP and choose"
            " it manually on the external site. Prepared chains and pLDDT are"
            " retained; PAE and AF3-specific metrics are not supplied. The external"
            " source requires internet"
            f" access.</p><ul>{''.join(group_links)}</ul></section>"
            "<section><h2>Dual-aligner"
            " agreement</h2>"
            + html_table(
                rows=agreement,
                columns=[
                    "reference",
                    "mobile",
                    "available_aligners",
                    "rank_one_both_aligners",
                    "rank_one_conserved_both_aligners",
                    "top_k_both_aligners",
                    "top_k_same_member_pockets",
                ],
            )
            + f"</section><p class='note'>Exported {utc_now()}. "
            "Checksums are recorded in SHA256SUMS.tsv.</p></main>"
            "<script>document.getElementById('search').oninput=function(){"
            "const q=this.value.toLowerCase();document.querySelectorAll('li,tbody tr')"
            ".forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q));};"
            "</script></html>"
        )
        (staging / "index.html").write_text(index)
        (staging / "README.txt").write_text(
            "Extract the entire ZIP, then open index.html in Chrome, Firefox, Edge "
            "or Safari with WebGL enabled. No Python or server account is required.\n"
            "To continue analyses in the workbench, extract app_resource.zip and "
            "open the resulting project directory containing project.json.\n"
            "The HTML review does not execute new predictions or alignments.\n"
        )
        if load_project(root=root)["revision"] != data["revision"]:
            raise WorkbenchError(
                "Project changed during export; retry after analyses finish"
            )
        write_tsv(
            path=staging / "SHA256SUMS.tsv",
            rows=[
                {
                    "path": p.relative_to(staging).as_posix(),
                    "sha256": digest_file(path=p),
                }
                for p in sorted(staging.rglob("*"))
                if p.is_file()
            ],
            columns=["path", "sha256"],
        )
        with zipfile.ZipFile(
            temporary_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    archive.write(
                        path, f"{output.name}/{path.relative_to(staging).as_posix()}"
                    )
        staging.rename(output)
        temporary_zip.rename(archive_path)
        LOGGER.info("Published offline review: %s", archive_path)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        temporary_zip.unlink(missing_ok=True)
        raise
    return output
