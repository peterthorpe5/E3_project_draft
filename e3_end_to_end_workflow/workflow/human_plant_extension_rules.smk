"""Shared Snakemake rules for the human-and-plant structural extension."""

from pathlib import Path

from e3workflow.config import load_config
from e3workflow.io_utils import read_tsv


def _extension_value(name, default=None, required=False):
    """Return one validated extension setting from the active configuration."""

    value = HUMAN_PLANT_EXTENSION.get(name, default)
    if required and (value is None or str(value).strip() == ""):
        raise ValueError(f"human_plant_extension.{name} is required")
    return value


def _extension_path(name, default=None, required=False):
    """Resolve one extension path relative to its configuration file."""

    value = _extension_value(name, default=default, required=required)
    if value is None:
        return None
    path = Path(str(value)).expanduser()
    return (HUMAN_PLANT_CONFIG_BASE / path).resolve() if not path.is_absolute() else path.resolve()


HUMAN_PARENT_CONFIG = _extension_path(
    "parent_workflow_config",
    default=str(HUMAN_PLANT_DEFAULT_PARENT_CONFIG),
    required=True,
)
HUMAN_PARENT = load_config(HUMAN_PARENT_CONFIG)
HUMAN_OUTPUT_ROOT = _extension_path(
    "output_root",
    default=str(HUMAN_PARENT.run_root / "human_plant_structural_extension"),
    required=True,
)
HUMAN_REVIEW_LIMIT = int(_extension_value("review_limit", default=200))
HUMAN_SPECIES = str(_extension_value("human_species", default="Homo_sapiens"))
HUMAN_LIGANDABILITY_CONFIG = _extension_path(
    "ligandability_component_config",
    required=True,
)
HUMAN_LIGANDABILITY_ENV = str(
    _extension_value(
        "ligandability_conda_environment",
        default=HUMAN_PARENT.analysis.ligandability.conda_environment,
    )
)
HUMAN_STRUCTURAL_ENV = str(
    _extension_value(
        "structural_alignment_conda_environment",
        default=HUMAN_PARENT.analysis.structural_alignment.conda_environment,
    )
)
HUMAN_RESOURCES = dict(_extension_value("resources", default={}))


def _resource(name, default):
    """Return one positive integer resource request."""

    value = int(HUMAN_RESOURCES.get(name, default))
    if value < 1:
        raise ValueError(f"human_plant_extension.resources.{name} must be positive")
    return value


HUMAN_MANIFEST_ROOT = HUMAN_OUTPUT_ROOT / "manifests"
HUMAN_PREPARATION_MANIFEST = HUMAN_MANIFEST_ROOT / "preparation_manifest.json"
HUMAN_TASK_MANIFEST = HUMAN_MANIFEST_ROOT / "human_accession_tasks.tsv"
HUMAN_TASK_PARQUET = HUMAN_MANIFEST_ROOT / "human_accession_tasks.parquet"
HUMAN_MEMBER_MANIFEST = HUMAN_MANIFEST_ROOT / "human_group_members.tsv"
HUMAN_MEMBER_PARQUET = HUMAN_MANIFEST_ROOT / "human_group_members.parquet"
HUMAN_GROUP_MANIFEST = HUMAN_MANIFEST_ROOT / "groups.tsv"
HUMAN_GROUP_PARQUET = HUMAN_MANIFEST_ROOT / "groups.parquet"
HUMAN_REVIEW_SHORTLIST = HUMAN_MANIFEST_ROOT / "review_shortlist.parquet"
HUMAN_LIGANDABILITY_MANIFEST = (
    HUMAN_OUTPUT_ROOT / "ligandability" / "aggregate_manifest.json"
)
HUMAN_STRUCTURAL_MANIFEST = (
    HUMAN_OUTPUT_ROOT / "structural_alignment" / "aggregate_manifest.json"
)
HUMAN_PLANT_REVIEW_MANIFEST = (
    HUMAN_OUTPUT_ROOT / "pocket_review" / "provenance" / "run_manifest.json"
)
HUMAN_PLANT_PLANT_REVIEW_MANIFEST = (
    HUMAN_OUTPUT_ROOT
    / "plant_pocket_review"
    / "provenance"
    / "run_manifest.json"
)


