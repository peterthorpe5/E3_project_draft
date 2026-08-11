"""Defensive parsing of the structure-guided chemistry configuration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from e3chemistry.errors import ConfigurationError
from e3chemistry.licensing import validate_licence_policy
from e3chemistry.models import ChemistryConfig, ComponentLicence

SCREENING_MODES = frozenset({"prepare_only", "open_fragment_screen"})


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    """Return a string-keyed mapping or raise a configuration error."""
    if value is None:
        return {}
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ConfigurationError(f"{label} must be a mapping with string keys")
    return value


def _positive_integer(value: Any, label: str) -> int:
    """Return a validated positive integer."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigurationError(f"{label} must be a positive integer")
    return value


def _bounded_positive_integer(
    value: Any,
    *,
    label: str,
    maximum: int,
) -> int:
    """Return a positive integer not exceeding a defensive upper bound."""
    result = _positive_integer(value, label)
    if result > maximum:
        raise ConfigurationError(f"{label} must not exceed {maximum}")
    return result


def _fraction(value: Any, label: str) -> float:
    """Return a finite fraction between zero and one."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigurationError(f"{label} must be numeric")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ConfigurationError(f"{label} must be between 0 and 1")
    return result


def _path(value: Any, *, base: Path, label: str) -> Path | None:
    """Resolve one optional path relative to the configuration file."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ConfigurationError(f"{label} must be a path string or null")
    candidate = Path(value).expanduser()
    return (candidate if candidate.is_absolute() else base / candidate).resolve()


