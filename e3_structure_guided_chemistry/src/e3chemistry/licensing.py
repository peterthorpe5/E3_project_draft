"""Fail-closed policy for open-source runtime components."""

from __future__ import annotations

from collections.abc import Iterable

from e3chemistry.errors import ConfigurationError
from e3chemistry.models import ComponentLicence

APPROVED_OPEN_SOURCE_SPDX = frozenset(
    {
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "MIT",
        "MPL-2.0",
    }
)

REQUIRED_COMPONENTS = {
    "duckdb": "MIT",
    "gemmi": "MPL-2.0",
    "rdkit": "BSD-3-Clause",
}


def validate_licence_policy(
    *,
    allow_restricted_licence_tools: bool,
    components: Iterable[ComponentLicence],
    fragment_screening_mode: str,
) -> tuple[ComponentLicence, ...]:
    """Validate the declared components against the open-source allow-list.

    Args:
        allow_restricted_licence_tools: Unsafe opt-in value from configuration.
        components: Declared runtime components.
        fragment_screening_mode: Configured fragment-screening mode.

    Returns:
        Deterministically ordered component declarations.

    Raises:
        ConfigurationError: If restricted tools are allowed, an SPDX licence is
            not approved, declarations conflict or a required component is absent.
    """
    if allow_restricted_licence_tools:
        raise ConfigurationError(
            "licensing.allow_restricted_licence_tools must remain false"
        )
    ordered = tuple(sorted(components, key=lambda item: item.name.lower()))
    observed: dict[str, str] = {}
    for component in ordered:
        key = component.name.strip().lower()
        if not key:
            raise ConfigurationError("Declared component name must not be empty")
        if component.spdx not in APPROVED_OPEN_SOURCE_SPDX:
            raise ConfigurationError(
                f"Component {component.name!r} does not have an approved open-source "
                f"SPDX licence: {component.spdx!r}"
            )
        if key in observed and observed[key] != component.spdx:
            raise ConfigurationError(
                f"Conflicting licence declarations for component {component.name!r}"
            )
        observed[key] = component.spdx
    required = {"duckdb", "gemmi"}
    if fragment_screening_mode == "open_fragment_screen":
        required.add("rdkit")
    for component_name in sorted(required):
        expected = REQUIRED_COMPONENTS[component_name]
        if observed.get(component_name) != expected:
            raise ConfigurationError(
                f"Required open-source component {component_name!r} must be declared "
                f"with SPDX licence {expected!r}"
            )
    return ordered