checkpoint prepare_human_plant_extension:
    input:
        parent_config=str(HUMAN_PARENT_CONFIG),
        parent_complete=str(
            HUMAN_PARENT.run_root / "11_app_ready" / "stage_manifest.json"
        ),
        ligandability_config=str(HUMAN_LIGANDABILITY_CONFIG)
    output:
        preparation=str(HUMAN_PREPARATION_MANIFEST),
        task_tsv=str(HUMAN_TASK_MANIFEST),
        task_parquet=str(HUMAN_TASK_PARQUET),
        member_tsv=str(HUMAN_MEMBER_MANIFEST),
        member_parquet=str(HUMAN_MEMBER_PARQUET),
        group_tsv=str(HUMAN_GROUP_MANIFEST),
        group_parquet=str(HUMAN_GROUP_PARQUET),
        shortlist=str(HUMAN_REVIEW_SHORTLIST)
    threads:
        1
    resources:
        mem_mb=_resource("preparation_memory_mb", 8000),
        runtime=_resource("preparation_runtime_minutes", 30)
    log:
        str(HUMAN_OUTPUT_ROOT / "logs" / "prepare.snakemake.log")
    conda:
        "../environment.yml"
    shell:
        """
        set -o pipefail
        e3-workflow prepare-human-plant-extension \
            --parent-config {input.parent_config:q} \
            --output-root {HUMAN_OUTPUT_ROOT:q} \
            --review-limit {HUMAN_REVIEW_LIMIT} \
            --human-species {HUMAN_SPECIES:q} 2>&1 | tee {log:q}
        """


rule build_plant_baseline_review:
    input:
        parent_config=str(HUMAN_PARENT_CONFIG),
        parent_complete=str(
            HUMAN_PARENT.run_root / "11_app_ready" / "stage_manifest.json"
        )
    output:
        manifest=str(HUMAN_PLANT_PLANT_REVIEW_MANIFEST)
    params:
        output_root=str(HUMAN_OUTPUT_ROOT),
        conda_environment=HUMAN_STRUCTURAL_ENV,
        review_limit=HUMAN_REVIEW_LIMIT
    threads:
        _resource("review_threads", 2)
    resources:
        mem_mb=_resource("review_memory_mb", 12000),
        runtime=_resource("review_runtime_minutes", 120)
    log:
        str(HUMAN_OUTPUT_ROOT / "logs" / "plant_pocket_review.snakemake.log")
    conda:
        "../environment.yml"
    shell:
        """
        set -o pipefail
        e3-workflow build-plant-baseline-review \
            --parent-config {input.parent_config:q} \
            --output-root {params.output_root:q} \
            --conda-environment {params.conda_environment:q} \
            --review-limit {params.review_limit} 2>&1 | tee {log:q}
        """


def _human_ligandability_markers(wildcards):
    """Expand exact human-accession tasks after preparation."""

    completed = checkpoints.prepare_human_plant_extension.get()
    _fields, rows = read_tsv(Path(completed.output.task_tsv))
    task_ids = [f"{int(row['task_index']):04d}" for row in rows]
    return expand(
        str(
            HUMAN_OUTPUT_ROOT
            / "work_cache"
            / "human_ligandability"
            / "task_{task}"
            / "task_complete.tsv"
        ),
        task=task_ids,
    )


