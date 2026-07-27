"""Regression checks against inherited AlphaFold test metadata and models."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .structure import compute_model_quality, parse_model_residues


def read_legacy_metadata(path: Path) -> list[dict[str, str]]:
    """Read inherited AlphaFold metadata CSV without changing NA semantics.

    Args:
        path: Legacy metadata CSV.

    Returns:
        Ordered metadata rows.

    Raises:
        FileNotFoundError: If the CSV is absent.
        ValueError: If the accession column is missing.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Legacy metadata CSV does not exist: {source}")
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "accession" not in reader.fieldnames:
            raise ValueError("Legacy metadata CSV must contain an accession column.")
        return [
            {
                str(key): "" if value is None else str(value).strip()
                for key, value in row.items()
                if key is not None
            }
            for row in reader
        ]


def parse_legacy_number(value: str) -> float | None:
    """Parse inherited numeric values, including explicit NA markers.

    Args:
        value: Legacy CSV value.

    Returns:
        Float or ``None``.
    """

    stripped = value.strip()
    if not stripped or stripped.upper() in {"NA", "NAN", "NONE", "NULL"}:
        return None
    return float(stripped)


def find_legacy_model(root: Path, accession: str) -> Path | None:
    """Find one inherited AlphaFold model for an accession.

    Args:
        root: Inherited testing directory.
        accession: Protein accession.

    Returns:
        Unique preferred model path, or ``None`` when absent.

    Raises:
        ValueError: If several equally preferred models are present.
    """

    directory = Path(root).expanduser().resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"Legacy testing directory does not exist: {directory}")
    matches = sorted(directory.rglob(f"AF-{accession}-F1-model_v*.cif"))
    if not matches:
        return None

    def model_version(path: Path) -> int:
        """Extract numeric AlphaFold file version for ordering."""

        stem = path.name.rsplit("_v", maxsplit=1)[-1].split(".", maxsplit=1)[0]
        return int(stem) if stem.isdigit() else -1

    highest_version = max(model_version(path) for path in matches)
    preferred = [path for path in matches if model_version(path) == highest_version]
    unique_resolved = sorted({path.resolve() for path in preferred})
    if len(unique_resolved) > 1:
        raise ValueError(
            f"Multiple inherited v{highest_version} models found for {accession}: "
            + ", ".join(str(path) for path in unique_resolved)
        )
    return unique_resolved[0]


def compare_legacy_metadata_row(
    row: dict[str, str],
    model_path: Path | None,
    mean_tolerance: float,
    fraction_tolerance: float,
) -> dict[str, Any]:
    """Compare one inherited metadata row with its retained model file.

    Args:
        row: Legacy metadata row.
        model_path: Located model or ``None``.
        mean_tolerance: Allowed mean pLDDT difference.
        fraction_tolerance: Allowed fraction >=70 difference.

    Returns:
        Regression result record.
    """

    accession = row["accession"]
    expected_mean = parse_legacy_number(row.get("globalMetricValue", ""))
    expected_fraction = parse_legacy_number(row.get("fractionModToHigh", ""))
    if model_path is None:
        expected_missing = expected_mean is None and expected_fraction is None
        return {
            "accession": accession,
            "status": "PASS" if expected_missing else "MISSING_MODEL",
            "model_path": None,
            "legacy_global_metric_value": expected_mean,
            "computed_mean_plddt": None,
            "mean_difference": None,
            "legacy_fraction_mod_to_high": expected_fraction,
            "computed_fraction_residues_ge_70": None,
            "fraction_difference": None,
            "message": (
                "Legacy metadata and model are both absent."
                if expected_missing
                else "Legacy metadata reports a model but no CIF was found."
            ),
        }

    residues = parse_model_residues(model_path)
    computed = compute_model_quality(accession, residues)
    mean_difference = (
        None
        if expected_mean is None
        else float(computed["mean_plddt"]) - expected_mean
    )
    fraction_difference = (
        None
        if expected_fraction is None
        else float(computed["fraction_residues_ge_70"]) - expected_fraction
    )
    mean_pass = (
        expected_mean is None
        or mean_difference is not None
        and abs(mean_difference) <= mean_tolerance
    )
    fraction_pass = (
        expected_fraction is None
        or fraction_difference is not None
        and abs(fraction_difference) <= fraction_tolerance
    )
    passed = mean_pass and fraction_pass
    return {
        "accession": accession,
        "status": "PASS" if passed else "FAIL",
        "model_path": str(model_path),
        "legacy_global_metric_value": expected_mean,
        "computed_mean_plddt": computed["mean_plddt"],
        "mean_difference": mean_difference,
        "legacy_fraction_mod_to_high": expected_fraction,
        "computed_fraction_residues_ge_70": computed[
            "fraction_residues_ge_70"
        ],
        "fraction_difference": fraction_difference,
        "message": (
            "Computed model pLDDT agrees with inherited metadata."
            if passed
            else "Computed model pLDDT differs from inherited metadata."
        ),
    }


def run_legacy_model_regression(
    testing_root: Path,
    metadata_csv: Path,
    mean_tolerance: float = 0.25,
    fraction_tolerance: float = 0.01,
) -> list[dict[str, Any]]:
    """Run model-level regression across inherited test metadata.

    Args:
        testing_root: Inherited testing-data root containing model CIFs.
        metadata_csv: Inherited AlphaFold metadata CSV.
        mean_tolerance: Allowed mean pLDDT difference.
        fraction_tolerance: Allowed fraction >=70 difference.

    Returns:
        One regression record per metadata accession.
    """

    rows = read_legacy_metadata(metadata_csv)
    return [
        compare_legacy_metadata_row(
            row=row,
            model_path=find_legacy_model(testing_root, row["accession"]),
            mean_tolerance=mean_tolerance,
            fraction_tolerance=fraction_tolerance,
        )
        for row in rows
    ]
