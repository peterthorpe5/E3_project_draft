"""Scientific and data-integrity validation checks for pipeline outputs."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence


def make_check(
    name: str,
    passed: bool,
    observed: Any,
    expected: Any,
    message: str,
) -> dict[str, Any]:
    """Create one standard validation record.

    Args:
        name: Stable check identifier.
        passed: Check outcome.
        observed: Observed value.
        expected: Expected value or criterion.
        message: Human-readable explanation.

    Returns:
        Validation record.
    """

    return {
        "check": name,
        "status": "PASS" if passed else "FAIL",
        "observed": observed,
        "expected": expected,
        "message": message,
    }


def check_unique_accessions(
    status_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Check that accession status has exactly one row per accession.

    Args:
        status_records: Accession-level status rows.

    Returns:
        Validation record.
    """

    accessions = [str(record.get("accession", "")) for record in status_records]
    duplicates = sorted(
        accession
        for accession, count in Counter(accessions).items()
        if accession and count > 1
    )
    passed = bool(accessions) and not duplicates and all(accessions)
    return make_check(
        "unique_nonempty_accessions",
        passed,
        ",".join(duplicates) if duplicates else len(accessions),
        "one non-empty row per accession",
        "Accession status must be non-empty and unique.",
    )


def check_success_has_model_quality(
    status_records: Sequence[Mapping[str, Any]],
    model_quality: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Check that each successful accession has model-quality evidence.

    Args:
        status_records: Accession-level status rows.
        model_quality: Model-quality rows.

    Returns:
        Validation record.
    """

    successful = {
        str(record["accession"])
        for record in status_records
        if record.get("status") == "SUCCESS"
    }
    quality_accessions = {str(record["accession"]) for record in model_quality}
    missing = sorted(successful.difference(quality_accessions))
    return make_check(
        "successful_accessions_have_model_quality",
        not missing,
        ",".join(missing) if missing else len(successful),
        len(successful),
        "Every successful accession must have one model-quality row.",
    )


def check_pocket_mapping_accounting(
    pocket_quality: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Check pocket mapping counts reconcile to predicted residue totals.

    Args:
        pocket_quality: Pocket-level confidence rows.

    Returns:
        Validation record.
    """

    failures: list[str] = []
    for record in pocket_quality:
        predicted = int(record["predicted_pocket_residue_count"])
        mapped = int(record["mapped_pocket_residue_count"])
        ambiguous = int(record["ambiguous_pocket_residue_count"])
        unmapped = int(record["unmapped_pocket_residue_count"])
        if predicted != mapped + ambiguous + unmapped:
            failures.append(
                f"{record['accession']}:{record['pocket_number']}"
            )
    return make_check(
        "pocket_mapping_counts_reconcile",
        not failures,
        ",".join(failures) if failures else len(pocket_quality),
        "predicted = mapped + ambiguous + unmapped",
        "No predicted pocket residue may disappear from mapping accounting.",
    )


def check_mapping_rows_match_quality_totals(
    mapping_records: Sequence[Mapping[str, Any]],
    pocket_quality: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Check residue mapping row counts match pocket quality denominators.

    Args:
        mapping_records: Residue-level mapping rows.
        pocket_quality: Pocket-level confidence rows.

    Returns:
        Validation record.
    """

    mapping_counts: dict[tuple[str, int], int] = defaultdict(int)
    for record in mapping_records:
        key = (str(record["accession"]), int(record["pocket_number"]))
        mapping_counts[key] += 1

    failures = []
    for record in pocket_quality:
        key = (str(record["accession"]), int(record["pocket_number"]))
        expected = int(record["predicted_pocket_residue_count"])
        if mapping_counts.get(key, 0) != expected:
            failures.append(f"{key[0]}:{key[1]}")
    return make_check(
        "mapping_rows_match_pocket_denominators",
        not failures,
        ",".join(failures) if failures else len(pocket_quality),
        "one mapping row per predicted pocket residue",
        "Pocket confidence denominators must match residue-level records.",
    )


def check_no_duplicate_mapping_rows(
    mapping_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Check residue mapping records are unique within each pocket.

    Args:
        mapping_records: Residue-level mapping rows.

    Returns:
        Validation record.
    """

    keys = [
        (
            str(record.get("accession", "")),
            int(record.get("pocket_number", -1)),
            str(record.get("label_chain", "")),
            record.get("label_seq_id"),
            str(record.get("auth_chain", "")),
            record.get("auth_seq_id"),
            str(record.get("insertion_code", "")),
        )
        for record in mapping_records
    ]
    duplicates = sum(count - 1 for count in Counter(keys).values() if count > 1)
    return make_check(
        "no_duplicate_pocket_residue_rows",
        duplicates == 0,
        duplicates,
        0,
        "Each predicted residue must appear once per pocket.",
    )


def check_model_threshold_flag(
    model_quality: Sequence[Mapping[str, Any]],
    minimum_fraction: float,
) -> dict[str, Any]:
    """Check model confidence flags match the configured fraction threshold.

    Args:
        model_quality: Model-quality rows.
        minimum_fraction: Required fraction of residues with pLDDT >=70.

    Returns:
        Validation record.
    """

    mismatches = []
    for record in model_quality:
        observed = float(record["fraction_residues_ge_70"])
        expected = observed >= minimum_fraction
        if bool(record.get("passes_model_confidence_threshold")) != expected:
            mismatches.append(str(record["accession"]))
    return make_check(
        "model_confidence_flags_match_threshold",
        not mismatches,
        ",".join(mismatches) if mismatches else len(model_quality),
        f"fraction_residues_ge_70 >= {minimum_fraction}",
        "Model confidence flags must be recomputable from numeric evidence.",
    )


def run_validation_checks(
    datasets: Mapping[str, Sequence[Mapping[str, Any]]],
    minimum_model_fraction: float,
) -> list[dict[str, Any]]:
    """Run the complete deterministic validation contract.

    Args:
        datasets: Pipeline output datasets.
        minimum_model_fraction: Model-level confidence threshold.

    Returns:
        Ordered validation records.
    """

    status_records = datasets.get("accession_status", [])
    model_quality = datasets.get("model_quality", [])
    mappings = datasets.get("pocket_residue_mappings", [])
    pocket_quality = datasets.get("pocket_quality", [])
    return [
        check_unique_accessions(status_records),
        check_success_has_model_quality(status_records, model_quality),
        check_model_threshold_flag(model_quality, minimum_model_fraction),
        check_pocket_mapping_accounting(pocket_quality),
        check_mapping_rows_match_quality_totals(mappings, pocket_quality),
        check_no_duplicate_mapping_rows(mappings),
    ]
