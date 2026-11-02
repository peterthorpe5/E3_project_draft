"""Generate synthetic offline protein viewer documents for browser smoke tests."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from e3app.research.viewers import viewer_document
from e3app.research.species_tree import species_display_tree


def main(*, argv: Sequence[str] | None = None) -> int:
    """Write bounded synthetic documents for each bundled viewer.

    Args:
        argv: Optional named command arguments.

    Returns:
        Zero after all viewer documents have been generated.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args(argv).output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "msa": ">query\nACDEFGHIKLMNPQRSTVWY\n>member\nACDEFGHIKLMNPQRSTVWF\n",
        "tree": "(query:0.1,member:0.2);",
        "sequence": "ACDEFGHIKLMNPQRSTVWY",
        "features": [
            {
                "accession": "SYNTHETIC_DOMAIN",
                "locations": [{"fragments": [{"start": 2, "end": 10}]}],
            }
        ],
    }
    for viewer in ("alignment", "jbrowse", "nightingale"):
        (output / f"{viewer}.html").write_text(
            viewer_document(viewer=viewer, payload=payload), encoding="utf-8"
        )
    (output / "nightingale-recorded.html").write_text(
        viewer_document(viewer="nightingale", payload={
            **payload, "sequence": "", "length": 100,
            "coordinate_scope": "Recorded annotation coordinates; amino-acid sequence not verified",
        }), encoding="utf-8",
    )
    species, _audit = species_display_tree(
        newick="(Human:1,Plant:1);", sequence_ids=["query", "member"],
        metadata={"query": {"species": "Human"}, "member": {"species": "Plant"}},
    )
    (output / "jbrowse-species.html").write_text(
        viewer_document(viewer="jbrowse", payload={**payload, "tree": species}), encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
