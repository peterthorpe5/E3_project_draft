"""Optional structure prediction and eukaryote-aware sequence annotation providers."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import time
from typing import Mapping
from urllib.parse import urlencode, urlparse

import requests

from Bio.PDB import PDBParser
from Bio.PDB.PDBExceptions import PDBConstructionException
from Bio.SeqUtils import seq1

from .analysis import index_fasta, run_command
from .common import ResearchConfig, ResearchError, atomic_json, iter_fasta, write_tsv

LOGGER = logging.getLogger(__name__)
ATLAS_ENDPOINT = "https://api.esmatlas.com/foldSequence/v1/pdb/"
INTERPRO_ENDPOINT = "https://www.ebi.ac.uk/Tools/services/rest/iprscan5"


def http_request(
    *,
    url: str,
    method: str = "GET",
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    maximum_bytes: int = 20_000_000,
) -> bytes:
    """Issue one bounded provider request without logging sequences or bearer tokens.

    Args:
        url: Trusted configured HTTPS provider URL without embedded credentials.
        method: GET or POST.
        body: Optional encoded request body.
        headers: Optional headers, including a server-held token.
        maximum_bytes: Maximum result payload size.

    Returns:
        Complete response bytes.

    Raises:
        ResearchError: If endpoint validation, the request or response size fails.
    """
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
        or method not in {"GET", "POST"}
    ):
        raise ResearchError(
            "Protein providers require HTTPS URLs without credentials or query tokens"
        )
    try:
        with requests.request(
            method=method,
            url=url,
            data=body,
            headers={"User-Agent": "protein-research-workbench/0.19", **dict(headers or {})},
            stream=True,
            allow_redirects=False,
            timeout=(10, 120),
        ) as response:
            if not 200 <= response.status_code < 300:
                raise ResearchError(
                    f"Protein service returned HTTP {response.status_code}; "
                    "retry or use another provider"
                )
            blocks, total = [], 0
            for block in response.iter_content(chunk_size=65536):
                total += len(block)
                if total > maximum_bytes:
                    raise ResearchError("Protein service response exceeds its explicit size bound")
                blocks.append(block)
            content = b"".join(blocks)
    except (requests.RequestException, TimeoutError, OSError) as exc:
        raise ResearchError("Protein service is unavailable or timed out") from exc
    return content


def pdb_evidence(*, pdb: str, expected_sequence: str) -> list[dict[str, object]]:
    """Validate a complete monomer model against its exact source sequence.

    Args:
        pdb: Model coordinate text.
        expected_sequence: Exact normalised input protein.

    Returns:
        One residue record per C-alpha, including coordinates and reported B-factor.

    Raises:
        ResearchError: If atoms are absent, sequence differs or confidence values are invalid.
    """
    if "ATOM  " not in pdb or len(pdb.encode("utf-8")) > 20_000_000:
        raise ResearchError("Structure provider did not return a bounded PDB coordinate model")
    try:
        structure = PDBParser(QUIET=True).get_structure("prediction", io.StringIO(pdb))
        model = next(structure.get_models())
        records = []
        for chain in model:
            for residue in chain:
                if "CA" not in residue or residue.id[0] != " ":
                    continue
                atom = residue["CA"]
                records.append(
                    {
                        "residue_index": len(records) + 1,
                        "chain_id": chain.id,
                        "pdb_residue_number": residue.id[1],
                        "residue": seq1(residue.resname, custom_map={"MSE": "M"}),
                        "confidence_b_factor": float(atom.bfactor),
                        "x": float(atom.coord[0]),
                        "y": float(atom.coord[1]),
                        "z": float(atom.coord[2]),
                    }
                )
    except (ValueError, KeyError, StopIteration, TypeError, PDBConstructionException) as exc:
        raise ResearchError("Could not parse the predicted PDB model") from exc
    if "".join(record["residue"] for record in records) != expected_sequence:
        raise ResearchError("Predicted model residues do not match the complete input sequence")
    if any(not 0 <= record["confidence_b_factor"] <= 100 for record in records):
        raise ResearchError("Reported model confidence is outside its supported 0–100 range")
    if any(not math.isfinite(record[axis]) for record in records for axis in ("x", "y", "z")):
        raise ResearchError("Model coordinates must be finite")
    return records


def local_esmfold(*, sequence: str, revision: str) -> str:
    """Run the Hugging Face ESMFold checkpoint locally on a worker, without sending the sequence.

    Args:
        sequence: Validated single-chain input protein.
        revision: Pinned model revision recorded with the result.

    Returns:
        Predicted PDB coordinate text.

    Raises:
        ResearchError: If optional PyTorch/Transformers dependencies are unavailable.
    """
    try:
        import torch
        from transformers import EsmForProteinFolding
    except ImportError as exc:
        raise ResearchError(
            "Install the folding optional dependencies in the worker environment"
        ) from exc
    device = "cuda" if torch.cuda.is_available() else "cpu"
    LOGGER.info("Loading ESMFold revision %s on %s", revision, device)
    model = EsmForProteinFolding.from_pretrained("facebook/esmfold_v1", revision=revision)
    model = model.eval().to(device)
    if device == "cuda":
        model.esm = model.esm.half()
    model.trunk.set_chunk_size(128)
    with torch.inference_mode():
        prediction = model.infer(sequence)
        # Transformers 4.x exports fractional lDDT. Store the documented 0-100 scale.
        prediction["plddt"] = prediction["plddt"] * 100
        pdb = model.output_to_pdb(prediction)[0]
    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    return pdb


def predict_one(
    *, sequence: str, engine: str, config: ResearchConfig, remote_allowed: bool = False
) -> tuple[Path, list[dict[str, object]], bool]:
    """Obtain a validated model through Atlas, a configured endpoint, or local ESMFold.

    Args:
        sequence: Exact canonical protein sequence.
        engine: atlas, huggingface_endpoint or local.
        config: Trusted provider configuration; tokens are read from its named environment variable.
        remote_allowed: Explicit user decision to submit a sequence outside the local worker.

    Returns:
        Content-addressed cached model, residue evidence and whether it was reused.

    Raises:
        ResearchError: If provider, sequence length or remote consent is invalid.
    """
    if engine not in {"atlas", "huggingface_endpoint", "local"}:
        raise ResearchError("Unsupported structure prediction provider")
    if not re.fullmatch(r"[ACDEFGHIKLMNPQRSTVWYX]+", sequence):
        raise ResearchError("ESMFold inputs require canonical amino acids or X")
    limit = (
        400
        if engine == "atlas"
        else (
            config.endpoint_max_length
            if engine == "huggingface_endpoint"
            else config.local_fold_max_length
        )
    )
    if len(sequence) > limit:
        raise ResearchError(
            f"This structure route is limited to {limit} residues; " "no truncation was performed"
        )
    if engine != "local" and remote_allowed is not True:
        raise ResearchError(
            "Remote prediction requires the user's explicit sequence-submission selection"
        )
    if engine == "huggingface_endpoint" and not config.esm_endpoint:
        raise ResearchError(
            (
                "Configure a deployed ESMFold endpoint; no generic Hugging Face inference"
                " provider is assumed"
            )
        )
    effective_revision = (
        config.esm_model_revision if engine == "local" else "SERVICE_VERSION_UNVERIFIED"
    )
    key = hashlib.sha256(
        (sequence + engine + effective_revision + config.esm_endpoint).encode()
    ).hexdigest()
    cache = config.workspace / "models"
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / f"{key}.pdb"
    if destination.is_file():
        return (
            destination,
            pdb_evidence(pdb=destination.read_text(encoding="utf-8"), expected_sequence=sequence),
            True,
        )
    lock = cache / f"{key}.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ResearchError(
            "This exact model is already being computed; inspect its worker before retrying"
        ) from exc
    os.close(descriptor)
    try:
        if engine == "local":
            pdb = local_esmfold(sequence=sequence, revision=config.esm_model_revision)
        elif engine == "atlas":
            pdb = http_request(
                url=ATLAS_ENDPOINT,
                method="POST",
                body=sequence.encode(),
                headers={"Content-Type": "text/plain"},
            ).decode("utf-8")
        else:
            headers = {"Content-Type": "application/json"}
            token = os.environ.get(config.esm_token_env, "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            content = http_request(
                url=config.esm_endpoint,
                method="POST",
                headers=headers,
                body=json.dumps({"inputs": sequence}).encode(),
            ).decode("utf-8")
            if content.lstrip().startswith("{"):
                try:
                    pdb = json.loads(content)["pdb"]
                except (ValueError, KeyError, TypeError) as exc:
                    raise ResearchError(
                        "Configured endpoint must return PDB text or an object with a pdb field"
                    ) from exc
            else:
                pdb = content
        residues = pdb_evidence(pdb=pdb, expected_sequence=sequence)
        temporary = cache / f"{key}.partial"
        temporary.write_text(pdb, encoding="utf-8")
        os.replace(temporary, destination)
        return destination, residues, False
    finally:
        lock.unlink(missing_ok=True)


def predict_batch(
    *, config: ResearchConfig, source: Path, output: Path, parameters: Mapping[str, object]
) -> dict[str, Path]:
    """Predict selected models with per-sequence success/failure auditing and downloads.

    Args:
        config: Trusted worker/provider settings.
        source: Explicitly selected FASTA; at most 100 proteins per model job.
        output: Owned job directory.
        parameters: engine and remote_allowed controls.

    Returns:
        Successful PDB/residue artifacts and an audit retaining every attempted sequence.

    Raises:
        ResearchError: If input is oversized or every model attempt fails.
    """
    connection, _ = index_fasta(source=source, destination=output / "input.sqlite", maximum=100)
    connection.close()
    engine = str(parameters.get("engine", "atlas"))
    rows: list[dict[str, object]] = []
    artifacts: dict[str, Path] = {}
    for identifier, sequence in iter_fasta(path=source):
        row: dict[str, object] = {
            "sequence_id": identifier,
            "sequence_length": len(sequence),
            "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
            "provider": engine,
            "model_revision": (
                config.esm_model_revision if engine == "local" else "SERVICE_VERSION_UNVERIFIED"
            ),
        }
        try:
            cached, residues, reused = predict_one(
                sequence=sequence,
                engine=engine,
                config=config,
                remote_allowed=parameters.get("remote_allowed", False) is True,
            )
            stem = hashlib.sha256(identifier.encode()).hexdigest()[:24]
            model_name, residue_name = f"model_{stem}.pdb", f"residues_{stem}.tsv"
            shutil.copyfile(cached, output / model_name)
            write_tsv(path=output / residue_name, rows=residues, columns=list(residues[0]))
            artifacts[model_name], artifacts[residue_name] = (
                output / model_name,
                output / residue_name,
            )
            row.update(
                {
                    "status": "REUSED" if reused else "PREDICTED",
                    "pdb_artifact": model_name,
                    "residue_artifact": residue_name,
                    "mean_reported_confidence": sum(
                        item["confidence_b_factor"] for item in residues
                    )
                    / len(residues),
                    "error": "",
                }
            )
        except (ResearchError, RuntimeError) as exc:
            row.update(
                {"status": "FAILED", "error": str(exc), "pdb_artifact": "", "residue_artifact": ""}
            )
        rows.append(row)
    columns = (
        "sequence_id",
        "sequence_length",
        "sequence_sha256",
        "provider",
        "model_revision",
        "status",
        "pdb_artifact",
        "residue_artifact",
        "mean_reported_confidence",
        "error",
    )
    write_tsv(path=output / "predictions.tsv", rows=rows, columns=columns)
    artifacts["predictions.tsv"] = output / "predictions.tsv"
    if not any(row["status"] != "FAILED" for row in rows):
        raise ResearchError(
            "No model was produced; inspect predictions.tsv for provider-specific reasons"
        )
    return artifacts


def parse_interpro(*, path: Path, sequences: Mapping[str, str]) -> list[dict[str, object]]:
    """Normalise InterProScan TSV domains with one-based inclusive input coordinates.

    Args:
        path: Local or remote service TSV result.
        sequences: Exact submitted proteins by identifier.

    Returns:
        Validated domain-hit records; no-hit inputs are handled separately in the audit.

    Raises:
        ResearchError: If a hit changes identifiers or has invalid coordinates.
    """
    rows = []
    with path.open(encoding="utf-8") as handle:
        for fields in csv.reader(handle, delimiter="\t"):
            if not fields or fields[0].startswith("#"):
                continue
            if len(fields) < 11 or fields[0] not in sequences:
                raise ResearchError(
                    "InterPro result has an unsupported row or unknown input identifier"
                )
            expected = sequences[fields[0]]
            expected_md5 = hashlib.md5(expected.encode(), usedforsecurity=False).hexdigest()
            if fields[1].lower() != expected_md5 or fields[2] != str(len(expected)):
                raise ResearchError(
                    "InterPro result sequence checksum or length differs from its input"
                )
            try:
                start, end = int(fields[6]), int(fields[7])
            except ValueError as exc:
                raise ResearchError("InterPro domain coordinates must be integers") from exc
            if not 1 <= start <= end <= len(sequences[fields[0]]):
                raise ResearchError("InterPro domain lies outside the submitted protein")
            rows.append(
                {
                    "sequence_id": fields[0],
                    "analysis": fields[3],
                    "signature_accession": fields[4],
                    "description": fields[5],
                    "start": start,
                    "end": end,
                    "score": fields[8],
                    "interpro_accession": fields[11] if len(fields) > 11 else "",
                    "interpro_description": fields[12] if len(fields) > 12 else "",
                    "go_terms": fields[13] if len(fields) > 13 else "",
                    "evidence_type": "SEQUENCE_SIGNATURE_PREDICTION",
                }
            )
    return rows


def remote_interpro(
    *, sequences: Mapping[str, str], output: Path, config: ResearchConfig, remote_allowed: bool
) -> Path:
    """Submit/poll a bounded EBI InterProScan job, retaining its service job ID for recovery.

    Args:
        sequences: At most 25 selected proteins.
        output: Owned job directory.
        config: Contact email and runtime settings.
        remote_allowed: Explicit user decision to send sequences to EBI.

    Returns:
        Downloaded TSV service result.

    Raises:
        ResearchError: If consent/contact is absent, the service fails or polling expires.
    """
    if remote_allowed is not True or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", config.email):
        raise ResearchError(
            "Remote InterProScan requires explicit submission and a configured contact email"
        )
    if len(sequences) > 25:
        raise ResearchError(
            (
                "Select at most 25 proteins for one remote InterProScan job; use local "
                "execution for batches"
            )
        )
    checkpoint = output / "interpro_service_job.json"
    if checkpoint.is_file():
        job_id = json.loads(checkpoint.read_text(encoding="utf-8"))["service_job_id"]
    else:
        fasta = "".join(f">{key}\n{sequence}\n" for key, sequence in sequences.items())
        body = urlencode(
            {"email": config.email, "sequence": fasta, "goterms": "true", "pathways": "true"}
        ).encode()
        job_id = (
            http_request(
                url=INTERPRO_ENDPOINT + "/run",
                method="POST",
                body=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            .decode()
            .strip()
        )
        atomic_json(path=checkpoint, value={"service_job_id": job_id})
    if not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        raise ResearchError("InterPro service returned an invalid job identifier")
    deadline = time.monotonic() + config.command_timeout
    while time.monotonic() < deadline:
        status = http_request(url=f"{INTERPRO_ENDPOINT}/status/{job_id}").decode().strip()
        if status == "FINISHED":
            destination = output / "interpro.raw.tsv"
            destination.write_bytes(
                http_request(
                    url=f"{INTERPRO_ENDPOINT}/result/{job_id}/tsv", maximum_bytes=50_000_000
                )
            )
            return destination
        if status not in {"PENDING", "RUNNING", "QUEUED"}:
            raise ResearchError(f"InterPro service job ended with state {status}")
        time.sleep(min(10, max(0, deadline - time.monotonic())))
    raise ResearchError("InterPro polling timed out; service job ID was retained for recovery")


def annotate_batch(
    *, config: ResearchConfig, source: Path, output: Path, parameters: Mapping[str, object]
) -> dict[str, Path]:
    """Run InterProScan or eggNOG with an explicit taxonomic scope and auditable no-hit states.

    Args:
        config: Local tools, databases and optional remote contact.
        source: Selected protein FASTA.
        output: Owned job directory.
        parameters: engine, tax_scope, target_taxon and remote_allowed controls.

    Returns:
        Normalised annotation/evidence TSV, per-input audit and raw provider output artifacts.

    Raises:
        ResearchError: If a tool, database, scope or result contract is invalid.
    """
    connection, _ = index_fasta(source=source, destination=output / "input.sqlite", maximum=100_000)
    connection.close()
    sequences = dict(iter_fasta(path=source))
    normalised = output / "annotation_input.fasta"
    with normalised.open(mode="w", encoding="utf-8") as handle:
        handle.writelines(
            f">{identifier}\n{sequence}\n" for identifier, sequence in sequences.items()
        )
    engine = str(parameters.get("engine", "interpro_local"))
    artifacts: dict[str, Path] = {"annotation_input.fasta": normalised}
    if engine in {"interpro_local", "interpro_remote"}:
        if engine == "interpro_local":
            run_command(
                arguments=[config.interproscan, "-version"],
                output=output,
                config=config,
                stdout=output / "annotation_tool_version.txt",
            )
            run_command(
                arguments=[
                    config.interproscan,
                    "-i",
                    str(normalised),
                    "-b",
                    str(output / "interpro"),
                    "-f",
                    "TSV,JSON,GFF3",
                    "-cpu",
                    str(config.threads),
                    "-goterms",
                    "-pa",
                ],
                output=output,
                config=config,
            )
            raw = output / "interpro.tsv"
            artifacts.update(
                {path.name: path for path in output.glob("interpro.*") if path.is_file()}
            )
        else:
            raw = remote_interpro(
                sequences=sequences,
                output=output,
                config=config,
                remote_allowed=parameters.get("remote_allowed", False) is True,
            )
        rows = parse_interpro(path=raw, sequences=sequences)
        columns = (
            "sequence_id",
            "analysis",
            "signature_accession",
            "description",
            "start",
            "end",
            "score",
            "interpro_accession",
            "interpro_description",
            "go_terms",
            "evidence_type",
        )
        artifacts[raw.name] = raw
    elif engine == "eggnog":
        scope = str(parameters.get("tax_scope", "Eukaryota"))
        target = str(parameters.get("target_taxon", "2759"))
        if not re.fullmatch(r"[A-Za-z0-9_]+", scope) or not target.isdigit() or int(target) < 1:
            raise ResearchError(
                "eggNOG requires a named/numeric taxonomic scope and positive target taxon ID"
            )
        if not config.eggnog_data or not Path(config.eggnog_data).is_dir():
            raise ResearchError(
                "Configure an installed eggNOG database directory before annotation"
            )
        run_command(
            arguments=[config.emapper, "--version"],
            output=output,
            config=config,
            stdout=output / "annotation_tool_version.txt",
        )
        run_command(
            arguments=[
                config.emapper,
                "-i",
                str(normalised),
                "--itype",
                "proteins",
                "-m",
                "diamond",
                "--output",
                "annotation",
                "--output_dir",
                str(output),
                "--data_dir",
                config.eggnog_data,
                "--cpu",
                str(config.threads),
                "--tax_scope",
                scope,
                "--target_taxa",
                target,
                "--go_evidence",
                "non-electronic",
            ],
            output=output,
            config=config,
        )
        raw = output / "annotation.emapper.annotations"
        rows = []
        with raw.open(encoding="utf-8") as handle:
            header = None
            for line in handle:
                if line.startswith("#query\t"):
                    header = line.lstrip("#").rstrip("\n").split("\t")
                elif line.strip() and not line.startswith("#"):
                    values = line.rstrip("\n").split("\t")
                    if header is None or len(values) != len(header):
                        raise ResearchError("Unsupported eggNOG annotation table header")
                    record = dict(zip(header, values, strict=True))
                    if record["query"] not in sequences:
                        raise ResearchError(
                            "eggNOG returned an identifier outside the submitted proteins"
                        )
                    rows.append(
                        {
                            "sequence_id": record["query"],
                            "seed_ortholog": record.get("seed_ortholog", ""),
                            "description": record.get(
                                "Description", record.get("Preferred_name", "")
                            ),
                            "go_terms": record.get("GOs", ""),
                            "orthogroups": record.get("eggNOG_OGs", ""),
                            "tax_scope": scope,
                            "target_taxon": target,
                            "evidence_type": "ORTHOLOGY_BASED_FUNCTION_TRANSFER",
                        }
                    )
        columns = (
            "sequence_id",
            "seed_ortholog",
            "description",
            "go_terms",
            "orthogroups",
            "tax_scope",
            "target_taxon",
            "evidence_type",
        )
        artifacts[raw.name] = raw
    else:
        raise ResearchError("Unsupported sequence annotation engine")
    for row in rows:
        row["sequence_sha256"] = hashlib.sha256(sequences[row["sequence_id"]].encode()).hexdigest()
    columns = (*columns, "sequence_sha256")
    write_tsv(path=output / "annotations.tsv", rows=rows, columns=columns)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["sequence_id"]] = counts.get(row["sequence_id"], 0) + 1
    audit = [
        {
            "sequence_id": identifier,
            "engine": engine,
            "annotation_record_count": counts.get(identifier, 0),
            "status": "PREDICTED_ANNOTATION" if identifier in counts else "NO_HIT_REPORTED",
            "interpretation": "Computational prediction; function needs experimental review",
        }
        for identifier in sequences
    ]
    write_tsv(
        path=output / "annotation_audit.tsv",
        rows=audit,
        columns=("sequence_id", "engine", "annotation_record_count", "status", "interpretation"),
    )
    artifacts.update(
        {
            "annotations.tsv": output / "annotations.tsv",
            "annotation_audit.tsv": output / "annotation_audit.tsv",
        }
    )
    return artifacts
