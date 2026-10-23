"""Named-option, batch-only cleaning, pocket prediction and review preparation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import logging
import os
import shutil
import socket
from dataclasses import asdict
from pathlib import Path

from . import __version__
from ._pipeline.io import load_samples
from ._pipeline.models import Settings
from ._pipeline.pipeline import run_pipeline
from ._pipeline.tools import inspect_tools
from .comparison import compare_batch, sequence_pairs
from .core import (
    ComparisonSettings,
    WorkbenchError,
    digest_file,
    inside,
    load_project,
    safe_id,
    utc_now,
    write_json,
    write_tsv,
)
from .database import save_project, workbook_bytes
from .importing import (
    import_project,
    map_sequence,
    normalise_model,
    read_fasta,
    read_report,
)
from .quality import (
    CleaningSettings,
    find_pae_file,
    pocket_context,
    read_pae,
    select_regions,
    write_region_cif,
)
from .reporting import export_review, html_table
from .runtime import available_cpus
from .sequences import analyse_sequences, fasta_text

LOGGER = logging.getLogger(__name__)


def discover_models(*, directory: Path) -> list[Path]:
    """Discover unique original model IDs while excluding MSA/template directories.

    Args:
        directory: Original AlphaFold model root.

    Returns:
        Stable sorted PDB/mmCIF input paths.
    """
    if not directory.is_dir():
        raise WorkbenchError(f"Model directory does not exist: {directory}")
    paths = sorted(
        p.resolve()
        for p in directory.rglob("*")
        if p.is_file()
        and not p.is_symlink()
        and p.suffix.lower() in {".pdb", ".cif", ".mmcif"}
        and not any(
            part.lower() in {"msas", "templates"}
            for part in p.relative_to(directory).parts
        )
    )
    names = [safe_id(value=p.stem) for p in paths]
    if not paths or len(names) != len(set(n.casefold() for n in names)):
        raise WorkbenchError("Supply coordinate models with unique filename stems")
    return paths


def explicit_regions(
    *, rows: list[dict], parent: dict, residues: list[dict]
) -> list[dict]:
    """Translate explicit full-sequence or model positions without guessing offsets.

    Args:
        rows: Curated region TSV rows.
        parent: Exact parent/FASTA mapping record.
        residues: Full parent coordinate map.

    Returns:
        Inclusive zero-based model-index intervals for this parent.
    """
    selected = []
    for row in rows:
        if row.get("sample_id"):
            matches = row["sample_id"] == parent["sample_id"]
        else:
            matches = row.get("sequence_id") == parent["sequence_id"]
        if not matches:
            continue
        start, end = int(row["start"]), int(row["end"])
        if not 1 <= start <= end:
            raise WorkbenchError(
                "Explicit region start/end must be positive and ordered"
            )
        system = row.get("coordinate_system") or "sequence"
        if system == "sequence":
            if parent["original_mapping_status"] not in {
                "exact_sequence",
                "exact_explicit",
                "unique_exact_fragment_explicit",
            }:
                raise WorkbenchError(
                    "Sequence-coordinate regions require an exact supplied FASTA"
                    " mapping"
                )
            positions = {r["sequence_position"]: i for i, r in enumerate(residues)}
            if start not in positions or end not in positions:
                raise WorkbenchError(
                    "Explicit region is not completely covered by the model"
                )
            start, end = positions[start], positions[end]
        elif system == "model":
            start, end = start - 1, end - 1
        else:
            raise WorkbenchError("Region coordinate_system must be sequence or model")
        selected.append(
            {
                "start_index": start,
                "end_index": end,
                "region_name": row.get("region_name") or "explicit_region",
            }
        )
    ordered = sorted(selected, key=lambda r: r["start_index"])
    if any(a["end_index"] >= b["start_index"] for a, b in zip(ordered, ordered[1:])):
        raise WorkbenchError(
            "Explicit regions overlap; provide independent complete units"
        )
    return ordered


def prepare_inputs(
    *,
    paths: list[Path],
    root: Path,
    fasta: Path | None,
    mapping: Path | None,
    regions_file: Path | None,
    settings: CleaningSettings,
    chain: str,
) -> dict:
    """Prepare confidence-supported contiguous inputs with original-numbering audits.

    Args:
        paths: Discovered original coordinate files.
        root: New run directory, owned by this workflow.
        fasta: Optional representative full-sequence FASTA.
        mapping: Optional exact sample_id/sequence_id/chain TSV.
        regions_file: Optional curated region TSV.
        settings: Explicit confidence/PAE policy.
        chain: Default target protein chain.

    Returns:
        Parent/region metadata and paths needed for prediction and app import.
    """
    supplied_sequences = read_fasta(path=fasta) if fasta else {}
    sequences = dict(supplied_sequences)
    original_sequences = list(supplied_sequences)
    mapping_rows, curated = {}, []
    if mapping:
        with mapping.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if not row.get("sample_id") or row["sample_id"] in mapping_rows:
                    raise WorkbenchError("Mapping needs unique sample_id values")
                mapping_rows[row["sample_id"]] = row
    if regions_file:
        with regions_file.open(newline="", encoding="utf-8-sig") as handle:
            curated = list(csv.DictReader(handle, delimiter="\t"))
        if not curated or any(
            not r.get("region_name")
            or not (r.get("sample_id") or r.get("sequence_id"))
            or not r.get("start")
            or not r.get("end")
            for r in curated
        ):
            raise WorkbenchError(
                "Regions TSV needs sample_id or sequence_id, region_name, start, end"
            )
    parents, regions, model_qc, region_qc, exclusions, manifest, app_mapping = (
        {},
        {},
        [],
        [],
        [],
        [],
        [],
    )
    for path in paths:
        identifier = path.stem
        LOGGER.info("Assessing original model %s", identifier)
        record = {
            "sample_id": identifier,
            "source_path": str(path),
            "source_sha256": digest_file(path=path),
        }
        try:
            directory = root / "01_quality" / identifier
            full_pdb = directory / "full_prepared.pdb"
            rows, metadata = normalise_model(
                source=path,
                destination=full_pdb,
                sample_id=identifier,
                chain=mapping_rows.get(identifier, {}).get("chain") or chain,
                confidence="plddt",
            )
            sequence = "".join(r["amino_acid"] for r in rows)
            sequence_id, mapping_status, offset = map_sequence(
                sequence=sequence,
                sequences=supplied_sequences,
                explicit_id=mapping_rows.get(identifier, {}).get("sequence_id", ""),
            )
            if not sequence_id:
                sequence_id = (
                    "model_sequence_"
                    + hashlib.sha256(sequence.encode()).hexdigest()[:16]
                )
                sequences[sequence_id] = sequence
                offset = 0
            for i, row in enumerate(rows):
                row["sequence_position"], row["model_position"] = i + 1 + offset, i + 1
            pae_path = find_pae_file(model_path=path)
            pae, pae_basis = (
                read_pae(path=pae_path, residues=rows)
                if pae_path
                else (None, "missing")
            )
            parent = {
                "sample_id": identifier,
                "sequence_id": sequence_id,
                "original_mapping_status": mapping_status,
                "sequence": sequences[sequence_id],
                "model_sequence": sequence,
                "sequence_offset": offset,
                "residue_count": len(rows),
                "pae_path": str(pae_path) if pae_path else None,
                "pae_mapping_basis": pae_basis,
                "pae_sha256": digest_file(path=pae_path) if pae_path else None,
            }
            chosen = (
                explicit_regions(rows=curated, parent=parent, residues=rows)
                if regions_file
                else None
            )
            decisions = (
                select_regions(
                    residues=rows, pae=pae, settings=settings, explicit=chosen
                )
                if not regions_file or chosen
                else []
            )
            retained = set()
            for index, decision in enumerate(decisions, start=1):
                child = (
                    identifier[:92]
                    + "__"
                    + hashlib.sha256(identifier.encode()).hexdigest()[:8]
                    + f"_r{index:03d}"
                )
                start, end = decision["start_index"], decision["end_index"]
                decision.update(
                    sample_id=child,
                    parent_sample_id=identifier,
                    sequence_id=sequence_id,
                    sequence_start=rows[start]["sequence_position"],
                    sequence_end=rows[end]["sequence_position"],
                    parent_residue_count=len(rows),
                    pae_mapping_basis=pae_basis,
                    original_mapping_status=mapping_status,
                )
                # A model supplied as an exact FASTA fragment also has cut ends.
                decision["artificial_n_terminus"] |= offset > 0
                decision["artificial_c_terminus"] |= offset + len(rows) < len(
                    sequences[sequence_id]
                )
                if decision["status"] != "retained":
                    region_qc.append(dict(decision))
                    continue
                retained.update(range(start, end + 1))
                child_path = root / "02_cleaned_models" / f"{child}.cif"
                write_region_cif(
                    prepared_pdb=full_pdb,
                    residues=rows,
                    start=start,
                    end=end,
                    output=child_path,
                )
                fragment = sequence[start : end + 1]
                target = sequences[sequence_id]
                target_id = sequence_id
                if target.find(fragment) != target.rfind(fragment):
                    target_id = (
                        "region_sequence_"
                        + hashlib.sha256(fragment.encode()).hexdigest()[:16]
                    )
                    sequences[target_id] = fragment
                    decision["fragment_mapping_status"] = (
                        "ambiguous_in_parent;separate_fragment_sequence"
                    )
                else:
                    decision["fragment_mapping_status"] = "unique_exact_parent_fragment"
                decision["app_sequence_id"] = target_id
                region_qc.append(dict(decision))
                regions[child] = decision
                manifest.append(
                    {
                        "sample_id": child,
                        "model_path": str(child_path),
                        "sequence_id": target_id,
                        "cluster": "quality_regions",
                    }
                )
                app_mapping.append(
                    {
                        "sample_id": child,
                        "sequence_id": target_id,
                        "group_id": "quality_regions",
                        **{
                            key: mapping_rows.get(identifier, {}).get(key, "")
                            for key in ("hog_id", "source_accession", "source_url")
                        },
                    }
                )
            for keep, group in itertools.groupby(
                enumerate(rows), key=lambda item: item[0] in retained
            ):
                if keep:
                    continue
                removed = list(group)
                exclusions.append(
                    {
                        "sample_id": identifier,
                        "model_start": removed[0][0] + 1,
                        "model_end": removed[-1][0] + 1,
                        "residue_count": len(removed),
                        "reason": "outside_retained_contiguous_regions",
                    }
                )
            write_json(path=directory / "residues.json", value=rows)
            parents[identifier] = parent
            record.update(
                metadata,
                sequence_id=sequence_id,
                original_mapping_status=mapping_status,
                pae_mapping_basis=pae_basis,
                retained_regions=sum(d["status"] == "retained" for d in decisions),
                retained_residues=len(retained),
                excluded_residues=len(rows) - len(retained),
                status="prepared" if retained else "no_retained_region",
            )
        except (ValueError, OSError, RuntimeError) as error:
            LOGGER.exception("Quality preparation failed for %s", identifier)
            record.update(status="failed", error=str(error))
        model_qc.append(record)
    audit = root / "01_quality"
    audit.mkdir(exist_ok=True)
    tables = {
        "Model_QC": model_qc,
        "Region_decisions": region_qc,
        "Excluded_ranges": exclusions,
    }
    for name, records in tables.items():
        write_tsv(
            path=audit / f"{name}.tsv",
            rows=records,
            columns=sorted({k for r in records for k in r}) or ["sample_id", "status"],
        )
    (audit / "quality_audit.xlsx").write_bytes(
        workbook_bytes(
            tables=tables,
            notes=(
                "Contiguous confidence-supported candidate regions; automatic"
                " selections are not annotated biological domains. Short internal loops"
                " are retained. Thresholds are heuristics. PAE and cut-end/context"
                " flags are recorded.\nRun-specific settings:\n"
                + "\n".join(
                    f"{key}: {value}" for key, value in asdict(settings).items()
                )
            ),
        )
    )
    audit_columns = {
        "Model_QC": [
            "sample_id",
            "status",
            "residue_count",
            "mean_plddt",
            "retained_regions",
            "retained_residues",
            "excluded_residues",
            "original_mapping_status",
            "pae_mapping_basis",
            "error",
        ],
        "Region_decisions": [
            "parent_sample_id",
            "sample_id",
            "region_name",
            "selection_source",
            "sequence_start",
            "sequence_end",
            "residue_count",
            "core_fraction",
            "mean_plddt",
            "pae_fraction",
            "status",
            "reason",
            "artificial_n_terminus",
            "artificial_c_terminus",
        ],
        "Excluded_ranges": [
            "sample_id",
            "model_start",
            "model_end",
            "residue_count",
            "reason",
        ],
    }
    (audit / "index.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Input quality"
        " audit</title><style>body{font:14px"
        " system-ui;margin:25px;color:#17384d}table{border-collapse:collapse}"
        "td,th{padding:8px;border:1px"
        " solid #ccd9e2}.scroll{overflow:auto}th{background:#e9f2f7}"
        "</style><h1>Input quality and region audit</h1><p>Automatic"
        " regions are confidence-supported candidates, not confirmed biological"
        " domains. Review the decisions and cut-end flags. Original inputs are"
        " unchanged.</p><p><a href='quality_audit.xlsx'>Excel audit</a></p>"
        + "".join(
            "<h2>"
            + name
            + "</h2><p><a href='"
            + name
            + ".tsv'>Complete TSV</a></p><div class='scroll'>"
            + html_table(rows=records, columns=audit_columns[name])
            + "</div>"
            for name, records in tables.items()
        )
    )
    fasta_path, manifest_path, mapping_path = (
        root / "representatives.fasta",
        root / "prediction_manifest.tsv",
        root / "app_mapping.tsv",
    )
    fasta_path.write_text(fasta_text(records=sequences))
    write_tsv(
        path=manifest_path,
        rows=manifest,
        columns=["sample_id", "model_path", "sequence_id", "cluster"],
    )
    write_tsv(
        path=mapping_path,
        rows=app_mapping,
        columns=[
            "sample_id",
            "sequence_id",
            "group_id",
            "hog_id",
            "source_accession",
            "source_url",
        ],
    )
    result = {
        "parents": parents,
        "regions": regions,
        "model_qc": model_qc,
        "region_decisions": region_qc,
        "exclusions": exclusions,
        "tree_sequence_ids": sorted(
            set(original_sequences + [p["sequence_id"] for p in parents.values()])
        ),
        "fasta": str(fasta_path),
        "manifest": str(manifest_path),
        "mapping": str(mapping_path),
    }
    result["checksums"] = {
        p.relative_to(root).as_posix(): digest_file(path=p)
        for base in (audit, root / "02_cleaned_models")
        for p in sorted(base.rglob("*"))
        if p.is_file()
    }
    for p in (fasta_path, manifest_path, mapping_path):
        result["checksums"][p.relative_to(root).as_posix()] = digest_file(path=p)
    write_json(path=root / "preparation.json", value=result)
    return result


def plan_region_comparisons(
    *, preparation: dict, mode: str, minimum_overlap: float = 0.7
) -> tuple[list[tuple[str, str]], dict[str, str], list[dict]]:
    """Compare corresponding regions using full parent sequence correspondence.

    Args:
        preparation: Exact parent sequences and retained region coordinates.
        mode: matched_reference, matched_all or none.
        minimum_overlap: Required correspondence fraction in both complete regions.

    Returns:
        Eligible pairs, computational region groups and full eligibility audit.
    """
    if (
        mode not in {"matched_reference", "matched_all", "none"}
        or not 0 < minimum_overlap <= 1
    ):
        raise WorkbenchError("Invalid region comparison plan")
    regions, parents = preparation["regions"], preparation["parents"]
    grouped = {}
    for name, region in regions.items():
        grouped.setdefault(region["parent_sample_id"], []).append(name)
    edges, audit, correspondences = [], [], {}
    for a, b in itertools.combinations(sorted(grouped), 2):
        parent_a, parent_b = parents[a], parents[b]
        key = (parent_a["sequence"], parent_b["sequence"])
        if key not in correspondences:
            correspondences[key] = sequence_pairs(reference=key[0], mobile=key[1])
        correspondence = correspondences[key]
        for ref, mob in itertools.product(grouped[a], grouped[b]):
            x, y = regions[ref], regions[mob]
            count = sum(
                x["sequence_start"] <= i + 1 <= x["sequence_end"]
                and y["sequence_start"] <= j + 1 <= y["sequence_end"]
                for i, j in correspondence
            )
            cov_a, cov_b = count / x["residue_count"], count / y["residue_count"]
            explicit_ok = (
                x["selection_source"] != "explicit_region"
                or y["selection_source"] != "explicit_region"
                or x["region_name"] == y["region_name"]
            )
            eligible = min(cov_a, cov_b) >= minimum_overlap and explicit_ok
            audit.append(
                {
                    "reference": ref,
                    "mobile": mob,
                    "corresponding_residues": count,
                    "reference_region_coverage": cov_a,
                    "mobile_region_coverage": cov_b,
                    "eligible": eligible,
                }
            )
            if eligible:
                edges.append((ref, mob))
    adjacency = {name: set() for name in regions}
    for a, b in edges:
        adjacency[a].add(b)
        adjacency[b].add(a)
    groups, pairs, visited = {}, [], set()
    for name in sorted(regions):
        if name in visited:
            continue
        component, pending = set(), [name]
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(adjacency[current] - component)
        visited |= component
        group = f"corresponding_region_{len(set(groups.values()))+1:03d}"
        groups.update(dict.fromkeys(component, group))
        if mode == "matched_reference" and len(component) > 1:
            reference = min(
                component,
                key=lambda k: (-len(adjacency[k]), -regions[k]["mean_plddt"], k),
            )
            pairs.extend((reference, mobile) for mobile in sorted(adjacency[reference]))
    if mode == "matched_all":
        pairs = edges
    return pairs if mode != "none" else [], groups, audit


def enrich_resource(
    *,
    resource: Path,
    preparation: dict,
    settings: CleaningSettings,
    groups: dict[str, str],
    comparison_audit: list[dict] | None = None,
) -> None:
    """Attach original-region provenance and conservative cavity-context annotations.

    Args:
        resource: Imported new prediction resource.
        preparation: Parent and region preparation records.
        settings: Quality/context thresholds.
        groups: Computational correspondence groups, never HOG assertions.
        comparison_audit: Direct corresponding-region eligibility evidence.
    """
    data = load_project(root=resource)
    for model in data["models"]:
        region = preparation["regions"][model["sample_id"]]
        model.update(
            parent_sample_id=region["parent_sample_id"],
            input_scope="cleaned_region",
            region_name=region["region_name"],
            group_id=groups[model["sample_id"]],
            original_start=region["sequence_start"],
            original_end=region["sequence_end"],
            parent_residue_count=region["parent_residue_count"],
            selection_source=region["selection_source"],
            original_mapping_status=region["original_mapping_status"],
        )
        if not model.get("coordinates"):
            continue
        residues = json.loads(
            inside(root=resource, relative=model["coordinates"]).read_text()
        )
        for pocket in (
            p for p in data["pockets"] if p["sample_id"] == model["sample_id"]
        ):
            pocket.update(
                pocket_context(
                    pocket=pocket, residues=residues, region=region, settings=settings
                )
            )
    data["quality_preparation"] = {
        "settings": asdict(settings),
        "audit_directory": "quality",
        "interpretation": (
            "Automatic confidence-supported regions are not annotated domains."
        ),
        "model_qc": preparation["model_qc"],
        "region_decisions": preparation["region_decisions"],
        "exclusions": preparation["exclusions"],
        "comparison_plan": comparison_audit or [],
    }
    save_project(root=resource, data=data)


def run_workflow(*, args: argparse.Namespace) -> int:
    """Run or resume the isolated quality/prediction/analysis workflow.

    Args:
        args: Validated named command options.

    Returns:
        Zero for a completed run, two for explicitly retained partial results.
    """
    import fcntl

    root, models = (
        args.output.expanduser().resolve(),
        args.models.expanduser().resolve(),
    )
    for name in ("fasta", "mapping", "regions"):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.expanduser().resolve())
    if root.is_relative_to(models) or models.is_relative_to(root):
        raise WorkbenchError(
            "Output must be separate from the original model directory"
        )
    settings = CleaningSettings(
        core_plddt=args.core_plddt,
        max_low_gap=args.max_low_gap,
        min_length=args.min_region_length,
        min_core=args.min_core,
        padding=args.padding,
        max_pae=args.max_pae,
        require_pae=not args.allow_missing_pae,
    )
    ComparisonSettings(top_pockets=args.top_pockets)
    Settings(threads=args.threads, timeout=args.timeout)
    if not 0 <= args.bootstrap <= 200 or not 0 < args.sequence_overlap <= 1:
        raise WorkbenchError("Choose 0–200 bootstraps and sequence overlap in (0, 1]")
    if (
        not 1 <= args.threads <= available_cpus()
        or not 1 <= args.workers <= available_cpus()
    ):
        raise WorkbenchError("Threads/workers exceed the available CPU allocation")
    paths = discover_models(directory=models)
    sources = []
    for path in paths:
        pae = find_pae_file(model_path=path)
        sources.append(
            {
                "model": str(path),
                "model_sha256": digest_file(path=path),
                "pae": str(pae) if pae else None,
                "pae_sha256": digest_file(path=pae) if pae else None,
            }
        )
    identity = {
        "version": __version__,
        "cleaning": asdict(settings),
        "sources": sources,
        "workflow_code": {
            p.name: digest_file(path=p)
            for p in (Path(__file__), Path(__file__).with_name("quality.py"))
        },
        "chain": args.chain,
        "comparison_mode": args.comparison_mode,
        "prediction_threads": args.threads,
        "prediction_timeout": args.timeout,
        "bootstrap": args.bootstrap,
        "top_pockets": args.top_pockets,
        "sequence_overlap": args.sequence_overlap,
        "extra_inputs": {
            name: {"path": str(value.resolve()), "sha256": digest_file(path=value)}
            for name in ("fasta", "mapping", "regions")
            if (value := getattr(args, name))
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode()
    ).hexdigest()
    state_path = root / "workflow.json"
    if (
        root.exists()
        and any(root.iterdir())
        and not (args.resume and state_path.is_file())
    ):
        raise WorkbenchError("Choose a new results folder or explicitly use --resume")
    old = json.loads(state_path.read_text()) if state_path.is_file() else {}
    if old and old.get("fingerprint") != fingerprint:
        raise WorkbenchError(
            "Resume refused: sources, cleaning or analysis settings changed"
        )
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".workflow.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WorkbenchError(
                "This results directory already has an active workflow"
            ) from error
        handler = logging.FileHandler(root / "workflow.log")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logging.getLogger().addHandler(handler)
        state = dict(
            old,
            fingerprint=fingerprint,
            identity=identity,
            status="running",
            hostname=socket.gethostname(),
            pid=os.getpid(),
            started_utc=utc_now(),
        )
        try:
            state["stage"] = "quality_preparation"
            write_json(path=state_path, value=state)
            preparation_path = root / "preparation.json"
            preparation = (
                json.loads(preparation_path.read_text())
                if preparation_path.is_file()
                else None
            )
            if preparation and not all(
                inside(root=root, relative=p).is_file()
                and digest_file(path=inside(root=root, relative=p)) == sha
                for p, sha in preparation["checksums"].items()
            ):
                raise WorkbenchError("Prepared inputs changed; use a new output folder")
            if preparation is None:
                preparation = prepare_inputs(
                    paths=paths,
                    root=root,
                    fasta=args.fasta,
                    mapping=args.mapping,
                    regions_file=args.regions,
                    settings=settings,
                    chain=args.chain,
                )
            bad_qc = sum(m["status"] != "prepared" for m in preparation["model_qc"])
            if args.prepare_only:
                state.update(
                    status="prepared", stage="quality_review", finished_utc=utc_now()
                )
                write_json(path=state_path, value=state)
                return 2 if bad_qc else 0
            if not preparation["regions"]:
                raise WorkbenchError(
                    "No regions passed quality preparation; inspect"
                    " 01_quality/index.html and quality_audit.xlsx"
                )
            if args.comparison_mode != "none":
                for executable in (args.usalign, args.tmalign):
                    if not shutil.which(executable):
                        raise WorkbenchError(
                            f"Structural aligner unavailable: {executable}"
                        )
            state["stage"] = "pocket_prediction"
            write_json(path=state_path, value=state)
            prediction_root = root / "03_pocket_predictions"
            prediction_settings = Settings(
                threads=args.threads,
                timeout=args.timeout,
                allow_fragments=True,
                predict_config="alphafold",
                rescore_config="rescore_2024",
            )
            tools = inspect_tools(
                fpocket=args.fpocket, p2rank=args.p2rank, settings=prediction_settings
            )
            samples = load_samples(
                models=None,
                manifest=Path(preparation["manifest"]),
                fasta=Path(preparation["fasta"]),
                chain="",
            )
            report_path = prediction_root / "report.html"
            reuse_prediction = (
                state.get("prediction_complete")
                and report_path.is_file()
                and state.get("prediction_report_sha") == digest_file(path=report_path)
                and state.get("prediction_tools") == tools
            )
            prediction_status = (
                0
                if reuse_prediction
                else run_pipeline(
                    samples=samples,
                    output=prediction_root,
                    tools=tools,
                    settings=prediction_settings,
                    resume=args.resume and prediction_root.exists(),
                )
            )
            state.update(
                prediction_complete=prediction_status == 0,
                prediction_report_sha=digest_file(path=report_path),
                prediction_tools=tools,
            )
            write_json(path=state_path, value=state)
            report = read_report(path=report_path)
            evidence_sha = hashlib.sha256(
                json.dumps(
                    {k: report[k] for k in ("samples", "pockets", "ranked")},
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            resource = Path(state.get("resource") or root / "04_workbench")
            if resource.exists() and state.get("evidence_sha") != evidence_sha:
                for number in itertools.count(2):
                    candidate = root / f"04_workbench_{number:03d}"
                    if not candidate.exists():
                        resource = candidate
                        break
            if not resource.exists():
                previous = Path(state["resource"]) if state.get("resource") else None
                import_project(
                    sources=[prediction_root],
                    output=resource,
                    fasta=Path(preparation["fasta"]),
                    mapping=Path(preparation["mapping"]),
                    title=args.title,
                )
                if previous and (previous / "comparisons").is_dir():
                    shutil.copytree(
                        previous / "comparisons",
                        resource / "comparisons",
                        dirs_exist_ok=True,
                    )
            state.update(
                stage="region_comparisons",
                resource=str(resource),
                evidence_sha=evidence_sha,
            )
            write_json(path=state_path, value=state)
            pairs, groups, audit = plan_region_comparisons(
                preparation=preparation,
                mode=args.comparison_mode,
                minimum_overlap=args.sequence_overlap,
            )
            write_tsv(
                path=root / "01_quality" / "comparison_plan.tsv",
                rows=audit,
                columns=[
                    "reference",
                    "mobile",
                    "corresponding_residues",
                    "reference_region_coverage",
                    "mobile_region_coverage",
                    "eligible",
                ],
            )
            # The new audit file is not part of the immutable cleaning checksum set.
            shutil.copytree(
                root / "01_quality", resource / "quality", dirs_exist_ok=True
            )
            enrich_resource(
                resource=resource,
                preparation=preparation,
                settings=settings,
                groups=groups,
                comparison_audit=audit,
            )
            analyse_sequences(
                root=resource,
                sequence_ids=preparation["tree_sequence_ids"],
                threads=args.threads,
                bootstrap=args.bootstrap,
                seed=42,
            )
            failed = 0
            for engine in ("usalign", "tmalign") if pairs else ():
                for start in range(0, len(pairs), 2000):
                    results = compare_batch(
                        root=resource,
                        pairs=pairs[start : start + 2000],
                        settings=ComparisonSettings(
                            engine=engine,
                            fit_scope="global",
                            min_plddt=0,
                            top_pockets=args.top_pockets,
                            confident_only=True,
                            quality_screen_only=True,
                        ),
                        usalign=args.usalign,
                        tmalign=args.tmalign,
                        workers=args.workers,
                    )
                    failed += sum(r["status"] != "complete" for r in results)
            review = root / "05_review"
            for number in itertools.count(2):
                if not review.exists() and not review.with_suffix(".zip").exists():
                    break
                review = root / f"05_review_{number:03d}"
            export_review(root=resource, output=review)
            outputs = {
                "resource": str(resource),
                "review_directory": str(review),
                "review_zip": str(review.with_suffix(".zip")),
            }
            write_json(path=root / "latest_outputs.json", value=outputs)
            partial = bool(prediction_status or bad_qc or failed)
            state.update(
                outputs,
                stage="finished",
                status="partial" if partial else "complete",
                failed_comparisons=failed,
                finished_utc=utc_now(),
            )
            write_json(path=state_path, value=state)
            LOGGER.info("Final outputs: %s", json.dumps(outputs))
            return 2 if partial else 0
        except Exception as error:
            state.update(status="failed", error=str(error), finished_utc=utc_now())
            write_json(path=state_path, value=state)
            raise
        finally:
            logging.getLogger().removeHandler(handler)
            handler.close()


def main(*, argv: list[str] | None = None) -> int:
    """Parse named options and run the audited batch workflow.

    Args:
        argv: Explicit command-line options or process arguments.

    Returns:
        Zero complete, one fatal input/tool error, two retained partial results.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--models",
        type=Path,
        required=True,
        help="Original model root; scanned recursively",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="New isolated results directory"
    )
    parser.add_argument("--fasta", type=Path, help="Full representative protein FASTA")
    parser.add_argument(
        "--mapping", type=Path, help="Exact parent sample_id/sequence_id/chain TSV"
    )
    parser.add_argument(
        "--regions",
        type=Path,
        help="Curated region TSV instead of automatic candidates",
    )
    parser.add_argument(
        "--chain", default="", help="Target author chain for multi-protein models"
    )
    parser.add_argument(
        "--title",
        default="Quality-prepared protein pocket review",
        help="Project display title",
    )
    parser.add_argument("--fpocket", default="fpocket", help="fpocket executable")
    parser.add_argument(
        "--p2rank", default="prank", help="P2Rank 2.5.1 prank executable"
    )
    parser.add_argument("--usalign", default="USalign", help="USalign executable")
    parser.add_argument("--tmalign", default="TMalign", help="TMalign executable")
    parser.add_argument(
        "--threads", type=int, default=8, help="P2Rank/FAMSA thread allocation"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Concurrent single-thread structural fits",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3600,
        help="Per-predictor-command timeout, seconds",
    )
    parser.add_argument(
        "--core-plddt", type=float, default=70, help="Residue-mean pLDDT core threshold"
    )
    parser.add_argument(
        "--max-low-gap",
        type=int,
        default=30,
        help="Largest internal non-core run between anchors",
    )
    parser.add_argument(
        "--min-region-length",
        type=int,
        default=50,
        help="Minimum candidate length in residues",
    )
    parser.add_argument(
        "--min-core", type=int, default=40, help="Minimum core residues per candidate"
    )
    parser.add_argument(
        "--padding",
        type=int,
        default=5,
        help="Boundary padding in residues without overlap",
    )
    parser.add_argument(
        "--max-pae",
        type=float,
        default=10,
        help="Symmetric core-pair PAE threshold, Angstroms",
    )
    parser.add_argument(
        "--allow-missing-pae",
        action="store_true",
        help="Retain PAE-unassessed regions as secondary evidence only",
    )
    parser.add_argument(
        "--comparison-mode",
        choices=["matched_reference", "matched_all", "none"],
        default="matched_reference",
        help=(
            "Reference fits per corresponding-region group, all eligible fits, or none"
        ),
    )
    parser.add_argument(
        "--sequence-overlap",
        type=float,
        default=0.7,
        help="Minimum mutual correspondence coverage",
    )
    parser.add_argument(
        "--top-pockets",
        type=int,
        default=5,
        help="Compare original review ranks up to this number",
    )
    parser.add_argument(
        "--bootstrap", type=int, default=100, help="NJ tree bootstrap replicates, 0–200"
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Stop after the quality audit; no predictors required",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse matching completed stages in this run",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        return run_workflow(args=args)
    except (ValueError, OSError, RuntimeError) as error:
        LOGGER.error("%s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
