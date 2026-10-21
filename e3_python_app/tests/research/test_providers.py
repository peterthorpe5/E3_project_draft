"""Provider consent, payload, model sequence and annotation evidence contracts."""

from contextlib import nullcontext
from dataclasses import replace
import hashlib
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

from e3app.research import providers
from e3app.research.common import ResearchError
from e3app.research.providers import (
    annotate_batch,
    http_request,
    local_esmfold,
    parse_interpro,
    pdb_evidence,
    predict_batch,
    predict_one,
    remote_interpro,
)


def test_http_redirects_limits_and_errors(monkeypatch):
    """Tokens remain on the configured HTTPS host and result bytes stay bounded."""
    response = Mock(status_code=200)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    response.iter_content.return_value = [b"AB", b"CD"]
    request = Mock(return_value=response)
    monkeypatch.setattr(requests, "request", request)
    assert http_request(url="https://example.org/fold", body=b"AC") == b"ABCD"
    assert request.call_args.kwargs["allow_redirects"] is False
    response.iter_content.return_value = [b"ABCDE"]
    with pytest.raises(ResearchError, match="size bound"):
        http_request(url="https://example.org/fold", maximum_bytes=4)
    response.status_code = 307
    with pytest.raises(ResearchError, match="HTTP 307"):
        http_request(url="https://example.org/fold")
    request.side_effect = requests.Timeout("secret message")
    with pytest.raises(ResearchError, match="unavailable"):
        http_request(url="https://example.org/fold")
    for url in (
        "http://example.org",
        "https://name:secret@example.org",
        "https://example.org/?token=secret",
        "https://example.org/#x",
    ):
        with pytest.raises(ResearchError):
            http_request(url=url)


def test_model_evidence_and_atlas_cache(research_config, model_pdb, monkeypatch):
    """Complete exact-sequence models alone become reusable cache entries."""
    records = pdb_evidence(pdb=model_pdb, expected_sequence="AC")
    assert [row["confidence_b_factor"] for row in records] == [80, 90]
    assert records[0]["x"] == 1
    for pdb, expected in (
        ("bad", "AC"),
        (model_pdb, "AA"),
        (model_pdb.replace("80.00", "-1.00"), "AC"),
    ):
        with pytest.raises(ResearchError):
            pdb_evidence(pdb=pdb, expected_sequence=expected)
    remote = Mock(return_value=model_pdb.encode())
    monkeypatch.setattr(providers, "http_request", remote)
    path, evidence, reused = predict_one(
        sequence="AC", engine="atlas", config=research_config, remote_allowed=True
    )
    assert not reused and path.read_text() == model_pdb
    assert remote.call_args.kwargs["body"] == b"AC"
    assert predict_one(sequence="AC", engine="atlas", config=research_config, remote_allowed=True)[
        2
    ]
    assert remote.call_count == 1
    for kwargs in (
        {"sequence": "AC", "engine": "atlas"},
        {"sequence": "A" * 401, "engine": "atlas", "remote_allowed": True},
        {"sequence": "AB", "engine": "local"},
        {"sequence": "AC", "engine": "bad"},
        {"sequence": "AC", "engine": "huggingface_endpoint", "remote_allowed": True},
    ):
        with pytest.raises(ResearchError):
            predict_one(config=research_config, **kwargs)


