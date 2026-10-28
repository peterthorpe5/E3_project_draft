"""Generic group/HOG inventories and manual external-viewer hand-off bundles."""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import gemmi

from .core import WorkbenchError, inside

AF3_INSPECTOR_URL = "https://pdbms.altervista.org/af3viewer/afviewer8.html"


def source_link(*, value: str) -> str:
    """Keep only explicit HTTP(S) source links for external navigation.

    Args:
        value: User-supplied source URL.

    Returns:
        Original URL if valid; an empty string otherwise.
    """
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    return (
        value
        if parsed.scheme in {"https", "http"}
        and parsed.netloc
        and not parsed.username
        and not parsed.password
        else ""
    )


def inspector_bundle(*, root: Path, models: list[dict]) -> bytes:
    """Package existing local models using the E3 Inspector naming convention.

    Args:
        root: Native resource directory.
        models: Explicit selected models from one or more groups.

    Returns:
        ZIP containing mmCIF coordinates, model-index manifest and interpretation.
    """
    if not models or len(models) > 1000:
        raise WorkbenchError("Choose 1–1,000 existing local models")
    stream, manifest, total = io.BytesIO(), [], 0
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, model in enumerate(models):
            record = {
                "model_index": index,
                "sample_id": model["sample_id"],
                "group_id": model.get("group_id", ""),
                "hog_id": model.get("hog_id", ""),
                "sequence_id": model.get("sequence_id", ""),
                "source_url": source_link(value=model.get("source_url", "")),
                "status": "coordinates_missing",
                "sha256": "",
                "pae_status": "not_supplied",
                "af3_summary_status": "not_supplied",
            }
            if model.get("prepared_model"):
                path = inside(root=root, relative=model["prepared_model"])
                structure = gemmi.read_structure(str(path))
                content = structure.make_mmcif_document().as_string().encode()
                total += len(content)
                if total > 512 * 1024**2:
                    raise WorkbenchError("Selected model bundle exceeds 512 MiB")
                archive.writestr(f"workbench_model_{index}.cif", content)
                record.update(
                    status="included_prepared_target_chain",
                    sha256=hashlib.sha256(content).hexdigest(),
                )
            manifest.append(record)
        table = io.StringIO()
        writer = csv.DictWriter(table, fieldnames=list(manifest[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(manifest)
        archive.writestr("manifest.tsv", table.getvalue())
        archive.writestr(
            "README.txt",
            "Manual hand-off to the AlphaFold 3 Multi-Model Inspector:\n"
            f"{AF3_INSPECTOR_URL}\n\n"
            "Download this ZIP, open the external source and upload it yourself. "
            "The workbench does not send models to that site.\n"
            "Files use the same model_<index>.cif naming convention as the E3 "
            "HOG compatibility exporter. manifest.tsv maps model indices to "
            "original project IDs and groups. Coordinates are the prepared target "
            "protein chains, converted to mmCIF without inventing AF3 metrics.\n"
            "PAE, pTM, ipTM, ranking and chain-pair metrics are not supplied. "
            "Missing values are unknown. Distinct group members are not necessarily "
            "alternative predictions of the same sequence. Use recorded project "
            "alignments for residue equivalence and fitted pocket comparisons.\n"
            "The external website is maintained independently. The bundled "
            "offline workbench views provide a separate local option.\n",
        )
    return stream.getvalue()
