"""Tests for whitespace-safe external-tool path aliases."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from e3_discovery.exceptions import ConfigurationError
from e3_discovery.path_safety import (
    ExternalToolPathAlias,
    _alias_name,
    _default_alias_parent,
    _resolve_alias_parent,
    path_contains_whitespace,
    prepare_external_tool_path_alias,
    write_path_alias_record,
)


class PathSafetyTests(unittest.TestCase):
    """Validate path alias creation, reuse, mapping and provenance."""

    def test_path_contains_whitespace(self):
        self.assertTrue(path_contains_whitespace(Path("/tmp/with space")))
        self.assertTrue(path_contains_whitespace(Path("/tmp/with\ttab")))
        self.assertFalse(path_contains_whitespace(Path("/tmp/without_space")))

    def test_alias_name_is_deterministic_and_safe(self):
        root = Path("/tmp/result root")
        first = _alias_name(root)
        second = _alias_name(root)
        self.assertEqual(first, second)
        self.assertRegex(first, r"^run_[0-9a-f]{16}$")

    def test_default_alias_parent_prefers_repository(self):
        config = Path("/tmp/repository/config/config.yaml")
        parent = _default_alias_parent(config)
        self.assertEqual(
            parent,
            Path("/tmp/repository/.e3_path_aliases"),
        )

    def test_default_alias_parent_falls_back_for_space_in_repository(self):
        config = Path("/tmp/repository with space/config/config.yaml")
        parent = _default_alias_parent(config)
        self.assertFalse(path_contains_whitespace(parent))
        self.assertEqual(parent.name, "e3_discovery_path_aliases")

    def test_resolve_alias_parent_uses_default_when_omitted(self):
        config = Path("/tmp/repository/config/config.yaml")
        parent = _resolve_alias_parent(config, None)
        self.assertEqual(
            parent,
            Path("/tmp/repository/.e3_path_aliases"),
        )

    def test_default_alias_parent_rejects_all_spaced_candidates(self):
        config = Path("/tmp/repository with space/config/config.yaml")
        with mock.patch(
            "e3_discovery.path_safety.tempfile.gettempdir",
            return_value="/tmp/also spaced",
        ):
            with self.assertRaises(ConfigurationError):
                _default_alias_parent(config)

    def test_resolve_alias_parent_accepts_relative_override(self):
        config = Path("/tmp/repository/config/config.yaml")
        parent = _resolve_alias_parent(config, "../safe_aliases")
        self.assertEqual(parent, Path("/tmp/repository/safe_aliases"))

    def test_resolve_alias_parent_rejects_whitespace(self):
        config = Path("/tmp/repository/config/config.yaml")
        with self.assertRaises(ConfigurationError):
            _resolve_alias_parent(config, "/tmp/unsafe aliases")

    def test_no_alias_when_root_has_no_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "results"
            alias = prepare_external_tool_path_alias(
                root,
                Path(tmp) / "config" / "config.yaml",
            )
            self.assertFalse(alias.alias_created)
            self.assertEqual(alias.real_root, root.absolute())
            self.assertEqual(alias.tool_root, root.absolute())

    def test_create_reuse_and_map_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "results with space"
            config = base / "repository" / "config" / "config.yaml"
            alias_parent = base / "aliases"

            first = prepare_external_tool_path_alias(
                root,
                config,
                str(alias_parent),
            )
            second = prepare_external_tool_path_alias(
                root,
                config,
                str(alias_parent),
            )

            self.assertTrue(first.alias_created)
            self.assertTrue(first.tool_root.is_symlink())
            self.assertEqual(first.tool_root.resolve(), root.resolve())
            self.assertEqual(first, second)
            mapped = first.map_path(root / "diamond" / "database.dmnd")
            self.assertEqual(
                mapped,
                first.tool_root / "diamond" / "database.dmnd",
            )
            self.assertFalse(path_contains_whitespace(mapped))

    def test_map_path_rejects_path_outside_root(self):
        alias = ExternalToolPathAlias(
            real_root=Path("/tmp/results"),
            tool_root=Path("/tmp/alias"),
            alias_created=True,
        )
        with self.assertRaises(ConfigurationError):
            alias.map_path(Path("/tmp/other/file.tsv"))

    def test_existing_non_symlink_alias_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "results with space"
            alias_parent = base / "aliases"
            alias_parent.mkdir()
            conflict = alias_parent / _alias_name(root.absolute())
            conflict.mkdir()
            with self.assertRaises(ConfigurationError):
                prepare_external_tool_path_alias(
                    root,
                    base / "config" / "config.yaml",
                    str(alias_parent),
                )

    def test_existing_alias_to_other_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "results with space"
            other = base / "other results"
            other.mkdir()
            alias_parent = base / "aliases"
            alias_parent.mkdir()
            conflict = alias_parent / _alias_name(root.absolute())
            conflict.symlink_to(other, target_is_directory=True)
            with self.assertRaises(ConfigurationError):
                prepare_external_tool_path_alias(
                    root,
                    base / "config" / "config.yaml",
                    str(alias_parent),
                )

    def test_write_path_alias_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "provenance" / "alias.json"
            alias = ExternalToolPathAlias(
                real_root=Path("/Volumes/One Touch/results"),
                tool_root=Path("/tmp/e3_alias/run_123"),
                alias_created=True,
            )
            written = write_path_alias_record(
                destination,
                alias,
                {"diamond_version": "2.2.3"},
            )
            payload = json.loads(written.read_text(encoding="utf-8"))
            self.assertEqual(payload["diamond_version"], "2.2.3")
            self.assertTrue(payload["alias_created"])
            self.assertIn("whitespace", payload["reason"])


if __name__ == "__main__":
    unittest.main()