def test_dedicated_endpoint_and_exclusive_model_lock(research_config, model_pdb, monkeypatch):
    """Dedicated endpoints support JSON or raw PDB and use server-held tokens."""
    config = replace(research_config, esm_endpoint="https://endpoint.example/fold")
    monkeypatch.setenv("HF_TOKEN", "not-logged")
    remote = Mock(return_value=json.dumps({"pdb": model_pdb}).encode())
    monkeypatch.setattr(providers, "http_request", remote)
    path, _, _ = predict_one(
        sequence="AC", engine="huggingface_endpoint", config=config, remote_allowed=True
    )
    assert remote.call_args.kwargs["headers"]["Authorization"] == "Bearer not-logged"
    assert json.loads(remote.call_args.kwargs["body"])["inputs"] == "AC"
    path.unlink()
    lock = path.with_suffix(".lock")
    lock.touch()
    with pytest.raises(ResearchError, match="already being computed"):
        predict_one(
            sequence="AC", engine="huggingface_endpoint", config=config, remote_allowed=True
        )
    lock.unlink()
    remote.return_value = b'{"not_pdb":"bad"}'
    with pytest.raises(ResearchError, match="pdb field"):
        predict_one(
            sequence="AC", engine="huggingface_endpoint", config=config, remote_allowed=True
        )
    assert not lock.exists()
    remote.return_value = model_pdb.encode()
    assert predict_one(
        sequence="AC", engine="huggingface_endpoint", config=config, remote_allowed=True
    )[0].is_file()


def test_local_inference_pins_weights_and_converts_confidence(model_pdb, monkeypatch):
    """Transformers fractional lDDT is converted to the documented percent scale."""
    model = Mock()
    model.eval.return_value = model
    model.to.return_value = model
    model.infer.return_value = {"plddt": 0.8}
    model.output_to_pdb.return_value = [model_pdb]
    factory = Mock(from_pretrained=Mock(return_value=model))
    torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True, empty_cache=Mock()),
        inference_mode=nullcontext,
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(EsmForProteinFolding=factory))
    assert local_esmfold(sequence="AC", revision="pinned") == model_pdb
    assert factory.from_pretrained.call_args.kwargs["revision"] == "pinned"
    assert model.output_to_pdb.call_args.args[0]["plddt"] == 80
    model.trunk.set_chunk_size.assert_called_once_with(128)
    monkeypatch.setitem(sys.modules, "transformers", None)
    with pytest.raises(ResearchError, match="optional"):
        local_esmfold(sequence="AC", revision="pinned")


def test_prediction_batch_audits_partial_failures(
    research_config, model_pdb, tmp_path, monkeypatch
):
    """Every attempt is retained when a second sequence is rejected by the provider."""
    source = tmp_path / "input.fasta"
    source.write_text(">ok\nAC\n>bad\nAB\n")
    monkeypatch.setattr(providers, "http_request", Mock(return_value=model_pdb.encode()))
    output = tmp_path / "out"
    output.mkdir()
    result = predict_batch(
        config=research_config,
        source=source,
        output=output,
        parameters={"engine": "atlas", "remote_allowed": True},
    )
    table = pd.read_csv(result["predictions.tsv"], sep="\t")
    assert table.status.tolist() == ["PREDICTED", "FAILED"]
    assert table.loc[0, "mean_reported_confidence"] == 85
    assert table.loc[0, "sequence_sha256"] == hashlib.sha256(b"AC").hexdigest()
    output = tmp_path / "failure"
    output.mkdir()
    with pytest.raises(ResearchError, match="No model"):
        predict_batch(config=research_config, source=source, output=output, parameters={})
    assert (output / "predictions.tsv").is_file()


def interpro_row(identifier="a", sequence="ACDE", start=1, end=3):
    """Construct one standard InterProScan hit with a valid input checksum."""
    md5 = hashlib.md5(sequence.encode(), usedforsecurity=False).hexdigest()
    return (
        f"{identifier}\t{md5}\t{len(sequence)}\tPfam\tPF00001\tDomain\t{start}\t{end}"
        "\t1e-9\tT\t21-10-2026\tIPR1\tExample\tGO:0000001\n"
    )


def test_interpro_exact_sequence_and_coordinates(tmp_path):
    """Inclusive protein-domain coordinates require the exact submitted sequence."""
    path = tmp_path / "interpro.tsv"
    path.write_text(interpro_row())
    records = parse_interpro(path=path, sequences={"a": "ACDE"})
    assert records[0]["start"] == 1 and records[0]["end"] == 3
    for row in (
        interpro_row(start=0),
        interpro_row(end=5),
        interpro_row(identifier="unknown"),
        interpro_row(sequence="AAAA"),
        "malformed\n",
        interpro_row().replace("\t1\t3\t", "\tx\t3\t"),
    ):
        path.write_text(row)
        with pytest.raises(ResearchError):
            parse_interpro(path=path, sequences={"a": "ACDE"})


