"""Run audited DIAMOND subclustering over an operator-configured SSH connection."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import BinaryIO, Mapping

from .analysis import subcluster
from .common import ResearchConfig, ResearchError, file_sha256
from .remote import MAX_REQUEST_BYTES, read_checked_archive, ssh_command, write_checked_archive

LOGGER = logging.getLogger(__name__)
MANIFEST = "subcluster_response.json"
CONTROLS = ("identity", "mutual_coverage", "evalue")
RESULTS = frozenset({
    "sequences.fasta", "native_membership.tsv", "exact_alignments.tsv", "membership.parquet",
    "membership.tsv", "subclusters.tsv", "subcluster_settings.json", "diamond_version.txt",
    "vm_commands.jsonl", "vm_worker.log",
})
BLOCK_BYTES = 1024 * 1024


def write_vm_subclusters(
    *, config: ResearchConfig, source: BinaryIO, destination: BinaryIO,
) -> None:
    """Receive the selected FASTA, run DIAMOND and return the audited artifacts.

    Args:
        config: VM-local profile, executable and resource limits.
        source: Request metadata on one line followed by the exact protein FASTA.
        destination: Binary output for the checked result ZIP.

    Raises:
        ResearchError: If the input envelope, checksum or resource bounds are invalid.
    """
    line = source.readline(MAX_REQUEST_BYTES + 1)
    if len(line) > MAX_REQUEST_BYTES or not line.endswith(b"\n"):
        raise ResearchError("Invalid VM subclustering request header")
    encoded = line[:-1]
    request = json.loads(encoded)
    if (
        not isinstance(request, dict) or set(request) != {"fasta_sha256", "parameters"}
        or not isinstance(request["fasta_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", request["fasta_sha256"])
        or not isinstance(request["parameters"], dict)
        or not set(request["parameters"]).issubset(CONTROLS)
    ):
        raise ResearchError("VM subclustering accepts a FASTA checksum and audit thresholds")
    config.workspace.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="subcluster-ssh-", dir=config.workspace) as temporary:
        output = Path(temporary)
        fasta = output / "input.fasta"
        size = 0
        with fasta.open(mode="xb") as handle:
            while block := source.read(BLOCK_BYTES):
                size += len(block)
                if size > config.transfer_max_bytes:
                    raise ResearchError("Subclustering FASTA exceeds transfer_max_bytes on the VM")
                handle.write(block)
        if not size or file_sha256(path=fasta) != request["fasta_sha256"]:
            raise ResearchError("Subclustering FASTA is empty or its checksum differs")
        worker_log = output / "worker.log"
        try:
            artifacts = subcluster(
                config=config, source=fasta, output=output, parameters=request["parameters"],
            )
        except ResearchError:
            if worker_log.is_file():
                with worker_log.open(mode="rb") as handle:
                    handle.seek(max(0, worker_log.stat().st_size - 16_384))
                    LOGGER.error("DIAMOND on the VM:\n%s", handle.read().decode(errors="replace"))
            raise
        artifacts.update({
            "vm_commands.jsonl": output / "commands.jsonl", "vm_worker.log": worker_log,
        })
        write_checked_archive(
            config=config, request=encoded, artifacts=artifacts, manifest_name=MANIFEST,
            destination=destination,
        )


def subcluster_on_vm(
    *, config: ResearchConfig, source: Path, output: Path, parameters: Mapping[str, object],
) -> dict[str, Path]:
    """Send the chosen FASTA via SSH and return request-bound subclustering results.

    Args:
        config: App-host profile with the SSH alias, VM executable and VM profile.
        source: Exact input protein FASTA resolved from the queued request.
        output: Owned local job directory.
        parameters: Saved clustering thresholds and input provenance.

    Returns:
        Verified local copies of the scientific artifacts and the SSH log.

    Raises:
        ResearchError: If the input or returned response is invalid or the VM call fails.
    """
    command = ssh_command(config=config, command="run-subcluster")
    if source.stat().st_size > config.transfer_max_bytes:
        raise ResearchError("Subclustering FASTA exceeds transfer_max_bytes on the app host")
    header = json.dumps(
        {
            "fasta_sha256": file_sha256(path=source),
            "parameters": {name: parameters[name] for name in CONTROLS if name in parameters},
        },
        sort_keys=True, allow_nan=False,
    ).encode()
    if len(header) >= MAX_REQUEST_BYTES:
        raise ResearchError("Subclustering parameters exceed the VM request limit")
    log = output / "subcluster_ssh.log"
    LOGGER.info("Sending selected subclustering FASTA to SSH destination %s", config.remote_host)
    with tempfile.TemporaryDirectory(prefix="subcluster-transfer-", dir=output) as temporary:
        response = Path(temporary) / "response.zip"
        with tempfile.TemporaryFile(dir=temporary) as request:
            request.write(header + b"\n")
            with source.open(mode="rb") as fasta:
                shutil.copyfileobj(fsrc=fasta, fdst=request, length=BLOCK_BYTES)
            request.seek(0)
            try:
                with response.open(mode="wb") as handle, log.open(mode="wb") as diagnostics:
                    completed = subprocess.run(
                        args=command, stdin=request, stdout=handle, stderr=diagnostics,
                        timeout=config.command_timeout, check=False,
                    )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ResearchError(
                    "Subclustering SSH failed. Inspect subcluster_ssh.log."
                ) from exc
            if completed.returncode:
                raise ResearchError(
                    f"Subclustering VM command returned {completed.returncode}. "
                    "Inspect subcluster_ssh.log for SSH, installation or DIAMOND errors."
                )
        results = read_checked_archive(
            config=config, request=header, manifest_name=MANIFEST, source=response, output=output,
            expected_artifacts=RESULTS,
        )
    results[log.name] = log
    return results
