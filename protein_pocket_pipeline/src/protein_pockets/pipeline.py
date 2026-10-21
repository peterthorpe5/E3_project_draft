"""Per-model execution, verified checkpoints and independent failure records."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .io import sha256_file, write_json, write_tsv
from .models import Sample, Settings
from .parsers import (
    annotate_pockets,
    convert_native_tables,
    export_raw_pockets,
    match_pockets,
    parse_fpocket,
    parse_p2rank,
)
from .ranking import rank_cavities
from .schema import SCHEMA_VERSION, TABLE_FIELDS
from .structure import prepare_structure
from .tools import run_command

LOGGER = logging.getLogger(__name__)
METHODS = ("fpocket", "p2rank", "p2rank_rescore")


def analyse_method(
    *,
    method: str,
    sample: Sample,
    root: Path,
    prepared: Path,
    tools: dict,
    settings: Settings,
    previous_pockets: list[dict],
) -> list[dict]:
    """Execute and parse one method in its own directory.

    Args:
        method: fpocket, p2rank or p2rank_rescore.
        sample: Input identifier.
        root: Run directory.
        prepared: Normalised PDB.
        tools: Captured executable identities.
        settings: Profiles, thread count and timeouts.
        previous_pockets: fpocket cavities available for direct rescoring.

    Returns:
        Parsed pockets for this method; an empty list means no pockets.
    """
    directory = root / "tool_outputs" / sample.sample_id / method
    directory.mkdir(parents=True, exist_ok=True)
    log_prefix = root / "logs" / sample.sample_id / method
    native_output = directory / "output"
    try:
        if method == "fpocket":
            model_path = directory / "model.pdb"
            shutil.copy2(src=prepared, dst=model_path)
            run_command(
                command=[tools["fpocket"]["executable"], "-f", "model.pdb"],
                cwd=directory,
                log_prefix=log_prefix,
                timeout=settings.timeout,
            )
            output = directory / "model_out"
            if not list(output.glob("*_info.txt")):
                stdout = log_prefix.with_suffix(".stdout.log").read_text(
                    encoding="utf-8"
                )
                stderr = log_prefix.with_suffix(".stderr.log").read_text(
                    encoding="utf-8"
                )
                if re.search(
                    r"no pockets? (?:found|detected)|0 pockets", stdout + stderr, re.I
                ):
                    return []
                raise ValueError("fpocket succeeded but required output is absent")
            pockets = parse_fpocket(directory=output, sample_id=sample.sample_id)
            if not pockets:
                raise ValueError("fpocket info file contains no pocket records")
        elif method in {"p2rank", "p2rank_rescore"}:
            if method == "p2rank":
                shutil.copy2(src=prepared, dst=directory / "model.pdb")
                command = [tools["p2rank"]["executable"], "predict", "-f", "model.pdb"]
                profile = settings.predict_config
            else:
                # Relative paths avoid quoting ambiguities in P2Rank's whitespace
                # dataset parser even when the run directory contains spaces.
                (directory / "fpocket.ds").write_text(
                    data="PARAM.PREDICTION_METHOD=fpocket\nHEADER: prediction protein\n"
                    "../fpocket/model_out/model_out.pdb ../fpocket/model.pdb\n",
                    encoding="utf-8",
                )
                command = [tools["p2rank"]["executable"], "rescore", "fpocket.ds"]
                profile = settings.rescore_config
            command += [
                "-c",
                profile,
                "-o",
                "output",
                "-threads",
                str(settings.threads),
            ]
            run_command(
                command=command,
                cwd=directory,
                log_prefix=log_prefix,
                timeout=settings.timeout,
            )
            predictions = list(native_output.glob("*_predictions.csv"))
            if len(predictions) != 1:
                raise ValueError("Expected exactly one P2Rank predictions file")
            pockets = parse_p2rank(
                path=predictions[0],
                sample_id=sample.sample_id,
                method=method,
                valid_fpocket_ids={p["pocket_id"] for p in previous_pockets},
            )
            if method == "p2rank_rescore" and {
                p["fpocket_pocket_id"] for p in pockets
            } != {p["pocket_id"] for p in previous_pockets}:
                raise ValueError("P2Rank rescore did not return every fpocket cavity")
        else:
            raise ValueError(f"Unknown method: {method}")
        export_raw_pockets(path=directory / "raw_descriptors.tsv", pockets=pockets)
        return pockets
    finally:
        convert_native_tables(directory=directory)


def analyse_sample(
    *, sample: Sample, root: Path, tools: dict, settings: Settings
) -> dict:
    """Run one model while allowing independent methods to fail separately.

    Args:
        sample: Representative model and metadata.
        root: Run directory.
        tools: Checked executable identities.
        settings: Analysis configuration.

    Returns:
        Stable-schema data tables and internal pocket records for checkpoints.
    """
    model_dir = root / "models" / sample.sample_id
    input_dir = root / "inputs" / sample.sample_id
    for path in (
        model_dir,
        input_dir,
        root / "tool_outputs" / sample.sample_id,
        root / "logs" / sample.sample_id,
    ):
        if path.exists():
            shutil.rmtree(path=path)
    input_dir.mkdir(parents=True)
    source = input_dir / ("source" + sample.model_path.suffix.lower())
    shutil.copy2(src=sample.model_path, dst=source)
    if sample.sequence:
        (input_dir / "representative.fasta").write_text(
            data=f">{sample.sequence_id}\n{sample.sequence}\n", encoding="utf-8"
        )
    prepared = model_dir / "prepared.pdb"
    summary = {
        "sample_id": sample.sample_id,
        "cluster": sample.cluster,
        "sequence_id": sample.sequence_id,
        "status": "failed",
        "error": "",
        "source_model": source.relative_to(root).as_posix(),
        "prepared_model": None,
        "fpocket_status": "skipped",
        "p2rank_status": "skipped",
        "rescore_status": "skipped",
    }
    tables = {name: [] for name in TABLE_FIELDS}
    tables["samples"] = [summary]
    try:
        residues, metadata = prepare_structure(
            sample=sample, settings=settings, destination=prepared
        )
    except (ValueError, RuntimeError, OSError) as error:
        LOGGER.exception("Preparation failed for %s", sample.sample_id)
        summary["error"] = str(error)
        tables["method_runs"] = [
            {
                "sample_id": sample.sample_id,
                "method": method,
                "status": "skipped",
                "error": "Structure preparation failed",
                "log_prefix": None,
            }
            for method in METHODS
        ]
        return tables
    summary.update(metadata)
    summary["prepared_model"] = prepared.relative_to(root).as_posix()
    tables["residues"] = residues
    write_tsv(
        path=model_dir / "residue_map.tsv",
        rows=residues,
        columns=TABLE_FIELDS["residues"],
    )
    pockets = []
    errors = []
    for method in METHODS:
        run = {
            "sample_id": sample.sample_id,
            "method": method,
            "status": "skipped",
            "error": "",
            "log_prefix": f"logs/{sample.sample_id}/{method}",
        }
        fpocket_pockets = [p for p in pockets if p["method"] == "fpocket"]
        if method == "p2rank_rescore" and (not settings.rescore or not fpocket_pockets):
            run["error"] = (
                "Disabled" if not settings.rescore else "No fpocket cavities available"
            )
        else:
            try:
                result = analyse_method(
                    method=method,
                    sample=sample,
                    root=root,
                    prepared=prepared,
                    tools=tools,
                    settings=settings,
                    previous_pockets=fpocket_pockets,
                )
                pockets.extend(result)
                run["status"] = "complete" if result else "no_pockets"
            except (ValueError, RuntimeError, OSError) as error:
                LOGGER.exception("%s failed for %s", method, sample.sample_id)
                run.update(status="failed", error=str(error))
                errors.append(f"{method}: {error}")
        tables["method_runs"].append(run)
        field = "rescore_status" if method == "p2rank_rescore" else f"{method}_status"
        summary[field] = run["status"]
    # A later external stage may recreate an earlier native prediction file.
    # Enforce the TSV contract again after every external process has finished.
    convert_native_tables(directory=root / "tool_outputs" / sample.sample_id)
    annotated, membership = annotate_pockets(
        pockets=pockets, residues=residues, settings=settings
    )
    matches = match_pockets(pockets=annotated, threshold=settings.overlap)
    tables["pockets"] = annotated
    tables["pocket_residues"] = membership
    tables["matches"] = matches
    tables["ranked_pockets"] = rank_cavities(pockets=annotated, matches=matches)
    tables["fpocket_descriptors"] = [
        {
            "sample_id": sample.sample_id,
            "pocket_id": pocket["pocket_id"],
            "descriptor": name,
            "value": value,
        }
        for pocket in annotated
        if pocket["method"] == "fpocket"
        for name, value in pocket["metrics"].items()
    ]
    statuses = [run["status"] for run in tables["method_runs"]]
    if errors:
        summary["status"] = (
            "partial"
            if any(s in {"complete", "no_pockets"} for s in statuses)
            else "failed"
        )
    else:
        summary["status"] = "complete" if pockets else "no_pockets"
    summary["error"] = "; ".join(errors)
    return tables


def checkpoint_valid(
    *, checkpoint: dict, root: Path, sample_id: str | None = None
) -> bool:
    """Verify every retained input, model, tool-output and log file checksum.

    Args:
        checkpoint: Previously saved per-model state.
        root: Run directory.
        sample_id: Expected model identifier for a named checkpoint.

    Returns:
        True only for a successful, intact model checkpoint.
    """
    if not isinstance(checkpoint, dict):
        return False
    tables = checkpoint.get("tables", {})
    if not isinstance(tables, dict) or any(
        not isinstance(tables.get(name), list) for name in TABLE_FIELDS
    ):
        return False
    samples = tables["samples"]
    if len(samples) != 1 or not isinstance(samples[0], dict):
        return False
    if samples[0].get("status") not in {"complete", "no_pockets"}:
        return False
    if sample_id is not None and any(
        not isinstance(row, dict) or row.get("sample_id") != sample_id
        for name, rows in tables.items()
        if name != "run_info"
        for row in rows
    ):
        return False
    digest = hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()
    if checkpoint.get("tables_sha256") != digest:
        return False
    checksums = checkpoint.get("checksums", {})
    if not checksums:
        return False
    for relative, expected in checksums.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()):
            return False
        if not path.is_file() or sha256_file(path=path) != expected:
            return False
    return True


def run_pipeline(
    *,
    samples: list[Sample],
    output: Path,
    tools: dict,
    settings: Settings,
    resume: bool,
) -> int:
    """Execute a complete run, rebuilding exports from verified checkpoints.

    Args:
        samples: Validated input records.
        output: New/empty output directory, or an identical run with --resume.
        tools: Captured versions and selected P2Rank asset checksums.
        settings: Analysis options.
        resume: Reuse intact completed models; retry failed or altered outputs.

    Returns:
        0 for successful analysis (including no pockets), 2 for partial/failure.

    Raises:
        ValueError: For incompatible resume or a non-empty unrecognised output.
    """
    from .reporting import export_results

    output = output.resolve()
    if not samples or len({sample.sample_id.casefold() for sample in samples}) != len(
        samples
    ):
        raise ValueError(
            "At least one model and unique sample identifiers are required"
        )
    for sample in samples:
        if sample.model_path.resolve().is_relative_to(output):
            raise ValueError("Input models must be outside the output directory")
    identities = []
    for sample in samples:
        record = asdict(sample)
        record["model_path"] = str(sample.model_path)
        record["model_sha256"] = sha256_file(path=sample.model_path)
        identities.append(record)
    identity = {
        "pipeline_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "pipeline_source": {
            str(path.relative_to(Path(__file__).parent)): sha256_file(path=path)
            for path in sorted(Path(__file__).parent.rglob("*"))
            if path.is_file() and path.suffix in {".py", ".html"}
        },
        "settings": asdict(settings),
        "inputs": identities,
        "tools": tools,
    }
    fingerprint_input = {
        **identity,
        "tools": {
            name: {
                key: value
                for key, value in record.items()
                if key not in {"version_output", "return_code"}
            }
            for name, record in tools.items()
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_input, sort_keys=True).encode()
    ).hexdigest()
    manifest_path = output / "provenance" / "run_manifest.json"
    if output.exists() and any(output.iterdir()):
        if not resume or not manifest_path.is_file():
            raise ValueError(
                "Output is not empty; use a new folder or --resume for the same run"
            )
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("fingerprint") != fingerprint:
            raise ValueError(
                "Resume refused: inputs, settings, pipeline or tool identity changed"
            )
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".run.lock"
    try:
        descriptor = os.open(
            path=lock, flags=os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode=0o600
        )
    except FileExistsError as error:
        raise ValueError(
            "Run is locked; see docs/TROUBLESHOOTING.md before removing .run.lock"
        ) from error
    os.close(fd=descriptor)
    handler = logging.FileHandler(filename=output / "pipeline.log", encoding="utf-8")
    handler.setFormatter(
        fmt=logging.Formatter(fmt="%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logging.getLogger("protein_pockets").addHandler(hdlr=handler)
    manifest = {
        **identity,
        "fingerprint": fingerprint,
        "status": "running",
        "started_utc": datetime.now(tz=UTC).isoformat(),
    }
    try:
        write_json(path=manifest_path, data=manifest)
        tables = {name: [] for name in TABLE_FIELDS}
        for sample in samples:
            checkpoint_path = output / "checkpoints" / f"{sample.sample_id}.json"
            checkpoint = {}
            if resume and checkpoint_path.is_file():
                try:
                    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    LOGGER.warning(
                        "Retrying unreadable checkpoint: %s", checkpoint_path
                    )
            if checkpoint_valid(
                checkpoint=checkpoint, root=output, sample_id=sample.sample_id
            ):
                LOGGER.info("Reusing verified model %s", sample.sample_id)
                result = checkpoint["tables"]
            else:
                LOGGER.info("Analysing model %s", sample.sample_id)
                result = analyse_sample(
                    sample=sample, root=output, tools=tools, settings=settings
                )
                checksums = {}
                for name in ("inputs", "models", "tool_outputs", "logs"):
                    directory = output / name / sample.sample_id
                    for path in sorted(directory.rglob("*")):
                        if path.is_file():
                            checksums[path.relative_to(output).as_posix()] = (
                                sha256_file(path=path)
                            )
                write_json(
                    path=checkpoint_path,
                    data={
                        "tables": result,
                        "checksums": checksums,
                        "tables_sha256": hashlib.sha256(
                            json.dumps(result, sort_keys=True).encode()
                        ).hexdigest(),
                    },
                )
            for name in tables:
                tables[name].extend(result[name])
        exit_code = (
            2
            if any(row["status"] in {"failed", "partial"} for row in tables["samples"])
            else 0
        )
        manifest.update(
            status="partial" if exit_code else "complete",
            finished_utc=datetime.now(tz=UTC).isoformat(),
            model_count=len(samples),
        )
        tables["run_info"] = [
            {"key": key, "value": json.dumps(value, ensure_ascii=False)}
            for key, value in manifest.items()
        ]
        export_results(root=output, tables=tables, manifest=manifest)
        write_json(path=manifest_path, data=manifest)
        LOGGER.info("Finished: %s; open %s", manifest["status"], output / "report.html")
        return exit_code
    except BaseException:
        manifest["status"] = "interrupted_or_export_failed"
        write_json(path=manifest_path, data=manifest)
        raise
    finally:
        logging.getLogger("protein_pockets").removeHandler(hdlr=handler)
        handler.close()
        lock.unlink(missing_ok=True)