def load_config(path: Path) -> ChemistryConfig:
    """Load and validate one chemistry configuration.

    Args:
        path: YAML configuration path.

    Returns:
        Immutable validated configuration.

    Raises:
        ConfigurationError: If the file is absent, malformed or unsafe.
    """
    source = path.expanduser().resolve()
    if not source.is_file():
        raise ConfigurationError(f"Configuration file does not exist: {source}")
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Could not read configuration {source}: {exc}") from exc
    root = _mapping(raw, "configuration")
    if root.get("schema_version") not in {2, 3}:
        raise ConfigurationError("schema_version must be 2 or 3")
    unknown_root = set(root).difference(
        {
            "schema_version",
            "method",
            "fragment_screening",
            "licensing",
            "provenance",
        }
    )
    if unknown_root:
        raise ConfigurationError(
            "Unknown top-level configuration keys: " + ", ".join(sorted(unknown_root))
        )
    method = _mapping(root.get("method"), "method")
    screening = _mapping(root.get("fragment_screening"), "fragment_screening")
    licensing = _mapping(root.get("licensing"), "licensing")
    provenance = _mapping(root.get("provenance"), "provenance")
    allowed_sections = {
        "method": {
            "name",
            "maximum_candidate_groups",
            "minimum_conserved_component_fraction",
            "minimum_chemical_group_conservation",
            "minimum_mapping_fraction",
            "minimum_pocket_plddt_fraction",
            "minimum_druggability_score",
            "minimum_mapped_residue_count",
            "minimum_uniqueness_score",
            "high_confidence_conserved_component_fraction",
            "high_confidence_chemical_group_conservation",
            "high_confidence_pocket_plddt_fraction",
            "high_confidence_druggability_score",
            "high_confidence_mapped_residue_count",
            "maximum_fragments_per_group",
        },
        "fragment_screening": {"mode", "fragment_library"},
        "licensing": {
            "allow_restricted_licence_tools",
            "declared_components",
        },
        "provenance": {"require_clean_tracked_source"},
    }
    for section_name, section in (
        ("method", method),
        ("fragment_screening", screening),
        ("licensing", licensing),
        ("provenance", provenance),
    ):
        unknown = set(section).difference(allowed_sections[section_name])
        if unknown:
            raise ConfigurationError(
                f"Unknown {section_name} keys: " + ", ".join(sorted(unknown))
            )
    method_name = method.get("name", "open_structure_guided_pharmacophore_v2")
    if method_name not in {
        "open_structure_guided_pharmacophore_v1",
        "open_structure_guided_pharmacophore_v2",
    }:
        raise ConfigurationError(
            "method.name must be open_structure_guided_pharmacophore_v1 or "
            "open_structure_guided_pharmacophore_v2"
        )
    mode = screening.get("mode", "prepare_only")
    if mode not in SCREENING_MODES:
        raise ConfigurationError(
            "fragment_screening.mode must be one of: " + ", ".join(sorted(SCREENING_MODES))
        )
    fragment_library = _path(
        screening.get("fragment_library"),
        base=source.parent,
        label="fragment_screening.fragment_library",
    )
    if mode == "open_fragment_screen" and fragment_library is None:
        raise ConfigurationError(
            "open_fragment_screen requires fragment_screening.fragment_library"
        )
    if fragment_library is not None and not fragment_library.is_file():
        raise ConfigurationError(f"Fragment library does not exist: {fragment_library}")
    allow_restricted = licensing.get("allow_restricted_licence_tools", False)
    if not isinstance(allow_restricted, bool):
        raise ConfigurationError(
            "licensing.allow_restricted_licence_tools must be a boolean"
        )
    raw_components = licensing.get("declared_components", [])
    if not isinstance(raw_components, list):
        raise ConfigurationError("licensing.declared_components must be a list")
    components = []
    for index, raw_component in enumerate(raw_components):
        component = _mapping(
            raw_component,
            f"licensing.declared_components[{index}]",
        )
        name = component.get("name")
        spdx = component.get("spdx")
        if not isinstance(name, str) or not name.strip():
            raise ConfigurationError(f"Component {index} has an invalid name")
        if not isinstance(spdx, str) or not spdx.strip():
            raise ConfigurationError(f"Component {index} has an invalid SPDX licence")
        components.append(ComponentLicence(name=name.strip(), spdx=spdx.strip()))
    validated_components = validate_licence_policy(
        allow_restricted_licence_tools=allow_restricted,
        components=components,
        fragment_screening_mode=mode,
    )
    require_clean_source = provenance.get("require_clean_tracked_source", True)
    if not isinstance(require_clean_source, bool):
        raise ConfigurationError(
            "provenance.require_clean_tracked_source must be a boolean"
        )
    canonical = json.dumps(root, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return ChemistryConfig(
        source_path=source,
        method_name=method_name,
        maximum_candidate_groups=_bounded_positive_integer(
            method.get("maximum_candidate_groups", 2500),
            label="method.maximum_candidate_groups",
            maximum=10000,
        ),
        minimum_conserved_component_fraction=_fraction(
            method.get("minimum_conserved_component_fraction", 0.5),
            "method.minimum_conserved_component_fraction",
        ),
        minimum_chemical_group_conservation=_fraction(
            method.get("minimum_chemical_group_conservation", 0.5),
            "method.minimum_chemical_group_conservation",
        ),
        minimum_mapping_fraction=_fraction(
            method.get("minimum_mapping_fraction", 0.8),
            "method.minimum_mapping_fraction",
        ),
        minimum_pocket_plddt_fraction=_fraction(
            method.get("minimum_pocket_plddt_fraction", 0.7),
            "method.minimum_pocket_plddt_fraction",
        ),
        minimum_druggability_score=_fraction(
            method.get("minimum_druggability_score", 0.5),
            "method.minimum_druggability_score",
        ),
        minimum_mapped_residue_count=_bounded_positive_integer(
            method.get("minimum_mapped_residue_count", 10),
            label="method.minimum_mapped_residue_count",
            maximum=10000,
        ),
        minimum_uniqueness_score=_fraction(
            method.get("minimum_uniqueness_score", 0.1),
            "method.minimum_uniqueness_score",
        ),
        high_confidence_conserved_component_fraction=_fraction(
            method.get("high_confidence_conserved_component_fraction", 0.75),
            "method.high_confidence_conserved_component_fraction",
        ),
        high_confidence_chemical_group_conservation=_fraction(
            method.get("high_confidence_chemical_group_conservation", 0.8),
            "method.high_confidence_chemical_group_conservation",
        ),
        high_confidence_pocket_plddt_fraction=_fraction(
            method.get("high_confidence_pocket_plddt_fraction", 0.9),
            "method.high_confidence_pocket_plddt_fraction",
        ),
        high_confidence_druggability_score=_fraction(
            method.get("high_confidence_druggability_score", 0.5),
            "method.high_confidence_druggability_score",
        ),
        high_confidence_mapped_residue_count=_bounded_positive_integer(
            method.get("high_confidence_mapped_residue_count", 10),
            label="method.high_confidence_mapped_residue_count",
            maximum=10000,
        ),
        maximum_fragments_per_group=_positive_integer(
            method.get("maximum_fragments_per_group", 100),
            "method.maximum_fragments_per_group",
        ),
        fragment_screening_mode=mode,
        fragment_library=fragment_library,
        allow_restricted_licence_tools=allow_restricted,
        declared_components=validated_components,
        require_clean_tracked_source=require_clean_source,
        digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
