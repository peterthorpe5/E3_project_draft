"""Batch-first preparation of portable app resources on a compute node."""

from __future__ import annotations

import itertools
import logging
import shutil
from dataclasses import asdict, replace
from pathlib import Path

from .comparison import compare_batch
from .core import ComparisonSettings, WorkbenchError, load_project, utc_now, write_json
from .importing import import_project
from .reporting import export_review
from .runtime import available_cpus, execution_info
from .sequences import analyse_sequences

LOGGER = logging.getLogger(__name__)


def build_resource(
    *,
    resource: Path | None,
    sources: list[Path] | None,
    output: Path | None,
    review_output: Path,
    fasta: Path | None = None,
    mapping: Path | None = None,
    title: str = "Protein pocket project",
    chain: str = "",
    confidence: str = "plddt",
    comparison_mode: str = "all_pairs",
    reference: str | None = None,
    settings: ComparisonSettings | None = None,
    aligners: list[str] | None = None,
    usalign: str = "USalign",
    tmalign: str = "TMalign",
    workers: int = 4,
    threads: int = 8,
    bootstrap: int = 100,
    seed: int = 42,
    sequence_engine: str = "famsa",
) -> int:
    """Import existing pockets, calculate structures/sequences and publish reviews.

    Args:
        resource: Existing native resource for an explicit resume.
        sources: Original pipeline run plus matching raw AlphaFold models.
        output: New resource directory when importing sources.
        review_output: New portable review directory and sibling ZIP.
        fasta: Representative protein FASTA for import.
        mapping: Optional exact sample-to-FASTA TSV.
        title: Generic project title.
        chain: Optional selected protein chain.
        confidence: plddt for AlphaFold or none for other structures.
        comparison_mode: all_pairs, reference or none.
        reference: Exact model ID for reference comparisons.
        settings: Shared fit and pocket thresholds.
        aligners: Independent structural engines, normally USalign and TMalign.
        usalign: USalign executable.
        tmalign: TMalign executable.
        workers: Concurrent independent structure comparisons.
        threads: FAMSA or MAFFT threads, not simultaneous with comparisons.
        bootstrap: Seeded exploratory tree bootstrap count.
        seed: Reproducible tree seed.
        sequence_engine: famsa or mafft.

    Returns:
        Zero for complete analyses; two when comparison failures are retained.
    """
    if bool(resource) == bool(sources):
        raise WorkbenchError("Supply --resource or one or more --input options")
    review_output = review_output.expanduser().resolve()
    if review_output.exists() or review_output.with_suffix(".zip").exists():
        raise WorkbenchError("Choose a new review output before starting the build")
    if comparison_mode not in {"all_pairs", "reference", "none"}:
        raise WorkbenchError("Choose all_pairs, reference or none")
    if not 1 <= workers <= available_cpus() or not 1 <= threads <= available_cpus():
        raise WorkbenchError(
            f"Workers and threads must fit the {available_cpus()} available CPUs"
        )
    if comparison_mode == "reference" and not reference:
        raise WorkbenchError("Reference mode requires --reference MODEL_ID")
    settings = settings or ComparisonSettings(
        engine="usalign",
        fit_scope="global",
        min_plddt=0,
        top_pockets=5,
        confident_only=False,
    )
    if settings.start is not None and comparison_mode != "reference":
        raise WorkbenchError("Domain fitting requires one named reference")
    aligners = list(dict.fromkeys(aligners or ["usalign", "tmalign"]))
    if set(aligners) - {"usalign", "tmalign", "sequence_kabsch"}:
        raise WorkbenchError("Choose USalign, TMalign or paired sequence Kabsch")
    if comparison_mode != "none":
        for engine, executable in [("usalign", usalign), ("tmalign", tmalign)]:
            if engine in aligners and not shutil.which(executable):
                raise WorkbenchError(
                    f"Missing {engine}; create the supplied Conda environment"
                )
    if sources:
        if output is None:
            raise WorkbenchError("Import builds require --output RESOURCE_DIRECTORY")
        root = import_project(
            sources=sources,
            output=output,
            title=title,
            fasta=fasta,
            mapping=mapping,
            chain=chain,
            confidence=confidence,
        )
    else:
        root = resource.expanduser().resolve()
        load_project(root=root)
    state = {
        "started_utc": utc_now(),
        "execution": execution_info(root=root),
        "aligners": aligners,
        "comparison_mode": comparison_mode,
        "workers": workers,
        "threads": threads,
        "bootstrap": bootstrap,
        "seed": seed,
        "settings": asdict(settings),
        "reference": reference,
        "sequence_engine": sequence_engine,
        "review_output": str(review_output.expanduser().resolve()),
    }
    status_path = root / "provenance" / "build_status.json"
    (root / "logs").mkdir(exist_ok=True)
    handler = logging.FileHandler(root / "logs" / "build.log")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logging.getLogger().addHandler(handler)
    try:
        state["stage"] = "sequence_alignment_and_tree"
        write_json(path=status_path, value=state)
        LOGGER.info("Building representative sequence alignment and tree")
        data = load_project(root=root)
        if data["sequences"]:
            analyse_sequences(
                root=root,
                sequence_ids=list(data["sequences"]),
                engine=sequence_engine,
                threads=threads,
                bootstrap=bootstrap,
                seed=seed,
                max_gap=0.5,
            )
        state["stage"] = "structural_comparisons"
        write_json(path=status_path, value=state)
        models = [
            m["sample_id"]
            for m in load_project(root=root)["models"]
            if m.get("coordinates")
        ]
        if comparison_mode == "reference" and reference not in models:
            raise WorkbenchError("The selected reference has no model coordinates")
        pairs = (
            list(itertools.combinations(models, 2))
            if comparison_mode == "all_pairs"
            else (
                [(reference, name) for name in models if name != reference]
                if comparison_mode == "reference"
                else []
            )
        )
        if comparison_mode != "none" and not pairs:
            raise WorkbenchError("Add at least two coordinate models for comparisons")
        failed = 0
        for engine in aligners if pairs else []:
            LOGGER.info(
                "Calculating %s pairs with %s (%s workers)", len(pairs), engine, workers
            )
            results = compare_batch(
                root=root,
                pairs=pairs,
                settings=replace(settings, engine=engine),
                usalign=usalign,
                tmalign=tmalign,
                workers=workers,
            )
            failed += sum(row["status"] == "failed" for row in results)
        state.update(
            stage="analyses_complete",
            failed_comparisons=failed,
            comparison_pairs=len(pairs),
            status="partial" if failed else "complete",
        )
        write_json(path=status_path, value=state)
        export_review(root=root, output=review_output)
        state.update(stage="finished", finished_utc=utc_now())
        write_json(path=status_path, value=state)
    except Exception as error:
        state.update(stage="failed", error=str(error), finished_utc=utc_now())
        write_json(path=status_path, value=state)
        raise
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
    return 2 if failed else 0
