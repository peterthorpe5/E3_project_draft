"""Checksummed research result exchange over the configured SSH connection."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import logging
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
from typing import BinaryIO, Iterator, Mapping
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from e3app import __version__

from .catalogue import extract_clusters, open_catalogue, resolve_sequence_ids
from .common import ResearchConfig, ResearchError, file_sha256

LOGGER = logging.getLogger(__name__)
PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 2_000_000
MANIFEST_NAME = "deepclust_response.json"
SAFE_ARTIFACT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,150}$")


def request_bytes(*, request: Mapping[str, object]) -> bytes:
    """Validate and encode only supported read-only DeepClust requests.

    Args:
        request: Resolve/retrieve operation and exact string identifiers.

    Returns:
        Canonical, bounded UTF-8 JSON suitable for SSH standard input.

    Raises:
        ResearchError: If controls, identifiers or request size are invalid.
    """
    operation = request.get("operation")
    key = "identifiers" if operation == "resolve" else "cluster_ids"
    if operation not in {"resolve", "retrieve"} or set(request) != {"operation", key}:
        raise ResearchError("DeepClust exchange accepts only exact resolve/retrieve requests")
    identifiers = request[key]
    maximum = 10_000 if operation == "resolve" else 1_000
    if not isinstance(identifiers, list) or not 1 <= len(identifiers) <= maximum:
        raise ResearchError(f"DeepClust {operation} accepts 1 to {maximum} identifiers")
    if any(not isinstance(value, str) or not value.strip() or len(value) > 1_000
           or any(ord(character) < 32 for character in value) for value in identifiers):
        raise ResearchError("DeepClust identifiers must be non-empty, bounded single-line text")
    payload = json.dumps(request, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    if len(payload) > MAX_REQUEST_BYTES:
        raise ResearchError("DeepClust exchange request exceeds 2 MB")
    return payload


def ssh_command(
    *, config: ResearchConfig, command: str = "export-deepclust",
) -> list[str]:
    """Build a shell-free local SSH command using the existing operator connection.

    Args:
        config: Existing SSH alias and remote command/profile, without passwords.
        command: Supported research command accepting a standard-input request.

    Returns:
        Local argv; remote operands are individually shell-quoted by shlex.

    Raises:
        ResearchError: If the SSH destination or command/profile is unsafe or absent.
    """
    if command not in {"export-deepclust", "run-subcluster"}:
        raise ResearchError("Unsupported research SSH command")
    if not re.fullmatch(r"(?:[A-Za-z0-9_.-]+@)?[A-Za-z0-9][A-Za-z0-9_.-]*", config.remote_host):
        raise ResearchError("Configure remote_host as an existing SSH alias or user@host")
    for value in (config.remote_executable, config.remote_config):
        if not value or value.startswith("-") or any(ord(character) < 32 for character in value):
            raise ResearchError("Configure the installed remote command and research profile")
    remote = shlex.join([
        config.remote_executable, "--config", config.remote_config,
        command, "--request-stdin",
    ])
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=30", "--",
            config.remote_host, remote]


@contextmanager
def local_response(
    *, config: ResearchConfig, request: Mapping[str, object],
) -> Iterator[tuple[Path, dict[str, Path]]]:
    """Execute a read-only request on the configured worker/mount in a private temporary directory.

    Args:
        config: Worker-local mounted DeepClust paths and extraction limits.
        request: Validated operation and exact identifiers.

    Yields:
        Temporary root and audited result artifact paths.
    """
    request_bytes(request=request)
    parent = config.workspace / "exchange"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="deepclust-", dir=parent) as directory:
        root = Path(directory)
        if request["operation"] == "resolve":
            with open_catalogue(config=config) as connection:
                frame = resolve_sequence_ids(
                    connection=connection, identifiers=request["identifiers"],
                    prefixes=config.identifier_prefixes,
                )
            path = root / "global_cluster_mapping.tsv"
            frame.to_csv(path_or_buf=path, sep="\t", index=False)
            artifacts = {path.name: path}
        else:
            artifacts = extract_clusters(
                config=config, cluster_ids=request["cluster_ids"], output=root,
            )
        yield root, artifacts


def write_response(
    *, config: ResearchConfig, request: Mapping[str, object], destination: BinaryIO,
) -> None:
    """Stream only selected, checksummed artifacts through the command-line connection.

    Args:
        config: Remote profile and output budget.
        request: Supported exact request.
        destination: Binary standard output or an owned response file.

    Raises:
        ResearchError: If artifact names or response size violate the protocol.
    """
    with local_response(config=config, request=request) as (_root, artifacts):
        write_checked_archive(
            config=config, request=request_bytes(request=request), artifacts=artifacts,
            manifest_name=MANIFEST_NAME, destination=destination,
        )
        LOGGER.info("Exported DeepClust %s response: %d artifacts", request["operation"],
                    len(artifacts))


def write_checked_archive(
    *, config: ResearchConfig, request: bytes, artifacts: Mapping[str, Path],
    manifest_name: str, destination: BinaryIO,
) -> None:
    """Write a bounded result archive with a checksum inventory and request digest.

    Args:
        config: Sending profile and transfer budget.
        request: Encoded request, including the input digest if applicable.
        artifacts: Declared filenames and their result paths.
        manifest_name: Protocol-specific inventory filename.
        destination: Binary result stream.
    """
    inventory = []
    for name, path in sorted(artifacts.items()):
        if not SAFE_ARTIFACT.fullmatch(name) or name == manifest_name:
            raise ResearchError("Research response contains an unsafe artifact name")
        inventory.append({
            "name": name, "size_bytes": path.stat().st_size, "sha256": file_sha256(path=path),
        })
    if sum(row["size_bytes"] for row in inventory) > config.transfer_max_bytes:
        raise ResearchError("Research response exceeds transfer_max_bytes")
    manifest = {
        "protocol_version": PROTOCOL_VERSION, "application_version": __version__,
        "request_sha256": hashlib.sha256(request).hexdigest(), "artifacts": inventory,
    }
    with ZipFile(file=destination, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(zinfo_or_arcname=manifest_name, data=json.dumps(manifest))
        for name, path in sorted(artifacts.items()):
            archive.write(filename=path, arcname=name)


def read_response(
    *, config: ResearchConfig, request: Mapping[str, object], source: Path, output: Path,
) -> dict[str, Path]:
    """Validate a request-bound response before extracting any selected artifacts.

    Args:
        config: Receiving worker and transfer budget.
        request: Original request whose digest must match the response.
        source: Received response ZIP.
        output: Empty, owned request-result directory.

    Returns:
        Checksum-verified result paths, never archive-supplied arbitrary destinations.

    Raises:
        ResearchError: If the response is corrupt, mismatched, oversized or unsafe.
    """
    return read_checked_archive(
        config=config, request=request_bytes(request=request), manifest_name=MANIFEST_NAME,
        source=source, output=output,
    )


def read_checked_archive(
    *, config: ResearchConfig, request: bytes, manifest_name: str, source: Path, output: Path,
    expected_artifacts: frozenset[str] | None = None,
) -> dict[str, Path]:
    """Verify a bounded result archive before copying any of its files.

    Args:
        config: Receiving profile and transfer budget.
        request: Exact encoded request.
        manifest_name: Expected protocol-specific inventory filename.
        source: Received ZIP file.
        output: Owned destination directory.
        expected_artifacts: Exact result keys when the workflow has a fixed output set.

    Returns:
        Verified artifact paths inside the destination.
    """
    expected = hashlib.sha256(request).hexdigest()
    if source.stat().st_size > config.transfer_max_bytes:
        raise ResearchError("Research response exceeds transfer_max_bytes")
    try:
        with ZipFile(file=source) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(set(names)) or not 1 <= len(names) <= 5_000:
                raise ResearchError("Research response has duplicate or excessive members")
            if any(not SAFE_ARTIFACT.fullmatch(name) for name in names):
                raise ResearchError("Research response contains an unsafe artifact name")
            expanded = sum(item.file_size for item in infos)
            if expanded > config.transfer_max_bytes + MAX_REQUEST_BYTES:
                raise ResearchError("Expanded research response exceeds transfer_max_bytes")
            metadata = archive.getinfo(name=manifest_name)
            if metadata.file_size > MAX_REQUEST_BYTES:
                raise ResearchError("Research response metadata exceeds 2 MB")
            if expanded - metadata.file_size > config.transfer_max_bytes:
                raise ResearchError("Expanded research response exceeds transfer_max_bytes")
            manifest = json.loads(archive.read(name=manifest_name))
            if manifest["protocol_version"] != PROTOCOL_VERSION:
                raise ResearchError("Remote research exchange protocol version differs")
            if manifest["request_sha256"] != expected:
                raise ResearchError("Research response belongs to a different request")
            records = manifest["artifacts"]
            if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
                raise ResearchError("Research response artifact inventory is invalid")
            artifact_names = set(names) - {manifest_name}
            if len(records) != len(artifact_names) or {row["name"] for row in records} != (
                artifact_names
            ):
                raise ResearchError("Research response inventory does not match its files")
            if expected_artifacts is not None and artifact_names != expected_artifacts:
                raise ResearchError("Research response is missing or contains unexpected results")
            output.mkdir(parents=True, exist_ok=True)
            for row in records:
                info = archive.getinfo(name=row["name"])
                if info.file_size != row["size_bytes"]:
                    raise ResearchError("Research response artifact size differs")
                if (output / row["name"]).exists():
                    raise ResearchError("Refusing to replace an existing research result")
                digest = hashlib.sha256()
                with archive.open(name=row["name"]) as handle:
                    while block := handle.read(1024 * 1024):
                        digest.update(block)
                if digest.hexdigest() != row["sha256"]:
                    raise ResearchError("Research response artifact checksum differs")
            result = {}
            for row in records:
                path = output / row["name"]
                with archive.open(name=row["name"]) as incoming, path.open(mode="xb") as target:
                    while block := incoming.read(1024 * 1024):
                        target.write(block)
                result[path.name] = path
            return result
    except (BadZipFile, KeyError, TypeError, ValueError, OSError) as exc:
        raise ResearchError(f"Could not validate research response: {exc}") from exc


def exchange(
    *, config: ResearchConfig, request: Mapping[str, object], output: Path, transport: str,
) -> dict[str, Path]:
    """Run a mounted-worker or SSH command-line request outside the Streamlit process.

    Args:
        config: Operator profile including the established SSH connection.
        request: Exact selected DeepClust IDs and read-only operation.
        output: Owned job-result directory.
        transport: worker uses its mounted database; ssh uses the configured denbi command.

    Returns:
        Validated artifacts without downloading any global source database.

    Raises:
        ResearchError: If transport, remote execution or the response fails.
    """
    payload = request_bytes(request=request)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="exchange-", dir=output) as directory:
        response = Path(directory) / "response.zip"
        if transport == "worker":
            with response.open(mode="wb") as handle:
                write_response(config=config, request=request, destination=handle)
        elif transport == "ssh":
            command = ssh_command(config=config)
            log = output / "deepclust_ssh.log"
            try:
                with response.open(mode="wb") as handle, log.open(mode="wb") as diagnostics:
                    completed = subprocess.run(
                        args=command, input=payload, stdout=handle, stderr=diagnostics,
                        timeout=config.command_timeout, check=False,
                    )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ResearchError(
                    "DeepClust SSH request failed; inspect deepclust_ssh.log") from exc
            if completed.returncode:
                raise ResearchError(
                    f"DeepClust SSH command returned {completed.returncode}; "
                    "inspect deepclust_ssh.log and the configured host/profile"
                )
        else:
            raise ResearchError("DeepClust transport must be worker or ssh")
        result = read_response(config=config, request=request, source=response, output=output)
        if transport == "ssh":
            result["deepclust_ssh.log"] = log
        LOGGER.info("Completed DeepClust %s via %s: %d artifacts", request["operation"],
                    transport, len(result))
        return result
