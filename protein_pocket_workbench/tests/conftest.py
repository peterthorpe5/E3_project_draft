"""Reusable synthetic project fixtures; no biological results are fabricated."""

import shutil

import pytest

from pocket_workbench.demo import create_demo


@pytest.fixture(scope="session")
def demonstration(tmp_path_factory):
    """Build one known-transform project for end-to-end tests."""
    return create_demo(output=tmp_path_factory.mktemp("fixtures") / "demo")


@pytest.fixture
def project(demonstration, tmp_path):
    """Copy the fixture so mutation tests are independent."""
    destination = tmp_path / "project"
    shutil.copytree(demonstration, destination)
    return destination