def test_remote_interpro_polling_and_checkpoint(research_config, tmp_path, monkeypatch):
    """Service IDs persist and repeated polling never resubmits the protein input."""
    config = replace(research_config, email="researcher@example.org", command_timeout=30)
    with pytest.raises(ResearchError):
        remote_interpro(
            sequences={"a": "ACDE"}, output=tmp_path, config=config, remote_allowed=False
        )
    remote = Mock(side_effect=[b"iprscan5-test", b"RUNNING", b"FINISHED", interpro_row().encode()])
    monkeypatch.setattr(providers, "http_request", remote)
    monkeypatch.setattr(providers.time, "sleep", Mock())
    path = remote_interpro(
        sequences={"a": "ACDE"}, output=tmp_path, config=config, remote_allowed=True
    )
    assert path.read_text() == interpro_row()
    remote.side_effect = [b"FINISHED", interpro_row().encode()]
    remote_interpro(sequences={"a": "ACDE"}, output=tmp_path, config=config, remote_allowed=True)
    assert remote.call_args_list[-2].kwargs["url"].endswith("/status/iprscan5-test")
    remote.side_effect = [b"FAILURE"]
    with pytest.raises(ResearchError, match="FAILURE"):
        remote_interpro(
            sequences={"a": "ACDE"}, output=tmp_path, config=config, remote_allowed=True
        )
    with pytest.raises(ResearchError, match="25"):
        remote_interpro(
            sequences={str(i): "ACDE" for i in range(26)},
            output=tmp_path,
            config=config,
            remote_allowed=True,
        )


def test_annotation_commands_and_no_hit_audit(research_config, tmp_path, monkeypatch):
    """InterPro and eukaryote-scoped eggNOG preserve predicted/no-hit evidence."""
    source = tmp_path / "source.fasta"
    source.write_text(">a\nACDE\n>b\nAAAA\n")
    calls = []

    def fake_command(*, arguments, output, config, stdout=None):
        calls.append(arguments)
        if stdout:
            stdout.write_text("provider v-test\n")
        elif "-f" in arguments:
            (output / "interpro.tsv").write_text(interpro_row())
        elif "--tax_scope" in arguments:
            (output / "annotation.emapper.annotations").write_text(
                "## eggNOG\n#query\tseed_ortholog\tDescription\tGOs\teggNOG_OGs\n"
                "a\tseed1\tProtein\tGO:1\tOG1\n"
            )

    monkeypatch.setattr(providers, "run_command", fake_command)
    output = tmp_path / "interpro"
    output.mkdir()
    result = annotate_batch(
        config=research_config,
        source=source,
        output=output,
        parameters={"engine": "interpro_local"},
    )
    audit = pd.read_csv(result["annotation_audit.tsv"], sep="\t")
    assert audit.status.tolist() == ["PREDICTED_ANNOTATION", "NO_HIT_REPORTED"]
    annotations = pd.read_csv(result["annotations.tsv"], sep="\t")
    assert annotations.loc[0, "sequence_sha256"] == hashlib.sha256(b"ACDE").hexdigest()
    output = tmp_path / "eggnog"
    output.mkdir()
    result = annotate_batch(
        config=replace(research_config, eggnog_data=str(tmp_path)),
        source=source,
        output=output,
        parameters={"engine": "eggnog"},
    )
    command = next(value for value in calls if "--tax_scope" in value)
    assert command[command.index("--tax_scope") + 1] == "Eukaryota"
    assert command[command.index("--target_taxa") + 1] == "2759"
    assert "ORTHOLOGY_BASED_FUNCTION_TRANSFER" in result["annotations.tsv"].read_text()
    for i, parameters in enumerate(
        ({"engine": "eggnog"}, {"engine": "bad"}, {"engine": "eggnog", "tax_scope": "bad scope"})
    ):
        directory = tmp_path / f"invalid{i}"
        directory.mkdir()
        with pytest.raises(ResearchError):
            annotate_batch(
                config=research_config, source=source, output=directory, parameters=parameters
            )


