"""Configuration and fail-closed licence-policy tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from conftest import write_config
from e3chemistry.config import load_config
from e3chemistry.errors import ConfigurationError
from e3chemistry.licensing import validate_licence_policy
from e3chemistry.models import ComponentLicence


def test_prepare_only_configuration_is_valid(tmp_path: Path) -> None:
    """The minimal open structure route must not require RDKit."""
    config = load_config(write_config(tmp_path / "config.yaml"))

    assert config.fragment_screening_mode == "prepare_only"
    assert config.maximum_candidate_groups == 2500
    assert config.minimum_pocket_plddt_fraction == pytest.approx(0.7)
    assert config.minimum_druggability_score == pytest.approx(0.5)
    assert config.minimum_mapped_residue_count == 2
    assert config.digest
    assert {item.name for item in config.declared_components} == {"DuckDB", "Gemmi"}


def test_open_screen_resolves_relative_fragment_library(tmp_path: Path) -> None:
    """A relative fragment table must resolve from the YAML directory."""
    fragment_library = tmp_path / "fragments.tsv"
    fragment_library.write_text("fragment_id\tsmiles\nF1\tCC\n", encoding="utf-8")
    config_path = write_config(
        tmp_path / "config.yaml",
        mode="open_fragment_screen",
        fragment_library=Path("fragments.tsv"),
    )

    assert load_config(config_path).fragment_library == fragment_library.resolve()


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda data: data.update({"unknown": True}), "Unknown top-level"),
        (lambda data: data.update({"schema_version": 1}), "schema_version"),
        (
            lambda data: data["licensing"].update(
                {"allow_restricted_licence_tools": True}
            ),
            "must remain false",
        ),
        (
            lambda data: data["method"].update({"maximum_candidate_groups": 0}),
            "positive integer",
        ),
        (
            lambda data: data["method"].update({"maximum_candidate_groups": 10001}),
            "must not exceed 10000",
        ),
        (
            lambda data: data["method"].update(
                {"minimum_uniqueness_score": 1.5}
            ),
            "between 0 and 1",
        ),
        (
            lambda data: data["method"].update({"name": "FMOPhore"}),
            "open_structure_guided",
        ),
        (
            lambda data: data["method"].update({"unknown_method_key": True}),
            "Unknown method keys",
        ),
        (
            lambda data: data["fragment_screening"].update({"mode": "commercial"}),
            "mode must be one of",
        ),
        (
            lambda data: data["fragment_screening"].update(
                {"mode": "open_fragment_screen", "fragment_library": None}
            ),
            "requires fragment_screening.fragment_library",
        ),
        (
            lambda data: data["fragment_screening"].update({"fragment_library": 1}),
            "path string or null",
        ),
        (
            lambda data: data["licensing"].update(
                {"allow_restricted_licence_tools": "false"}
            ),
            "must be a boolean",
        ),
        (
            lambda data: data["licensing"].update({"declared_components": {}}),
            "must be a list",
        ),
        (
            lambda data: data["licensing"]["declared_components"][0].update(
                {"name": ""}
            ),
            "invalid name",
        ),
        (
            lambda data: data["licensing"]["declared_components"][0].update(
                {"spdx": ""}
            ),
            "invalid SPDX",
        ),
        (
            lambda data: data["provenance"].update(
                {"require_clean_tracked_source": "true"}
            ),
            "require_clean_tracked_source must be a boolean",
        ),
    ],
)
def test_invalid_configuration_fails_closed(
    tmp_path: Path,
    mutator: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    """Unsafe or unknown configuration values must not be ignored."""
    config_path = write_config(tmp_path / "config.yaml")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    mutator(data)
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        load_config(config_path)


def test_open_screen_requires_existing_library(tmp_path: Path) -> None:
    """Open screening must never continue with an unresolved chemical input."""
    config_path = write_config(
        tmp_path / "config.yaml",
        mode="open_fragment_screen",
        fragment_library=Path("missing.tsv"),
    )

    with pytest.raises(ConfigurationError, match="does not exist"):
        load_config(config_path)


def test_malformed_yaml_and_mapping_are_rejected(tmp_path: Path) -> None:
    """Unreadable YAML structures must not be interpreted as defaults."""
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("[", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Could not read"):
        load_config(malformed)

    wrong_mapping = tmp_path / "wrong_mapping.yaml"
    wrong_mapping.write_text("1: value\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="string keys"):
        load_config(wrong_mapping)

    null_config = tmp_path / "null.yaml"
    null_config.write_text("null\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="schema_version"):
        load_config(null_config)


def test_non_open_spdx_is_rejected() -> None:
    """Commercial or undefined licence labels are not permitted."""
    with pytest.raises(ConfigurationError, match="approved open-source"):
        validate_licence_policy(
            allow_restricted_licence_tools=False,
            components=(
                ComponentLicence(name="DuckDB", spdx="MIT"),
                ComponentLicence(name="Gemmi", spdx="Commercial"),
            ),
            fragment_screening_mode="prepare_only",
        )


def test_required_component_and_conflicting_declarations_are_rejected() -> None:
    """Missing or inconsistent component provenance must fail validation."""
    with pytest.raises(ConfigurationError, match="(?i)gemmi"):
        validate_licence_policy(
            allow_restricted_licence_tools=False,
            components=(ComponentLicence(name="DuckDB", spdx="MIT"),),
            fragment_screening_mode="prepare_only",
        )
    with pytest.raises(ConfigurationError, match="Conflicting"):
        validate_licence_policy(
            allow_restricted_licence_tools=False,
            components=(
                ComponentLicence(name="DuckDB", spdx="MIT"),
                ComponentLicence(name="duckdb", spdx="BSD-3-Clause"),
                ComponentLicence(name="Gemmi", spdx="MPL-2.0"),
            ),
            fragment_screening_mode="prepare_only",
        )