rule run_human_ligandability_extension_task:
    input:
        task_manifest=lambda wildcards: str(
            checkpoints.prepare_human_plant_extension.get().output.task_tsv
        ),
        component_config=str(HUMAN_LIGANDABILITY_CONFIG)
    output:
        marker=str(
            HUMAN_OUTPUT_ROOT
            / "work_cache"
            / "human_ligandability"
            / "task_{task}"
            / "task_complete.tsv"
        )
    params:
        task_index=lambda wildcards: int(wildcards.task),
        parent_config=str(HUMAN_PARENT_CONFIG),
        output_root=str(HUMAN_OUTPUT_ROOT),
        conda_environment=HUMAN_LIGANDABILITY_ENV
    threads:
        _resource("ligandability_threads", HUMAN_PARENT.analysis.ligandability.shard_threads)
    resources:
        mem_mb=_resource(
            "ligandability_memory_mb",
            HUMAN_PARENT.analysis.ligandability.shard_memory_mb,
        ),
        runtime=_resource(
            "ligandability_runtime_minutes",
            HUMAN_PARENT.analysis.ligandability.shard_runtime_minutes,
        )
    log:
        str(HUMAN_OUTPUT_ROOT / "logs" / "human_ligandability" / "{task}.log")
    conda:
        "../environment.yml"
    wildcard_constraints:
        task="[0-9]+"
    shell:
        """
        set -o pipefail
        e3-workflow run-human-ligandability-extension-task \
            --parent-config {params.parent_config:q} \
            --task-manifest {input.task_manifest:q} \
            --output-root {params.output_root:q} \
            --task-index {params.task_index} \
            --component-config {input.component_config:q} \
            --conda-environment {params.conda_environment:q} 2>&1 | tee {log:q}
        """


rule aggregate_human_ligandability_extension:
    input:
        preparation=lambda wildcards: str(
            checkpoints.prepare_human_plant_extension.get().output.preparation
        ),
        tasks=_human_ligandability_markers,
        task_manifest=lambda wildcards: str(
            checkpoints.prepare_human_plant_extension.get().output.task_tsv
        ),
        member_manifest=lambda wildcards: str(
            checkpoints.prepare_human_plant_extension.get().output.member_parquet
        ),
        group_manifest=lambda wildcards: str(
            checkpoints.prepare_human_plant_extension.get().output.group_tsv
        )
    output:
        manifest=str(HUMAN_LIGANDABILITY_MANIFEST)
    params:
        parent_config=str(HUMAN_PARENT_CONFIG),
        output_root=str(HUMAN_OUTPUT_ROOT)
    threads:
        _resource("ligandability_aggregate_threads", 4)
    resources:
        mem_mb=_resource("ligandability_aggregate_memory_mb", 16000),
        runtime=_resource("ligandability_aggregate_runtime_minutes", 120)
    log:
        str(HUMAN_OUTPUT_ROOT / "logs" / "human_ligandability.aggregate.log")
    conda:
        "../environment.yml"
    shell:
        """
        set -o pipefail
        e3-workflow aggregate-human-ligandability-extension \
            --parent-config {params.parent_config:q} \
            --task-manifest {input.task_manifest:q} \
            --group-member-manifest {input.member_manifest:q} \
            --group-manifest {input.group_manifest:q} \
            --output-root {params.output_root:q} 2>&1 | tee {log:q}
        """


def _human_structural_markers(wildcards):
    """Expand combined evolutionary-group tasks after preparation."""

    completed = checkpoints.prepare_human_plant_extension.get()
    _fields, rows = read_tsv(Path(completed.output.group_tsv))
    task_ids = [f"{int(row['group_task_index']):04d}" for row in rows]
    return expand(
        str(
            HUMAN_OUTPUT_ROOT
            / "work_cache"
            / "human_plant_structural"
            / "task_{group_task}"
            / "task_complete.tsv"
        ),
        group_task=task_ids,
    )


