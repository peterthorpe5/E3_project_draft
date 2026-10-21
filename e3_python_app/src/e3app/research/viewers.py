"""Offline viewer documents with bounded, escaped, exact protein coordinates."""

from __future__ import annotations

import hashlib
from importlib.resources import files
import json
import re
from typing import Mapping, Sequence
from urllib.parse import urlparse

from .common import ResearchError, normalise_protein


def json_for_html(*, value: object) -> str:
    """Encode untrusted data inside an inert JSON script without HTML termination.

    Args:
        value: JSON-compatible viewer payload.

    Returns:
        JSON with markup-significant characters escaped.
    """
    return (
        json.dumps(value, allow_nan=False, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def viewer_asset(*, name: str) -> str:
    """Read a checksummed vendored upstream viewer asset from the installed package.

    Args:
        name: Exact maintained asset filename.

    Returns:
        UTF-8 JavaScript or CSS with its build-time checksum verified.

    Raises:
        ResearchError: If an asset is missing, unrecognised or changed.
    """
    root = files("e3app").joinpath("resources", "research_viewers")
    try:
        hashes = json.loads(root.joinpath("checksums.json").read_text(encoding="utf-8"))
        if name not in hashes or "/" in name or "\\" in name:
            raise ResearchError("Unrecognised protein viewer asset")
        content = root.joinpath(name).read_bytes()
        if hashlib.sha256(content).hexdigest() != hashes[name]:
            raise ResearchError("Protein viewer asset checksum differs")
        return content.decode("utf-8")
    except (OSError, ValueError, KeyError) as exc:
        raise ResearchError("Reinstall the package to restore its bundled protein viewers") from exc


def viewer_document(*, viewer: str, payload: Mapping[str, object]) -> str:
    """Create a self-contained JBrowse, AV2 or Nightingale document.

    Args:
        viewer: jbrowse, alignment or nightingale.
        payload: Validated sequence/alignment data for this viewer.

    Returns:
        Standalone HTML, containing locally bundled libraries and no CDN scripts.

    Raises:
        ResearchError: If the viewer name or payload size is invalid.
    """
    if viewer not in {"jbrowse", "alignment", "nightingale"}:
        raise ResearchError("Unknown protein viewer")
    encoded = json_for_html(value=payload)
    if len(encoded) > 30_000_000:
        raise ResearchError("Viewer input exceeds its explicit rendering bound")
    script = viewer_asset(name=f"{viewer}.js")
    script = re.sub(r"</script", r"<\\/script", script, flags=re.IGNORECASE)
    css = viewer_asset(name="alignment.css") if viewer == "alignment" else ""
    bootstrap = ""
    if viewer == "jbrowse":
        bootstrap = """
        const data = JSON.parse(document.getElementById('protein-data').textContent);
        try {
          window.proteinMSA = window.ReactMSAView.mount(document.getElementById('viewer'),
              {msa:data.msa, tree:data.tree || undefined, height:680, colorScheme:'clustal'});
          document.getElementById('status').textContent='JBrowse MSA · alignment and inferred tree';
        } catch(error) {
          document.getElementById('status').textContent='Viewer error: '+error.message;
        }
        """
    return (
        """<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Protein research viewer</title><style>
    html,body{margin:0;font-family:Arial,sans-serif;background:white;color:#18243b}
    #status{padding:8px;font-size:13px}#viewer{height:680px;width:100%;position:relative}
    nightingale-navigation,nightingale-sequence,nightingale-track{display:block;width:100%}
    """
        + css
        + '</style></head><body><div id="status" role="status">Loading viewer…</div>'
        + (
            '<div id="viewer"></div><script id="protein-data" type="application/json">'
            + encoded
            + "</script><script>"
            + script
            + "</script><script>"
            + bootstrap
            + "</script></body></html>"
        )
    )


def nightingale_features(
    *, sequence_id: str, sequence: str, annotations: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    """Map exact-sequence annotation hits to Nightingale's inclusive coordinate schema.

    Args:
        sequence_id: Exact selected protein identifier.
        sequence: Ungapped protein sequence.
        annotations: Normalised InterPro predictions, including sequence SHA-256.

    Returns:
        Validated Nightingale feature objects; non-positional eggNOG rows are excluded.

    Raises:
        ResearchError: If selected positional annotation evidence has a different sequence hash.
    """
    protein = normalise_protein(sequence=sequence)
    digest = hashlib.sha256(protein.encode()).hexdigest()
    result = []
    for row in annotations:
        if str(row.get("sequence_id", "")) != sequence_id or row.get("start") in {None, ""}:
            continue
        if row.get("sequence_sha256") != digest:
            raise ResearchError(
                "Annotation belongs to a different sequence version; coordinates were not reused"
            )
        try:
            start, end = int(row["start"]), int(row["end"])
        except (ValueError, TypeError) as exc:
            raise ResearchError("Protein feature coordinates must be integers") from exc
        if not 1 <= start <= end <= len(protein):
            raise ResearchError("Protein feature coordinates exceed the selected sequence")
        result.append(
            {
                "accession": str(row.get("signature_accession", "")),
                "description": str(row.get("description", "")),
                "color": "#5852a3",
                "locations": [{"fragments": [{"start": start, "end": end}]}],
            }
        )
    return result


def auspice_dataset_url(*, base_url: str, job_id: str) -> str:
    """Build a dataset URL for a configured self-hosted Auspice installation.

    Args:
        base_url: Browser-accessible HTTP(S) base, optionally including a proxy prefix.
        job_id: Generated dataset identifier.

    Returns:
        URL selecting the actual worker-produced divergence dataset.

    Raises:
        ResearchError: If the operator URL or job identifier is unsafe.
    """
    parsed = urlparse(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"[a-f0-9]{32}", job_id)
    ):
        raise ResearchError(
            "Configure a valid Auspice base URL without credentials or query parameters"
        )
    return base_url.rstrip("/") + "/" + job_id + "?m=div"
