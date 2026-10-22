"""Generic workflow guidance and presentation helpers for protein-family research."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import shutil
from typing import Mapping

import pandas as pd

from .common import ResearchConfig, ResearchError

SECTIONS = (
    "Start here",
    "Discover",
    "Family analysis",
    "Alignments and trees",
    "Models",
    "Annotations",
    "Jobs",
    "Help & glossary",
)

OPERATION_NAMES = {
    "resolve": "Map sequence identifiers",
    "retrieve": "Retrieve global clusters",
    "import_cluster": "Import a cluster FASTA",
    "subcluster": "Create stricter subclusters",
    "align": "Align sequences and infer a tree",
    "search": "Search global representatives",
    "predict": "Predict protein structures",
    "annotate": "Predict protein annotations",
    "taxonomy_index": "Build species index",
}

# Aim, inputs/actions and outputs are shared by the page and downloadable help.
PAGE_GUIDES = {
    "Discover": (
        "Step 1 · Find and collect a protein family",
        "Find global DeepClust clusters containing your proteins, then retrieve their sequences.",
        "1. Choose your starting point: project groups, sequence identifiers, a known global "
        "centroid, or an exported cluster FASTA.\n"
        "2. If you start with identifiers, queue mapping and inspect its completed result. "
        "Mapping finds membership; it does not retrieve the sequences.\n"
        "3. Select mapped clusters and queue complete retrieval. "
        "Wait for COMPLETE in Jobs.\n\n"
        "**Output:** one unaligned protein FASTA per cluster, membership and length summaries. "
        "**Next:** open Family analysis and select a retrieved FASTA. Retrieval uses the "
        "configured database on the analysis server; it does not download the entire "
        "DeepClust database to your laptop.",
    ),
    "Family analysis": (
        "Step 2 · Compare the sequences in your family",
        "Split a broad family into more similar subclusters, or align an existing family directly.",
        "1. Choose a task and an unaligned protein FASTA from a completed job or an upload.\n"
        "2. For a broad family, start with Stricter subclusters. For a small family you can "
        "choose Alignment and tree immediately.\n"
        "3. To align one subcluster, select that completed subclustering job as your input "
        "and choose a subcluster from its audited membership.\n\n"
        "**Output:** audited subclusters, or a multiple sequence alignment and optional tree. "
        "**Next:** inspect a completed alignment in Alignments and trees. Subclustering and "
        "alignment are separate jobs; creating subclusters does not automatically align them.",
    ),
    "Alignments and trees": (
        "Step 3 · Inspect conservation and relationships",
        "Explore a completed multiple sequence alignment, its conservation statistics and tree.",
        "1. Select a completed alignment job. This page displays results; it does not run an "
        "alignment.\n"
        "2. Start with JBrowse MSA for the tree and alignment together. Use its search and "
        "zoom controls to locate sequences and residues.\n"
        "3. Try Alignment Viewer 2 for sorting by similarity to the reference, or Statistics "
        "for per-position and per-sequence evidence.\n\n"
        "**Output:** interactive views and downloadable standalone alignment HTML. Complete "
        "FASTA, Newick and TSV files are in Jobs. Tree branch lengths represent divergence, "
        "not elapsed time; alignments and trees do not demonstrate experimental function.",
    ),
    "Models": (
        "Optional · Predict and inspect protein structures",
        "Request ESMFold models for selected proteins and inspect the returned structure evidence.",
        "1. Select an unaligned protein FASTA, then paste exact sequence IDs to restrict the "
        "request. Start with one protein; a model job accepts at most 100 proteins.\n"
        "2. Choose a configured route. External routes require your explicit sequence "
        "submission selection. Atlas accepts proteins up to 400 amino acids in this app.\n"
        "3. Queue the job, then select its completed result below to inspect confidence and "
        "download PDB models.\n\n"
        "**Output:** PDB models, residue evidence and a per-protein success/failure table. "
        "An optional annotation overlay must describe exactly the same sequence. A failed "
        "provider request remains visible; a model is never substituted for a different sequence.",
    ),
    "Annotations": (
        "Optional · Predict domains and functional annotations",
        "Obtain computational evidence for proteins with missing or incomplete annotation.",
        "1. Select an unaligned protein FASTA and optionally restrict it to exact sequence IDs.\n"
        "2. Choose InterProScan for domains/signatures, or installed eggNOG-mapper for "
        "orthology-based annotation. Only eggNOG uses the taxonomic scope controls.\n"
        "3. For remote InterProScan, explicitly allow sequence submission. Queue the job, "
        "then inspect the completed annotation audit and feature tracks below.\n\n"
        "**Output:** annotations, per-input no-hit records and positional Nightingale tracks "
        "where domain coordinates exist. These are predictions, not experimentally validated "
        "functions. Eukaryota/2759 is the default eggNOG scope, not a prokaryote-only workflow.",
    ),
    "Jobs": (
        "Track progress and download results",
        "Follow submitted work, inspect its outcome and obtain the complete result files.",
        "1. Refresh the job list and choose a job by its task, timestamp and identifier.\n"
        "2. QUEUED means waiting for a worker; RUNNING means a worker has claimed it. A "
        "running job may be waiting for disk, a mounted file or an external service.\n"
        "3. COMPLETE means results were published; choose the next analysis or prepare a "
        "verified download. FAILED means inspect the error and diagnostics before retrying.\n\n"
        "Only queued jobs can be cancelled here. The browser submits jobs and a separate "
        "worker executes them using the same research profile/workspace. Closing the browser "
        "does not cancel queued or running work. The list shows the 200 most recent jobs.",
    ),
}

FIELD_HELP = {
    "navigation": "Start here explains the workflow. Jobs tracks progress from every page. "
    "Models and Annotations are optional; you can use them directly with a protein FASTA.",
    "discovery": "Project groups and protein accessions must first be mapped to global "
    "DeepClust membership. A known global centroid can be retrieved directly. Ranking "
    "browses the whole configured catalogue and may take time over a mounted database.",
    "protein_input": "Use an unaligned amino-acid FASTA. A completed retrieval, import, "
    "subclustering or alignment job can supply sequences without uploading them again.",
    "upload": "FASTA text, not a table or a DNA file. Each header starts with > and a unique "
    "ID before its first space. Paste that exact ID in later sequence-selection fields. "
    "Example: >protein_A followed on the next line by MAAKLVV. Maximum upload: 20 MB.",
    "source": "Choose the FASTA belonging to the family you want to analyse. The label shows "
    "the task, completion time, file and job ID. alignment.fasta is excluded because it "
    "contains an alignment; sequences.fasta is its unaligned input and may be a sample.",
    "sequence_ids": "Exact IDs from FASTA headers, one per line (spaces, commas or semicolons "
    "also separate entries). Do not include > or descriptions. Blank selects all input "
    "proteins. A local HOG ID is not a sequence ID.",
    "mapping_ids": "Paste protein accessions or exact source IDs, e.g. P12345 or "
    "NR_UGC79169.1. Configured UNIPROT_ and NR_ aliases are tested explicitly. Case, "
    "versions, unmatched IDs and multiple matches are preserved. No sequence similarity "
    "search or automatic representative selection is performed by this action.",
    "centroid": "A global DeepClust cluster is named by its centroid, e.g. NR_UGC79169.1. "
    "Paste the exact value from a mapping/ranking result, including its source prefix and "
    "accession version. A local project cluster ID or HOG number is a different identifier.",
    "minimum_size": "Published number of sequences in each global cluster. The official "
    "row-group index covers clusters with at least three members. This filter does not "
    "change or recluster the database.",
    "taxa": "Numeric NCBI taxon IDs, e.g. 3702 for Arabidopsis thaliana or 9606 for human. "
    "Filtering needs a configured reviewed cluster/species index. Taxonomy is never guessed "
    "from a sequence name. These are exact taxon IDs, not an automatic descendant search.",
    "all_taxa": "Unticked: a cluster may contain any selected taxon. Ticked: each cluster "
    "must contain every selected taxon. Uses reviewed metadata only.",
    "species": "Keep clusters with at least one reviewed species assignment in the "
    "configured cluster/species index. Unknown taxonomy is retained when this is unticked.",
    "preview": "Maximum rows displayed from the size-ranked query. This is not a sequence "
    "sample, and it does not retrieve any cluster sequences.",
    "project_groups": "Paste exact local group IDs from your project tables, one per line. "
    "This overrides the top-N setting. Use the full HOG ID, not just its ranking number. "
    "The adapter collects member/source accessions and linked seeds for exact mapping.",
    "project_top": "Prepare inputs for the top ranked project groups. Begin with one group "
    "to check the mapping before increasing this. Preparation does not contact DeepClust "
    "or run a representative/medoid calculation.",
    "identity": "Minimum percent identical residues in each audited member-to-centroid "
    "alignment. A higher threshold is stricter. The default 70% is a starting point, not "
    "a universal biological cut-off; it does not require every pair in a subcluster to match.",
    "coverage": "Minimum aligned coverage of BOTH the member and centroid. At 80%, at least "
    "80% of each must be covered; a short domain match alone may fail. Higher is stricter.",
    "evalue": "Largest accepted E-value in exact realignment. Smaller values are stricter. "
    "1e-10 means 10 to the power -10. Identity, mutual coverage and this threshold are "
    "applied together; failed assignments remain as singleton subclusters.",
    "subcluster": "Choose an audited subcluster from the selected subclustering job. "
    "Whole family selects its complete FASTA. A subcluster ID from a different job cannot "
    "be used with an unrelated FASTA.",
    "reference": "Exact ID of a sequence in the selected alignment input. It is retained "
    "during sampling and used for identity/overlap/BLOSUM statistics. Blank selects the "
    "first ID in sorted identifier order, not a computed centroid or medoid.",
    "sampling": "Opt in to a reproducible sequence sample when the complete family is too "
    "large. The reference is retained. Sampling changes the analysed set and is recorded "
    "in the selection audit; it is never enabled automatically.",
    "sample_size": "Maximum number of sequences to align when sampling is enabled. "
    "Use a small exploratory sample first for a large family. Limits also apply to total "
    "alignment matrix cells (sequences multiplied by aligned positions).",
    "tree": "Run FastTree with WAG+gamma after MAFFT. Requires at least three sequences. "
    "Branch lengths show inferred divergence; this is not a time-calibrated species tree.",
    "fold_engine": "Atlas submits to the ESM Atlas service. A Hugging Face route requires "
    "an operator-deployed inference endpoint. Local folding uses installed dependencies "
    "and model weights on the worker. Selecting a route does not run a prediction.",
    "consent": "The selected protein sequences will be sent to the named external provider "
    "only when you tick this and submit the job. Local routes do not send sequences away.",
    "annotation_engine": "InterProScan recognises protein signatures/domains. eggNOG-mapper "
    "transfers orthology-based annotations from its installed database. Local routes need "
    "their tool/database; remote InterProScan needs the configured contact email.",
    "scope": "eggNOG-mapper taxonomic scope. Eukaryota is suitable as a broad starting "
    "scope for eukaryotic proteins; choose a supported narrower scope when appropriate.",
    "target_taxon": "Positive NCBI target taxon ID passed to eggNOG-mapper. 2759 is Eukaryota. "
    "This affects annotation transfer and is separate from filtering DeepClust clusters.",
    "artifact": "An output file published by the selected job. FASTA contains sequences, "
    "TSV contains tables, PDB contains a predicted model, and Newick contains a tree. "
    "Prepare verified download checks the stored SHA-256 before offering the file.",
}

GLOSSARY = {
    "Local group / HOG": "A family/group in the source project. HOG means hierarchical "
    "orthogroup. Its local ID is not automatically a global DeepClust cluster ID.",
    "Sequence identifier": "The exact ID of one protein; in FASTA it is the first "
    "whitespace-delimited part of the header after >.",
    "Global cluster / centroid": "A published DeepClust family, named by its centroid "
    "sequence ID. An existing member can map you to that family.",
    "Representative / medoid": "A protein chosen to represent a family; a medoid is selected "
    "using distances. Exact identifier mapping does not calculate a medoid. The separate "
    "homology search compares all supplied query proteins against global centroids.",
    "Subcluster": "A local, stricter grouping inside your selected sequences. It is "
    "specific to the source job and thresholds, and does not change global DeepClust.",
    "Mutual coverage": "The aligned region must cover the required fraction of both "
    "the member sequence and its assigned centroid.",
    "Reference / query": "The selected protein used to compare alignment members. It "
    "can be chosen explicitly and is not necessarily a biological representative.",
    "Job / worker": "A job is a saved request; a separate worker executes it. Refresh "
    "Jobs to see its status and access the outputs.",
    "Artifact / manifest": "An artifact is an output file. The manifest records its "
    "checksum, parameters and provenance for reproducibility.",
    "No annotation hit": "No supported annotation was found under the chosen method "
    "and database. This does not prove a protein has no function.",
}


def job_label(*, job_id: str, record: Mapping[str, object], artifact: str = "") -> str:
    """Build a readable label while retaining an unambiguous job identifier.

    Args:
        job_id: Durable job identifier.
        record: Job summary or completed manifest.
        artifact: Optional source FASTA filename.

    Returns:
        Task, UTC timestamp, optional file and short job ID.
    """
    task = OPERATION_NAMES.get(str(record.get("operation", "")), "Research job")
    raw = record.get("completed_at") or record.get("created_at")
    try:
        moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        stamp = moment.astimezone(timezone.utc).strftime("%d %b %H:%M UTC")
    except ValueError:
        stamp = "time unavailable"
    parts = [task, stamp]
    if artifact:
        parts.append(artifact)
    parts.append(job_id[:12])
    return " · ".join(parts)


def retrievable_cluster_ids(*, frame: pd.DataFrame) -> list[str]:
    """Select indexed global IDs from a mapping or catalogue preview.

    Args:
        frame: Preview containing cluster_id and published member_count.

    Returns:
        Unique indexed IDs, excluding unmatched and unindexed mapping rows.
    """
    if not {"cluster_id", "member_count"}.issubset(frame.columns):
        return []
    valid = pd.to_numeric(frame["member_count"], errors="coerce").ge(1)
    return list(
        dict.fromkeys(
            value
            for value in frame.loc[valid, "cluster_id"]
            if isinstance(value, str) and value.strip()
        )
    )


def provider_problem(*, config: ResearchConfig, operation: str, engine: str) -> str:
    """Explain missing local setup without contacting a remote prediction service.

    Args:
        config: Trusted worker configuration.
        operation: predict or annotate.
        engine: Selected route identifier.

    Returns:
        Actionable setup message, or an empty string when basic setup is present.

    Raises:
        ResearchError: If an unknown operation or route is requested.
    """
    if operation == "predict":
        if engine == "atlas":
            return ""
        if engine == "huggingface_endpoint":
            return "" if config.esm_endpoint else "Ask the operator to configure esm_endpoint."
        if engine == "local":
            missing = [
                name for name in ("torch", "transformers") if importlib.util.find_spec(name) is None
            ]
            return (
                ("Install the optional folding dependencies on the worker: " + ", ".join(missing))
                if missing
                else ""
            )
    elif operation == "annotate":
        if engine == "interpro_remote":
            return "" if config.email else "Ask the operator to set the InterProScan contact email."
        if engine == "interpro_local":
            return (
                ""
                if shutil.which(config.interproscan)
                else (
                    "Local InterProScan is unavailable. Configure its executable and databases, "
                    "or select the remote route after setting its contact email."
                )
            )
        if engine == "eggnog":
            if not shutil.which(config.emapper):
                return "Install eggNOG-mapper on the worker and configure emapper."
            if not config.eggnog_data or not Path(config.eggnog_data).expanduser().is_dir():
                return "Configure the installed eggNOG database directory (eggnog_data)."
            return ""
    raise ResearchError("Unknown protein prediction route")


def user_guide(*, include_e3: bool) -> str:
    """Assemble portable help from the same guidance displayed in the workbench.

    Args:
        include_e3: Include the optional source-project adapter instructions.

    Returns:
        Markdown guide suitable for in-app display and a text download.
    """
    parts = [
        "# Protein research workbench user guide\n\n"
        "Aim: collect a relevant protein family, compare its sequences and interpret "
        "conservation, relationships and optional structure/annotation evidence.\n\n"
        "Start with one family. Find/collect → analyse → inspect results. "
        "Models and Annotations can also start directly from an unaligned protein FASTA."
    ]
    if include_e3:
        parts.append(
            "## Starting from E3\n\nOpen Discover → E3 ranked groups, choose one "
            "ranked group or paste its full local HOG ID, then Prepare E3 mapping "
            "inputs. Inspect the collected protein IDs, queue exact mapping, and "
            "use mapped global centroids for retrieval. Preparation does not choose "
            "a medoid. The E3 adapter is optional; other projects can use exact "
            "sequence IDs and FASTA uploads without an E3 resource."
        )
    for title, aim, instructions in PAGE_GUIDES.values():
        parts.append(f"## {title}\n\n{aim}\n\n{instructions}")
    parts.append(
        "## Glossary\n\n"
        + "\n\n".join(f"**{term}:** {meaning}" for term, meaning in GLOSSARY.items())
    )
    parts.append(
        "## Troubleshooting\n\n"
        "- **Queued for a long time:** a worker may be busy, stopped or using a "
        "different profile. Refresh Jobs; ask the operator to check the worker "
        "and workspace. Low CPU use alone does not establish that a job stopped.\n"
        "- **Unmatched ID:** check the exact accession/version and source prefix. "
        "Unmatched means no exact/declared-alias mapping, not no biological homologues.\n"
        "- **No indexed cluster:** some mapped clusters lack a published row-group "
        "index. Keep their mapping audit; do not assume they can be retrieved here.\n"
        "- **Missing tool or database:** an operator must configure that optional "
        "route. Opening this page does not install tools or download databases.\n"
        "- **Alignment too large:** select a smaller audited subcluster or explicitly "
        "enable sampling; the application does not silently truncate a family.\n"
        "- **Failed job:** read the error in Jobs, then expand technical details for "
        "the worker log and request. Correct the input/setup before submitting again."
    )
    return "\n\n".join(parts) + "\n"