rule run_human_plant_structural_extension_task:
    input:
        group_manifest=lambda wildcards: str(
            checkpoints.prepare_human_plant_extension.get().output.group_tsv
        ),
        ligandability_manifest=str(HUMAN_LIGANDABILITY_MANIFEST)
    output:
        marker=str(
            HUMAN_OUTPUT_ROOT
            / "work_cache"
            / "human_plant_structural"
            / "task_{group_task}"
            / "task_complete.tsv"
        )
    params:
        task_index=lambda wildcards: int(wildcards.group_task),
        parent_config=str(HUMAN_PARENT_CONFIG),
        output_root=str(HUMAN_OUTPUT_ROOT),
        conda_environment=HUMAN_STRUCTURAL_ENV
    threads:
        _resource(
            "structural_threads",
            HUMAN_PARENT.analysis.structural_alignment.shard_threads,
        )
    resources:
        mem_mb=_resource(
            "structural_memory_mb",
            HUMAN_PARENT.analysis.structural_alignment.shard_memory_mb,
        ),
        runtime=_resource(
            "structural_runtime_minutes",
            HUMAN_PARENT.analysis.structural_alignment.shard_runtime_minutes,
        )
    log:
        str(HUMAN_OUTPUT_ROOT / "logs" / "human_plant_structural" / "{group_task}.log")
    conda:
        "../environment.yml"
    wildcard_constraints:
        group_task="[0-9]+"
    shell:
        """
        set -o pipefail
        e3-workflow run-human-plant-structural-extension-task \
            --parent-config {params.parent_config:q} \
            --group-manifest {input.group_manifest:q} \
            --ligandability-manifest {input.ligandability_manifest:q} \
            --output-root {params.output_root:q} \
            --task-index {params.task_index} \
            --conda-environment {params.conda_environment:q} 2>&1 | tee {log:q}
        """


rule aggregate_human_plant_structural_extension:
    input:
        groups=_human_structural_markers,
        group_manifest=lambda wildcards: str(
            checkpoints.prepare_human_plant_extension.get().output.group_tsv
        )
    output:
        manifest=str(HUMAN_STRUCTURAL_MANIFEST)
    params:
        output_root=str(HUMAN_OUTPUT_ROOT)
    threads:
        _resource("structural_aggregate_threads", 2)
    resources:
        mem_mb=_resource("structural_aggregate_memory_mb", 12000),
        runtime=_resource("structural_aggregate_runtime_minutes", 60)
    log:
        str(HUMAN_OUTPUT_ROOT / "logs" / "human_plant_structural.aggregate.log")
    conda:
        "../environment.yml"
    shell:
        """
        set -o pipefail
        e3-workflow aggregate-human-plant-structural-extension \
            --group-manifest {input.group_manifest:q} \
            --output-root {params.output_root:q} 2>&1 | tee {log:q}
        """


rule build_human_plant_review:
    input:
        structural_manifest=str(HUMAN_STRUCTURAL_MANIFEST),
        shortlist=lambda wildcards: str(
            checkpoints.prepare_human_plant_extension.get().output.shortlist
        ),
        supplementary_sequences=lambda wildcards: str(
            checkpoints.prepare_human_plant_extension.get().output.member_parquet
        )
    output:
        manifest=str(HUMAN_PLANT_REVIEW_MANIFEST)
    params:
        parent_config=str(HUMAN_PARENT_CONFIG),
        output_root=str(HUMAN_OUTPUT_ROOT),
        conda_environment=HUMAN_STRUCTURAL_ENV,
        review_limit=HUMAN_REVIEW_LIMIT
    threads:
        _resource("review_threads", 2)
    resources:
        mem_mb=_resource("review_memory_mb", 12000),
        runtime=_resource("review_runtime_minutes", 120)
    log:
        str(HUMAN_OUTPUT_ROOT / "logs" / "human_plant_review.log")
    conda:
        "../environment.yml"
    shell:
        """
        set -o pipefail
        e3-workflow build-human-plant-review \
            --parent-config {params.parent_config:q} \
            --output-root {params.output_root:q} \
            --conda-environment {params.conda_environment:q} \
            --review-limit {params.review_limit} 2>&1 | tee {log:q}
        """
