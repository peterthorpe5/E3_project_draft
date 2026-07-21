"""Shared workflow test fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def package_root() -> Path:
    """Return the package root containing committed synthetic inputs."""

    return Path(__file__).resolve().parents[1]


@pytest.fixture
def synthetic_config(tmp_path: Path, package_root: Path) -> Path:
    """Create an isolated copy of the committed synthetic configuration."""

    config_dir = tmp_path / "config"
    fixture_dir = tmp_path / "tests" / "fixtures"
    config_dir.mkdir(parents=True)
    fixture_dir.mkdir(parents=True)
    for name in ("synthetic_proteomes.tsv", "synthetic_seeds.tsv", "synthetic_shortlist.tsv"):
        shutil.copy2(package_root / "config" / name, config_dir / name)
    for name in ("arabidopsis.faa", "human.faa"):
        shutil.copy2(package_root / "tests" / "fixtures" / name, fixture_dir / name)
    payload = yaml.safe_load((package_root / "config" / "synthetic.yaml").read_text())
    payload["run"]["project_root"] = str(tmp_path)
    payload["run"]["output_root"] = str(tmp_path / "runs")
    path = config_dir / "workflow.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path

