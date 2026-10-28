"""Checks for a public directory that does not imply a prepared scientific selection."""

from __future__ import annotations

from urllib.parse import urlparse

from e3app.alphafold_hog_bundle import AF3_INSPECTOR_URL
from e3app.external_actions import EMERALD_BASE_URL, MOLSTAR_VIEWER_BASE_URL
from e3app.external_resources import EXTERNAL_RESOURCES, PROTEIN_IMAGER_URL
from e3app.navigation import navigation_page_titles


def test_directory_reuses_maintained_viewers_without_exposing_submission_endpoints() -> None:
    """Browser shortcuts reuse tool roots and cannot submit a model or pair on render."""
    urls = {resource.name: resource.url for resource in EXTERNAL_RESOURCES}
    assert urls["Protein Imager"] == "https://3dproteinimaging.com/protein-imager/"
    assert urls["Protein Imager"] == PROTEIN_IMAGER_URL
    assert urls["Mol* Viewer"] == MOLSTAR_VIEWER_BASE_URL
    assert urls["EMERALD"] == EMERALD_BASE_URL
    assert urls["AlphaFold 3 Multi-Model Inspector"] == AF3_INSPECTOR_URL
    assert len(urls) == len(EXTERNAL_RESOURCES)
    for url in urls.values():
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc
        assert not parsed.query
        assert not parsed.fragment
        assert "/api/" not in parsed.path
        assert "rcsb.org" not in parsed.netloc


def test_directory_preparation_refers_to_available_contextual_pages() -> None:
    """Every tool identifies where its selection/files come from before manual hand-off."""
    pages = set(navigation_page_titles())
    for resource in EXTERNAL_RESOURCES:
        assert resource.source_pages
        assert set(resource.source_pages) <= pages
        assert resource.purpose
        assert len(resource.preparation) > 100
    by_name = {resource.name: resource for resource in EXTERNAL_RESOURCES}
    assert "recorded pocket chain" in by_name["Protein Imager"].preparation
    assert "does not transfer" in by_name["Protein Imager"].preparation
    assert "exact pair FASTA" in by_name["EMERALD"].preparation
    assert "selected-member ZIP" in by_name["AlphaFold 3 Multi-Model Inspector"].preparation
    assert "current database model" in by_name["AlphaFold Database"].preparation.lower()