def test_prediction_local_cpu_and_model_parse_failures(research_config, model_pdb, monkeypatch):
    """Local execution works without CUDA and malformed structures fail before caching."""
    model = Mock()
    model.eval.return_value = model
    model.to.return_value = model
    model.infer.return_value = {"plddt": 0.9}
    model.output_to_pdb.return_value = [model_pdb]
    factory = Mock(from_pretrained=Mock(return_value=model))
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: False), inference_mode=nullcontext
        ),
    )
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(EsmForProteinFolding=factory))
    path, _, reused = predict_one(sequence="AC", engine="local", config=research_config)
    assert path.exists() and not reused
    for value in (
        model_pdb.replace("   1.000", "     nan"),
        model_pdb.replace("   1.000", "   hello"),
    ):
        with pytest.raises(ResearchError):
            pdb_evidence(pdb=value, expected_sequence="AC")
    only_n = model_pdb.replace(" CA ", " N  ")
    with pytest.raises(ResearchError):
        pdb_evidence(pdb=only_n, expected_sequence="AC")


def test_remote_annotation_timeout_invalid_job_and_batch(research_config, tmp_path, monkeypatch):
    """Polling failures retain checkpoints and remote annotation normalises returned hits."""
    config = replace(research_config, email="name@example.org", command_timeout=1)
    checkpoint = tmp_path / "interpro_service_job.json"
    checkpoint.write_text('{"service_job_id":"invalid/ID"}')
    with pytest.raises(ResearchError, match="invalid job"):
        remote_interpro(
            sequences={"a": "ACDE"}, output=tmp_path, config=config, remote_allowed=True
        )
    checkpoint.write_text('{"service_job_id":"valid-id"}')
    monkeypatch.setattr(providers.time, "monotonic", Mock(side_effect=[0, 2]))
    with pytest.raises(ResearchError, match="timed out"):
        remote_interpro(
            sequences={"a": "ACDE"}, output=tmp_path, config=config, remote_allowed=True
        )
    source = tmp_path / "source.fasta"
    source.write_text(">a\nACDE\n")
    raw = tmp_path / "remote.tsv"
    raw.write_text(interpro_row())
    monkeypatch.setattr(providers, "remote_interpro", Mock(return_value=raw))
    result = annotate_batch(
        config=config,
        source=source,
        output=tmp_path,
        parameters={"engine": "interpro_remote", "remote_allowed": True},
    )
    assert "PF00001" in result["annotations.tsv"].read_text()


def test_eggnog_rejects_malformed_or_unknown_query_output(research_config, tmp_path, monkeypatch):
    """Unsupported annotation exports cannot be silently accepted as biological evidence."""
    source = tmp_path / "source.fasta"
    source.write_text(">a\nACDE\n")
    config = replace(research_config, eggnog_data=str(tmp_path))
    content = ["bad\trow\n"]

    def fake_command(*, arguments, output, config, stdout=None):
        """Write a deliberately invalid eggNOG provider table."""
        if stdout:
            stdout.write_text("version\n")
        else:
            (output / "annotation.emapper.annotations").write_text(content[0])

    monkeypatch.setattr(providers, "run_command", fake_command)
    for index, text in enumerate(("bad\trow\n", "#query\tDescription\nunknown\tProtein\n")):
        content[0] = text
        output = tmp_path / str(index)
        output.mkdir()
        with pytest.raises(ResearchError):
            annotate_batch(
                config=config, source=source, output=output, parameters={"engine": "eggnog"}
            )
