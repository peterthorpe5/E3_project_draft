"""Validated workflow configuration and stable stage ordering."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from e3workflow.errors import ConfigurationError

STAGE_NAMES = (
    "00_inputs",
    "01_prepared_proteomes",
    "02_discovery",
    "03_candidate_evidence",
    "04_orthofinder",
    "05_orthology",
    "06_domains",
    "07_expression",
    "08_shortlist_gate",
    "09_ligandability",
    "09b_structural_alignment",
    "09c_computational_chemistry",
    "10_integrated_resource",
    "11_app_ready",
)

EVIDENCE_MODES = frozenset(
    {
        "validate",
        "prepare",
        "reuse",
        "parent_reuse",
        "generate",
        "download",
        "derive",
        "synthetic",
        "disabled",
    }
)
CONFIG_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
INTERNAL_PRODUCTION_STAGES = frozenset(
    {
        "00_inputs",
        "01_prepared_proteomes",
        "02_discovery",
        "03_candidate_evidence",
        "04_orthofinder",
        "06_domains",
        "07_expression",
        "08_shortlist_gate",
        "09_ligandability",
        "09b_structural_alignment",
        "10_integrated_resource",
        "11_app_ready",
    }
)

STAGE_DEPENDENCIES = {
    "00_inputs": (),
    "01_prepared_proteomes": ("00_inputs",),
    "02_discovery": ("01_prepared_proteomes",),
    "03_candidate_evidence": ("02_discovery",),
    "04_orthofinder": ("01_prepared_proteomes",),
    "05_orthology": ("03_candidate_evidence", "04_orthofinder"),
    "06_domains": ("03_candidate_evidence", "05_orthology"),
    "07_expression": ("03_candidate_evidence", "05_orthology"),
    "08_shortlist_gate": (
        "03_candidate_evidence",
        "05_orthology",
        "06_domains",
        "07_expression",
    ),
    "09_ligandability": ("08_shortlist_gate",),
    "09b_structural_alignment": ("09_ligandability",),
    "09c_computational_chemistry": ("09_ligandability",),
    "10_integrated_resource": (
        "03_candidate_evidence",
        "05_orthology",
        "06_domains",
        "07_expression",
        "09_ligandability",
        "09b_structural_alignment",
        "09c_computational_chemistry",
    ),
    "11_app_ready": ("10_integrated_resource",),
}

STAGE_PURPOSES = {
    "00_inputs": (
        "Validate the controlled input manifests and their checksums.",
        "All later evidence must be traceable to an explicit, unchanged input set.",
    ),
    "01_prepared_proteomes": (
        "Prepare consistently named, validated proteomes for sequence analyses.",
        "Discovery and OrthoFinder must analyse the same complete species inputs.",
    ),
    "02_discovery": (
        "Provide E3-seeded sequence clusters, reusing or freshly building the authority.",
        "This expands the evidence set without claiming that every cluster member is an E3 ligase.",
    ),
    "03_candidate_evidence": (
        "Build the candidate-evidence resource from the validated Discovery Engine database.",
        "Downstream analyses need reconciled counts, identifiers and seed evidence per cluster.",
    ),
    "04_orthofinder": (
        "Provide a complete OrthoFinder analysis by reviewed reuse or a fresh isolated run.",
        (
            "Run-specific orthogroups provide evidence distinct from DeepClust sequence clusters; "
            "OrthoFinder 2.5.5 is retained because its project-reviewed phylogeny was preferred."
        ),
    ),
    "05_orthology": (
        "Reconcile candidate identifiers with the selected OrthoFinder outputs.",
        (
            "Orthogroup and predicted-orthologue evidence must be joined through validated "
            "identifiers."
        ),
    ),
    "06_domains": (
        "Collect protein-family and domain evidence for the candidate set.",
        "Domain architecture helps assess E3 plausibility independently of sequence clustering.",
    ),
    "07_expression": (
        "Build expression evidence for all selected group members in configured datasets.",
        (
            "Expression context is supporting evidence; reusable Atlas resources are acquired "
            "independently, then mapped to the selected run-specific orthology groups."
        ),
    ),
    "08_shortlist_gate": (
        "Build a transparent pre-structure ranking and a computational analysis shortlist.",
        (
            "Orthology, domain and expression evidence must be reconciled before structural "
            "evidence is assessed; the output remains a computational recommendation for review."
        ),
    ),
    "09_ligandability": (
        "Reuse or run structure and pocket analyses for computationally selected proteins.",
        "Ligandability evidence is meaningful only for the controlled shortlist.",
    ),
    "09b_structural_alignment": (
        (
            "Superpose shortlisted protein structures and compare selected pockets in three "
            "dimensions."
        ),
        (
            "Sequence-aligned pocket regions do not establish that predicted pockets occupy the "
            "same three-dimensional position."
        ),
    ),
    "09c_computational_chemistry": (
        (
            "Build open-source, residue-derived pharmacophore hypotheses for the "
            "highest-ranked evolutionarily stable candidate pockets."
        ),
        (
            "This optional stage provides a transparent computational-chemistry "
            "hand-off without requiring commercial or restricted software."
        ),
    ),
    "10_integrated_resource": (
        "Assemble validated evidence authorities into the release resource.",
        (
            "The application requires traceable joins across discovery, orthology, domains, "
            "expression and pockets."
        ),
    ),
    "11_app_ready": (
        "Publish the application hand-off and production-readiness statement.",
        "The viewer must open only a completed, validated integrated release.",
    ),
}

STAGE_INTERPRETATIONS = {
    "00_inputs": (
        "The configured manifests were readable and satisfied their declared validation rules.",
        (
            "Input validation establishes provenance and format; it does not assess biological "
            "quality."
        ),
    ),
    "01_prepared_proteomes": (
        (
            "The selected complete proteomes were prepared under a shared naming and validation "
            "contract."
        ),
        "Preparation does not establish completeness beyond the supplied source proteomes.",
    ),
    "02_discovery": (
        "Sequence clustering identifies candidates connected to known-E3 seed evidence.",
        "Cluster membership is similarity evidence and does not prove that every member is an E3.",
    ),
    "03_candidate_evidence": (
        "Validated cluster, representative and seed-accounting evidence is available for review.",
        "Candidate evidence prioritises sequences; it is not functional validation.",
    ),
    "04_orthofinder": (
        "A validated OrthoFinder 2.5.5 authority is available for the configured analysis.",
        (
            "Orthogroup membership alone does not prove a one-to-one orthologue relationship or "
            "function."
        ),
    ),
    "05_orthology": (
        "Candidate identifiers were reconciled with run-specific OrthoFinder evidence.",
        (
            "Predicted orthologue relationships remain computational evidence and require careful "
            "scope."
        ),
    ),
    "06_domains": (
        (
            "Protein-family and domain annotations provide independent support for candidate "
            "assessment."
        ),
        "A domain match does not by itself establish complete architecture or E3 activity.",
    ),
    "07_expression": (
        "Configured expression datasets provide biological-context evidence for the candidate set.",
        "Expression supports prioritisation but does not establish protein abundance or activity.",
    ),
    "08_shortlist_gate": (
        (
            "Candidates are ranked under a named, versioned scoring profile and selected for "
            "structural evidence interrogation."
        ),
        (
            "A computational shortlist is not human approval and does not establish E3 activity, "
            "ligandability or experimental suitability."
        ),
    ),
    "09_ligandability": (
        "Structure confidence and predicted-pocket evidence are available for approved proteins.",
        "AlphaFold confidence, FPocket and P2Rank predictions do not prove compound binding.",
    ),
    "09b_structural_alignment": (
        (
            "US-align and TM-align superpositions can test whether selected predicted pockets "
            "occupy a comparable three-dimensional region."
        ),
        (
            "Structural similarity and geometric pocket overlap remain computational predictions; "
            "they do not establish binding, selectivity or biochemical function."
        ),
    ),
    "09c_computational_chemistry": (
        (
            "Checksum-bound pocket structures support residue-derived pharmacophore "
            "hypotheses and optional open fragment compatibility ranking."
        ),
        (
            "The open method is not FMOPhore, FrAncestor, docking, binding-affinity "
            "prediction or experimental fragment screening."
        ),
    ),
    "10_integrated_resource": (
        "Validated evidence authorities have been joined into one traceable release resource.",
        (
            "Integrated evidence supports comparison and ranking, not a claim of experimental "
            "efficacy."
        ),
    ),
    "11_app_ready": (
        "The completed integrated release has an explicit application hand-off record.",
        "Application readiness describes data and interface checks, not biological validation.",
    ),
}


@dataclass(frozen=True)
class StageConfig:
    """Execution contract for one named stage."""

    name: str
    enabled: bool
    required: bool
    evidence_mode: str
    command: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    threads: int
    memory_mb: int
    runtime_minutes: int


@dataclass(frozen=True)
class ToolConfig:
    """One external tool's centrally controlled execution parameters.

    Attributes:
        name: Stable lower-case tool identifier.
        executable: Executable or repository-relative launcher used by stage commands.
        expected_version: Optional reviewed version string recorded in provenance.
        conda_environment: Optional Conda environment name used by command adapters.
        parameters: Ordered scalar parameter names and values exposed to command templates.
    """

    name: str
    executable: str
    expected_version: str | None
    conda_environment: str | None
    parameters: tuple[tuple[str, str | int | float | bool], ...]

    def parameter(self, name: str) -> str | int | float | bool:
        """Return one named parameter or fail with a configuration error."""
        for parameter_name, value in self.parameters:
            if parameter_name == name:
                return value
        raise ConfigurationError(f"Unknown parameter for tool {self.name}: {name}")

    def command_values(self) -> dict[str, str]:
        """Return documented command-template values for this tool."""
        prefix = f"tool_{self.name}_"
        values = {
            f"{prefix}executable": self.executable,
            f"{prefix}expected_version": self.expected_version or "",
            f"{prefix}conda_environment": self.conda_environment or "",
        }
        for parameter_name, value in self.parameters:
            values[f"{prefix}{parameter_name}"] = _render_scalar(value)
        return values

    def as_record(self) -> dict[str, Any]:
        """Return a JSON-serialisable provenance record."""
        return {
            "name": self.name,
            "executable": self.executable,
            "expected_version": self.expected_version,
            "conda_environment": self.conda_environment,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class BenchmarkConfig:
    """Validated resource-monitoring settings.

    Attributes:
        sample_interval_seconds: Delay between process-tree samples.
        collect_slurm_accounting: Whether the final aggregation should query ``sacct``.
    """

    sample_interval_seconds: float
    collect_slurm_accounting: bool


@dataclass(frozen=True)
class ReportingConfig:
    """Validated HTML-report settings.

    Attributes:
        preview_rows: Maximum result-table rows shown in a report.
        max_table_columns: Maximum columns shown in a result preview.
        max_chart_items: Maximum categories drawn in one embedded chart.
    """

    preview_rows: int
    max_table_columns: int
    max_chart_items: int


@dataclass(frozen=True)
class ResourceConfig:
    """Controlled reusable evidence resources for production integration."""

    candidate_evidence: Path | None
    candidate_evidence_manifest: Path | None
    orthofinder_archive: Path | None
    orthology_species_manifest: Path | None
    inherited_sqlite: Path | None
    expression_manifest: Path | None
    ligandability_manifest: Path | None
    domain_annotation_manifest: Path | None
    domain_cache_root: Path | None
    e3_domain_catalogue: Path | None


@dataclass(frozen=True)
class DomainAnalysisConfig:
    """Domain-analysis settings for downloaded annotations and optional gap filling."""

    mode: str
    interpro_api_base_url: str
    allow_network: bool
    workers: int
    request_timeout_seconds: float
    max_retries: int
    retry_delay_seconds: float


@dataclass(frozen=True)
class ExpressionAnalysisConfig:
    """Expression mapping and breadth thresholds."""

    minimum_expression_value: float
    broad_positive_fraction: float


@dataclass(frozen=True)
class LigandabilityAnalysisConfig:
    """Pocket selection and conserved-region analysis settings."""

    mode: str
    component_config: Path | None
    conda_environment: str
    shard_threads: int
    shard_memory_mb: int
    shard_runtime_minutes: int
    mafft_executable: str
    minimum_druggability_score: float
    minimum_mapping_fraction: float
    minimum_pocket_plddt_fraction: float
    minimum_region_overlap: float


@dataclass(frozen=True)
class StructuralAlignmentAnalysisConfig:
    """Three-dimensional structural-superposition and pocket-comparison settings."""

    conda_environment: str
    shard_threads: int
    shard_memory_mb: int
    shard_runtime_minutes: int
    member_pocket_top_k: int
    usalign_executable: str
    tmalign_executable: str
    distance_threshold_angstrom: float
    maximum_centroid_distance_angstrom: float
    minimum_pocket_overlap_fraction: float
    minimum_global_tm_score: float
    minimum_structural_residue_match_fraction: float
    minimum_structural_chemical_group_conservation: float
    minimum_group_support_fraction: float
    use_for_prioritisation: bool
    require_for_final_recommendation: bool
    prioritisation_weight: float


@dataclass(frozen=True)
class ComputationalChemistryAnalysisConfig:
    """Optional open-source structure-guided chemistry settings."""

    component_config: Path | None
    candidate_manifest: Path | None
    conda_environment: str


@dataclass(frozen=True)
class PrioritisationConfig:
    """Grant-aligned evidence integration and ranking configuration."""

    profile_name: str
    target_species: tuple[str, ...]
    mandatory_species: tuple[str, ...]
    minimum_target_species_fraction: float
    minimum_expression_species_fraction: float
    minimum_domain_species_fraction: float
    structure_group_limit: int
    final_candidate_limit: int
    discovery_weight: float
    orthology_weight: float
    domain_weight: float
    expression_weight: float
    ligandability_weight: float
    pocket_conservation_weight: float
    prestructure_final_weight: float
    structural_final_weight: float
    minimum_structural_species_fraction: float


@dataclass(frozen=True)
class AnalysisConfig:
    """Validated scientific settings for production evidence integration."""

    domains: DomainAnalysisConfig
    expression: ExpressionAnalysisConfig
    ligandability: LigandabilityAnalysisConfig
    structural_alignment: StructuralAlignmentAnalysisConfig
    computational_chemistry: ComputationalChemistryAnalysisConfig
    prioritisation: PrioritisationConfig


@dataclass(frozen=True)
class WorkflowConfig:
    """Fully resolved top-level workflow configuration."""

    schema_version: int
    source_path: Path
    path_base: Path
    project_root: Path
    output_root: Path
    run_name: str
    mode: str
    parent_run_root: Path | None
    proteomes_manifest: Path
    seeds_manifest: Path
    shortlist_manifest: Path
    benchmarking: BenchmarkConfig
    reporting: ReportingConfig
    resources: ResourceConfig
    analysis: AnalysisConfig
    tools: tuple[ToolConfig, ...]
    stages: tuple[StageConfig, ...]
    digest: str

    @property
    def run_root(self) -> Path:
        """Return the isolated root for this run."""
        return self.output_root / self.run_name

    def stage(self, name: str) -> StageConfig:
        """Return a configured stage by its stable name."""
        for stage in self.stages:
            if stage.name == name:
                return stage
        raise ConfigurationError(f"Unknown stage: {name}")

    def tool(self, name: str) -> ToolConfig:
        """Return a centrally configured external tool."""
        for tool in self.tools:
            if tool.name == name:
                return tool
        raise ConfigurationError(f"Unknown tool: {name}")

    def tool_command_values(self) -> dict[str, str]:
        """Return all tool settings exposed to external argv templates."""
        values: dict[str, str] = {}
        for tool in self.tools:
            values.update(tool.command_values())
        return values

    def tool_records(self) -> list[dict[str, Any]]:
        """Return all centrally configured tools as provenance records."""
        return [tool.as_record() for tool in self.tools]


def controlled_input_paths(config: WorkflowConfig) -> tuple[tuple[str, Path], ...]:
    """Return controlled inputs required by the enabled scientific branches.

    Proteomes and seed evidence are required only by fresh sequence-analysis branches. Reused
    candidate, OrthoFinder, domain, expression and ligandability authorities are added only when
    their corresponding internal branch consumes them. A real human-review file is retained when
    supplied, but the computational gate does not require a fabricated approval document.

    Args:
        config: Validated workflow configuration.

    Returns:
        Ordered ``(label, path)`` pairs for inputs that must exist for this configuration.
    """
    inputs: list[tuple[str, Path]] = []
    if config.mode == "synthetic":
        synthetic_inputs = [
            ("proteomes", config.proteomes_manifest),
            ("seeds", config.seeds_manifest),
            ("shortlist", config.shortlist_manifest),
        ]
        if config.stage("09c_computational_chemistry").enabled:
            _append_resource(
                synthetic_inputs,
                "computational_chemistry_component_config",
                config.analysis.computational_chemistry.component_config,
            )
            _append_resource(
                synthetic_inputs,
                "computational_chemistry_candidate_manifest",
                config.analysis.computational_chemistry.candidate_manifest,
            )
        return tuple(synthetic_inputs)
    if (
        config.stage("01_prepared_proteomes").enabled
        or config.stage("02_discovery").command
        or config.stage("04_orthofinder").command
    ):
        inputs.append(("proteomes", config.proteomes_manifest))
    if config.stage("02_discovery").enabled and config.stage("02_discovery").command:
        inputs.append(("seeds", config.seeds_manifest))
    if (
        config.stage("02_discovery").enabled
        and not config.stage("02_discovery").command
    ) or (
        config.stage("03_candidate_evidence").enabled
        and not config.stage("03_candidate_evidence").command
    ):
        _append_resource(inputs, "candidate_evidence", config.resources.candidate_evidence)
        _append_resource(
            inputs,
            "candidate_evidence_manifest",
            config.resources.candidate_evidence_manifest,
        )
    if config.stage("05_orthology").enabled:
        _append_resource(
            inputs,
            "orthology_species_manifest",
            config.resources.orthology_species_manifest,
        )
        _append_resource(inputs, "inherited_sqlite", config.resources.inherited_sqlite)
    if config.stage("04_orthofinder").enabled and not config.stage("04_orthofinder").command:
        _append_resource(
            inputs, "orthofinder_archive", config.resources.orthofinder_archive
        )
    if config.stage("06_domains").enabled and not config.stage("06_domains").command:
        _append_resource(inputs, "e3_domain_catalogue", config.resources.e3_domain_catalogue)
        if config.analysis.domains.mode == "downloaded_manifest":
            _append_resource(
                inputs,
                "domain_annotation_manifest",
                config.resources.domain_annotation_manifest,
            )
    if config.stage("07_expression").enabled and not config.stage("07_expression").command:
        _append_resource(inputs, "expression_manifest", config.resources.expression_manifest)
        _append_resource(inputs, "inherited_sqlite", config.resources.inherited_sqlite)
    if config.stage("09_ligandability").enabled:
        if config.analysis.ligandability.mode == "generate":
            _append_resource(
                inputs,
                "ligandability_component_config",
                config.analysis.ligandability.component_config,
            )
        elif not config.stage("09_ligandability").command:
            _append_resource(
                inputs,
                "ligandability_manifest",
                config.resources.ligandability_manifest,
            )
    if config.stage("09c_computational_chemistry").enabled:
        _append_resource(
            inputs,
            "computational_chemistry_component_config",
            config.analysis.computational_chemistry.component_config,
        )
        _append_resource(
            inputs,
            "computational_chemistry_candidate_manifest",
            config.analysis.computational_chemistry.candidate_manifest,
        )
    if config.stage("08_shortlist_gate").enabled and config.shortlist_manifest.is_file():
        inputs.append(("shortlist", config.shortlist_manifest))
    return tuple(dict(inputs).items())


def _append_resource(
    records: list[tuple[str, Path]], label: str, path: Path | None
) -> None:
    """Append a required configured resource or raise a precise error."""
    if path is None:
        raise ConfigurationError(f"inputs.{label} is required by the enabled production stages")
    records.append((label, path))


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    """Validate and return one mapping-like configuration section."""
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be a YAML mapping")
    return value


def _resolve_path(value: Any, base: Path, label: str) -> Path:
    """Resolve a required path relative to the configuration directory."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{label} must be a non-empty path string")
    path = Path(value).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def _optional_path(value: Any, base: Path, label: str) -> Path | None:
    """Resolve an optional configuration path."""
    if value is None or value == "":
        return None
    return _resolve_path(value, base, label)


def _number(
    value: Any,
    label: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """Validate a finite numeric setting within optional inclusive bounds."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigurationError(f"{label} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ConfigurationError(f"{label} must be finite")
    if minimum is not None and parsed < minimum:
        raise ConfigurationError(f"{label} must be at least {minimum}")
    if maximum is not None and parsed > maximum:
        raise ConfigurationError(f"{label} must be at most {maximum}")
    return parsed


def _positive_integer(value: Any, label: str) -> int:
    """Validate one positive integer setting."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigurationError(f"{label} must be a positive integer")
    return value


def _non_empty_string(value: Any, label: str) -> str:
    """Validate one non-empty string setting."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{label} must be a non-empty string")
    return value.strip()


def _render_scalar(value: str | int | float | bool) -> str:
    """Render a validated scalar consistently for an argv placeholder."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _optional_string(value: Any, label: str) -> str | None:
    """Validate an optional non-empty string."""
    if value is None or value == "":
        return None
    return _non_empty_string(value, label)


def _config_key(value: Any, label: str) -> str:
    """Validate a stable lower-case YAML key used in command placeholders."""
    if not isinstance(value, str) or CONFIG_KEY.fullmatch(value) is None:
        raise ConfigurationError(
            f"{label} must match {CONFIG_KEY.pattern}; use lower-case letters, numbers "
            "and underscores"
        )
    return value


def _tool_scalar(value: Any, label: str) -> str | int | float | bool:
    """Validate a tool parameter that can be represented by one argv token."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and any(character in value for character in "\t\r\n"):
        raise ConfigurationError(f"{label} must not contain tabs or line breaks")
    if isinstance(value, float) and not math.isfinite(value):
        raise ConfigurationError(f"{label} must be finite")
    if isinstance(value, (str, int, float)) and not (
        isinstance(value, str) and not value.strip()
    ):
        return value
    raise ConfigurationError(
        f"{label} must be one non-empty string, integer, number or boolean"
    )


def _tool_configs(root: Mapping[str, Any]) -> tuple[ToolConfig, ...]:
    """Build the central registry of external tool executables and parameters."""
    raw_tools = _mapping(root.get("tools", {}), "tools")
    configured: list[ToolConfig] = []
    for raw_name in sorted(raw_tools):
        name = _config_key(raw_name, "tools key")
        item = _mapping(raw_tools[raw_name], f"tools.{name}")
        executable = _non_empty_string(
            item.get("executable", name),
            f"tools.{name}.executable",
        )
        expected_version = _optional_string(
            item.get("expected_version"),
            f"tools.{name}.expected_version",
        )
        conda_environment = _optional_string(
            item.get("conda_environment"),
            f"tools.{name}.conda_environment",
        )
        raw_parameters = _mapping(
            item.get("parameters", {}),
            f"tools.{name}.parameters",
        )
        parameters = []
        for raw_parameter_name in sorted(raw_parameters):
            parameter_name = _config_key(
                raw_parameter_name,
                f"tools.{name}.parameters key",
            )
            parameters.append(
                (
                    parameter_name,
                    _tool_scalar(
                        raw_parameters[raw_parameter_name],
                        f"tools.{name}.parameters.{parameter_name}",
                    ),
                )
            )
        unknown_fields = set(item).difference(
            {"executable", "expected_version", "conda_environment", "parameters"}
        )
        if unknown_fields:
            raise ConfigurationError(
                f"Unknown settings for tools.{name}: {', '.join(sorted(unknown_fields))}"
            )
        configured.append(
            ToolConfig(
                name=name,
                executable=executable,
                expected_version=expected_version,
                conda_environment=conda_environment,
                parameters=tuple(parameters),
            )
        )
    return tuple(configured)


def _analysis_config(root: Mapping[str, Any], base: Path) -> AnalysisConfig:
    """Build validated domain, expression, pocket and prioritisation settings."""
    analysis = _mapping(root.get("analysis", {}), "analysis")
    domains = _mapping(analysis.get("domains", {}), "analysis.domains")
    expression = _mapping(analysis.get("expression", {}), "analysis.expression")
    ligandability = _mapping(
        analysis.get("ligandability", {}), "analysis.ligandability"
    )
    structural_alignment = _mapping(
        analysis.get("structural_alignment", {}),
        "analysis.structural_alignment",
    )
    computational_chemistry = _mapping(
        analysis.get("computational_chemistry", {}),
        "analysis.computational_chemistry",
    )
    prioritisation = _mapping(
        analysis.get("prioritisation", {}), "analysis.prioritisation"
    )
    target_species = _strings(
        prioritisation.get("target_species", []),
        "analysis.prioritisation.target_species",
    )
    mandatory_species = _strings(
        prioritisation.get("mandatory_species", []),
        "analysis.prioritisation.mandatory_species",
    )
    if not target_species:
        target_species = (
            "Arabidopsis_thaliana",
            "Brachypodium_distachyon",
            "Glycine_max",
            "Hordeum_vulgare",
            "Medicago_truncatula",
            "Oryza_sativa",
            "Populus_trichocarpa",
            "Solanum_lycopersicum",
            "Solanum_tuberosum",
            "Sorghum_bicolor",
            "Triticum_aestivum",
            "Zea_mays",
        )
    if not mandatory_species:
        mandatory_species = (
            "Hordeum_vulgare",
            "Oryza_sativa",
            "Solanum_lycopersicum",
            "Solanum_tuberosum",
            "Triticum_aestivum",
            "Zea_mays",
        )
    missing_mandatory = sorted(set(mandatory_species).difference(target_species))
    if missing_mandatory:
        raise ConfigurationError(
            "mandatory_species must be a subset of target_species: "
            + ", ".join(missing_mandatory)
        )
    mode = _non_empty_string(
        ligandability.get("mode", "reuse_only"), "analysis.ligandability.mode"
    )
    if mode not in {"reuse_only", "reuse_then_run_missing", "generate"}:
        raise ConfigurationError(
            "analysis.ligandability.mode must be reuse_only, "
            "reuse_then_run_missing or generate"
        )
    domain_mode = _non_empty_string(
        domains.get("mode", "interpro_api_cache"), "analysis.domains.mode"
    )
    if domain_mode not in {"interpro_api_cache", "downloaded_manifest"}:
        raise ConfigurationError(
            "analysis.domains.mode must be interpro_api_cache or downloaded_manifest"
        )
    allow_network = domains.get("allow_network", True)
    if not isinstance(allow_network, bool):
        raise ConfigurationError("analysis.domains.allow_network must be a boolean")
    use_for_prioritisation = structural_alignment.get("use_for_prioritisation", False)
    if not isinstance(use_for_prioritisation, bool):
        raise ConfigurationError(
            "analysis.structural_alignment.use_for_prioritisation must be a boolean"
        )
    require_for_final_recommendation = structural_alignment.get(
        "require_for_final_recommendation",
        False,
    )
    if not isinstance(require_for_final_recommendation, bool):
        raise ConfigurationError(
            "analysis.structural_alignment.require_for_final_recommendation "
            "must be a boolean"
        )
    max_retries = domains.get("max_retries", 4)
    if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
        raise ConfigurationError("analysis.domains.max_retries must be a non-negative integer")
    discovery_weight = _number(
        prioritisation.get("discovery_weight", 0.10),
        "analysis.prioritisation.discovery_weight",
        minimum=0.0,
    )
    orthology_weight = _number(
        prioritisation.get("orthology_weight", 0.35),
        "analysis.prioritisation.orthology_weight",
        minimum=0.0,
    )
    domain_weight = _number(
        prioritisation.get("domain_weight", 0.20),
        "analysis.prioritisation.domain_weight",
        minimum=0.0,
    )
    expression_weight = _number(
        prioritisation.get("expression_weight", 0.35),
        "analysis.prioritisation.expression_weight",
        minimum=0.0,
    )
    if abs(
        discovery_weight + orthology_weight + domain_weight + expression_weight - 1.0
    ) > 1e-9:
        raise ConfigurationError("pre-structure prioritisation weights must sum to 1.0")
    ligandability_weight = _number(
        prioritisation.get("ligandability_weight", 0.55),
        "analysis.prioritisation.ligandability_weight",
        minimum=0.0,
    )
    pocket_conservation_weight = _number(
        prioritisation.get("pocket_conservation_weight", 0.45),
        "analysis.prioritisation.pocket_conservation_weight",
        minimum=0.0,
    )
    if abs(ligandability_weight + pocket_conservation_weight - 1.0) > 1e-9:
        raise ConfigurationError("structural prioritisation weights must sum to 1.0")
    prestructure_final_weight = _number(
        prioritisation.get("prestructure_final_weight", 0.60),
        "analysis.prioritisation.prestructure_final_weight",
        minimum=0.0,
    )
    structural_final_weight = _number(
        prioritisation.get("structural_final_weight", 0.40),
        "analysis.prioritisation.structural_final_weight",
        minimum=0.0,
    )
    if abs(prestructure_final_weight + structural_final_weight - 1.0) > 1e-9:
        raise ConfigurationError("final prioritisation weights must sum to 1.0")
    return AnalysisConfig(
        domains=DomainAnalysisConfig(
            mode=domain_mode,
            interpro_api_base_url=_non_empty_string(
                domains.get("interpro_api_base_url", "https://www.ebi.ac.uk/interpro/api"),
                "analysis.domains.interpro_api_base_url",
            ).rstrip("/"),
            allow_network=allow_network,
            workers=_positive_integer(
                domains.get("workers", 4), "analysis.domains.workers"
            ),
            request_timeout_seconds=_number(
                domains.get("request_timeout_seconds", 60.0),
                "analysis.domains.request_timeout_seconds",
                minimum=1.0,
            ),
            max_retries=max_retries,
            retry_delay_seconds=_number(
                domains.get("retry_delay_seconds", 2.0),
                "analysis.domains.retry_delay_seconds",
                minimum=0.0,
            ),
        ),
        expression=ExpressionAnalysisConfig(
            minimum_expression_value=_number(
                expression.get("minimum_expression_value", 0.5),
                "analysis.expression.minimum_expression_value",
                minimum=0.0,
            ),
            broad_positive_fraction=_number(
                expression.get("broad_positive_fraction", 0.5),
                "analysis.expression.broad_positive_fraction",
                minimum=0.0,
                maximum=1.0,
            ),
        ),
        ligandability=LigandabilityAnalysisConfig(
            mode=mode,
            component_config=_optional_path(
                ligandability.get("component_config"),
                base,
                "analysis.ligandability.component_config",
            ),
            conda_environment=_non_empty_string(
                ligandability.get("conda_environment", "e3_ligandability"),
                "analysis.ligandability.conda_environment",
            ),
            shard_threads=_positive_integer(
                ligandability.get("shard_threads", 4),
                "analysis.ligandability.shard_threads",
            ),
            shard_memory_mb=_positive_integer(
                ligandability.get("shard_memory_mb", 16_000),
                "analysis.ligandability.shard_memory_mb",
            ),
            shard_runtime_minutes=_positive_integer(
                ligandability.get("shard_runtime_minutes", 720),
                "analysis.ligandability.shard_runtime_minutes",
            ),
            mafft_executable=_non_empty_string(
                ligandability.get("mafft_executable", "mafft"),
                "analysis.ligandability.mafft_executable",
            ),
            minimum_druggability_score=_number(
                ligandability.get("minimum_druggability_score", 0.5),
                "analysis.ligandability.minimum_druggability_score",
                minimum=0.0,
            ),
            minimum_mapping_fraction=_number(
                ligandability.get("minimum_mapping_fraction", 0.95),
                "analysis.ligandability.minimum_mapping_fraction",
                minimum=0.0,
                maximum=1.0,
            ),
            minimum_pocket_plddt_fraction=_number(
                ligandability.get("minimum_pocket_plddt_fraction", 0.7),
                "analysis.ligandability.minimum_pocket_plddt_fraction",
                minimum=0.0,
                maximum=1.0,
            ),
            minimum_region_overlap=_number(
                ligandability.get("minimum_region_overlap", 0.25),
                "analysis.ligandability.minimum_region_overlap",
                minimum=0.0,
                maximum=1.0,
            ),
        ),
        structural_alignment=StructuralAlignmentAnalysisConfig(
            conda_environment=_non_empty_string(
                structural_alignment.get(
                    "conda_environment",
                    "e3_structural_alignment",
                ),
                "analysis.structural_alignment.conda_environment",
            ),
            shard_threads=_positive_integer(
                structural_alignment.get("shard_threads", 4),
                "analysis.structural_alignment.shard_threads",
            ),
            shard_memory_mb=_positive_integer(
                structural_alignment.get("shard_memory_mb", 8_000),
                "analysis.structural_alignment.shard_memory_mb",
            ),
            shard_runtime_minutes=_positive_integer(
                structural_alignment.get("shard_runtime_minutes", 240),
                "analysis.structural_alignment.shard_runtime_minutes",
            ),
            member_pocket_top_k=_positive_integer(
                structural_alignment.get("member_pocket_top_k", 1),
                "analysis.structural_alignment.member_pocket_top_k",
            ),
            usalign_executable=_non_empty_string(
                structural_alignment.get("usalign_executable", "USalign"),
                "analysis.structural_alignment.usalign_executable",
            ),
            tmalign_executable=_non_empty_string(
                structural_alignment.get("tmalign_executable", "TMalign"),
                "analysis.structural_alignment.tmalign_executable",
            ),
            distance_threshold_angstrom=_number(
                structural_alignment.get("distance_threshold_angstrom", 4.0),
                "analysis.structural_alignment.distance_threshold_angstrom",
                minimum=0.1,
            ),
            maximum_centroid_distance_angstrom=_number(
                structural_alignment.get(
                    "maximum_centroid_distance_angstrom",
                    8.0,
                ),
                "analysis.structural_alignment.maximum_centroid_distance_angstrom",
                minimum=0.1,
            ),
            minimum_pocket_overlap_fraction=_number(
                structural_alignment.get("minimum_pocket_overlap_fraction", 0.5),
                "analysis.structural_alignment.minimum_pocket_overlap_fraction",
                minimum=0.0,
                maximum=1.0,
            ),
            minimum_global_tm_score=_number(
                structural_alignment.get("minimum_global_tm_score", 0.5),
                "analysis.structural_alignment.minimum_global_tm_score",
                minimum=0.0,
                maximum=1.0,
            ),
            minimum_structural_residue_match_fraction=_number(
                structural_alignment.get(
                    "minimum_structural_residue_match_fraction", 0.5
                ),
                (
                    "analysis.structural_alignment."
                    "minimum_structural_residue_match_fraction"
                ),
                minimum=0.0,
                maximum=1.0,
            ),
            minimum_structural_chemical_group_conservation=_number(
                structural_alignment.get(
                    "minimum_structural_chemical_group_conservation", 0.6
                ),
                (
                    "analysis.structural_alignment."
                    "minimum_structural_chemical_group_conservation"
                ),
                minimum=0.0,
                maximum=1.0,
            ),
            minimum_group_support_fraction=_number(
                structural_alignment.get("minimum_group_support_fraction", 0.75),
                "analysis.structural_alignment.minimum_group_support_fraction",
                minimum=0.0,
                maximum=1.0,
            ),
            use_for_prioritisation=use_for_prioritisation,
            require_for_final_recommendation=require_for_final_recommendation,
            prioritisation_weight=_number(
                structural_alignment.get("prioritisation_weight", 0.25),
                "analysis.structural_alignment.prioritisation_weight",
                minimum=0.0,
                maximum=1.0,
            ),
        ),
        computational_chemistry=ComputationalChemistryAnalysisConfig(
            component_config=_optional_path(
                computational_chemistry.get("component_config"),
                base,
                "analysis.computational_chemistry.component_config",
            ),
            candidate_manifest=_optional_path(
                computational_chemistry.get("candidate_manifest"),
                base,
                "analysis.computational_chemistry.candidate_manifest",
            ),
            conda_environment=_non_empty_string(
                computational_chemistry.get(
                    "conda_environment",
                    "e3_structure_guided_chemistry",
                ),
                "analysis.computational_chemistry.conda_environment",
            ),
        ),
        prioritisation=PrioritisationConfig(
            profile_name=_non_empty_string(
                prioritisation.get("profile_name", "grant_aligned_stringent_v1"),
                "analysis.prioritisation.profile_name",
            ),
            target_species=target_species,
            mandatory_species=mandatory_species,
            minimum_target_species_fraction=_number(
                prioritisation.get("minimum_target_species_fraction", 0.9),
                "analysis.prioritisation.minimum_target_species_fraction",
                minimum=0.0,
                maximum=1.0,
            ),
            minimum_expression_species_fraction=_number(
                prioritisation.get("minimum_expression_species_fraction", 0.8),
                "analysis.prioritisation.minimum_expression_species_fraction",
                minimum=0.0,
                maximum=1.0,
            ),
            minimum_domain_species_fraction=_number(
                prioritisation.get("minimum_domain_species_fraction", 0.8),
                "analysis.prioritisation.minimum_domain_species_fraction",
                minimum=0.0,
                maximum=1.0,
            ),
            structure_group_limit=_positive_integer(
                prioritisation.get("structure_group_limit", 50),
                "analysis.prioritisation.structure_group_limit",
            ),
            final_candidate_limit=_positive_integer(
                prioritisation.get("final_candidate_limit", 10),
                "analysis.prioritisation.final_candidate_limit",
            ),
            discovery_weight=discovery_weight,
            orthology_weight=orthology_weight,
            domain_weight=domain_weight,
            expression_weight=expression_weight,
            ligandability_weight=ligandability_weight,
            pocket_conservation_weight=pocket_conservation_weight,
            prestructure_final_weight=prestructure_final_weight,
            structural_final_weight=structural_final_weight,
            minimum_structural_species_fraction=_number(
                prioritisation.get("minimum_structural_species_fraction", 0.75),
                "analysis.prioritisation.minimum_structural_species_fraction",
                minimum=0.0,
                maximum=1.0,
            ),
        ),
    )


def _strings(value: Any, label: str) -> tuple[str, ...]:
    """Validate a YAML sequence containing only non-empty strings."""
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ConfigurationError(f"{label} must be a list of non-empty strings")
    return tuple(value)


def _default_evidence_mode(
    *, name: str, enabled: bool, command: tuple[str, ...], run_mode: str
) -> str:
    """Return the explicit provenance strategy implied by a stage configuration."""
    if not enabled:
        return "disabled"
    if run_mode == "synthetic":
        return "synthetic"
    if name == "00_inputs":
        return "validate"
    if name == "01_prepared_proteomes":
        return "prepare"
    if name in {"02_discovery", "03_candidate_evidence", "04_orthofinder", "09_ligandability"}:
        return "generate" if command else "reuse"
    if name == "06_domains":
        return "download" if not command else "generate"
    if name == "07_expression":
        return "reuse" if not command else "generate"
    return "derive"


def load_config(path: Path) -> WorkflowConfig:
    """Load, validate, and resolve one workflow YAML file.

    Args:
        path: YAML configuration path.

    Returns:
        Immutable resolved configuration.
    """
    source = path.expanduser().resolve()
    if not source.is_file():
        raise ConfigurationError(f"Configuration file does not exist: {source}")
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Could not read configuration {source}: {exc}") from exc
    root = _mapping(raw, "configuration")
    schema_version = root.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version not in {1, 2}
    ):
        raise ConfigurationError("schema_version must be the integer 1 or 2")
    run = _mapping(root.get("run"), "run")
    inputs = _mapping(root.get("inputs"), "inputs")
    mode = run.get("mode")
    if mode not in {"synthetic", "production"}:
        raise ConfigurationError("run.mode must be 'synthetic' or 'production'")
    run_name = run.get("name")
    if not isinstance(run_name, str) or not run_name or "/" in run_name or run_name in {".", ".."}:
        raise ConfigurationError("run.name must be a safe, non-empty directory name")
    configured_path_base = root.get("path_base")
    path_base = (
        _resolve_path(configured_path_base, source.parent, "path_base")
        if configured_path_base is not None
        else source.parent
    )
    base = path_base
    project_root = _resolve_path(run.get("project_root"), base, "run.project_root")
    output_root = _resolve_path(run.get("output_root"), base, "run.output_root")
    parent_run_root = _optional_path(
        run.get("parent_run_root"),
        base,
        "run.parent_run_root",
    )
    raw_stages = _mapping(root.get("stages"), "stages")
    raw_benchmarking = _mapping(root.get("benchmarking", {}), "benchmarking")
    raw_reporting = _mapping(root.get("reporting", {}), "reporting")
    analysis_config = _analysis_config(root, base)
    tool_configs = _tool_configs(root)
    sample_interval = raw_benchmarking.get("sample_interval_seconds", 5.0)
    collect_slurm = raw_benchmarking.get("collect_slurm_accounting", True)
    if (
        not isinstance(sample_interval, (int, float))
        or isinstance(sample_interval, bool)
        or sample_interval <= 0
    ):
        raise ConfigurationError(
            "benchmarking.sample_interval_seconds must be a positive number"
        )
    if not isinstance(collect_slurm, bool):
        raise ConfigurationError("benchmarking.collect_slurm_accounting must be a boolean")
    reporting_values = {
        "preview_rows": raw_reporting.get("preview_rows", 10),
        "max_table_columns": raw_reporting.get("max_table_columns", 12),
        "max_chart_items": raw_reporting.get("max_chart_items", 20),
    }
    for label, value in reporting_values.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ConfigurationError(f"reporting.{label} must be a positive integer")
    unknown = set(raw_stages).difference(STAGE_NAMES)
    if unknown:
        raise ConfigurationError(f"Unknown stage configuration: {', '.join(sorted(unknown))}")
    stages = []
    for name in STAGE_NAMES:
        item = _mapping(raw_stages.get(name, {}), f"stages.{name}")
        optional_by_default = name in {
            "09b_structural_alignment",
            "09c_computational_chemistry",
        }
        enabled = item.get("enabled", not optional_by_default)
        required = item.get("required", not optional_by_default)
        if not isinstance(enabled, bool) or not isinstance(required, bool):
            raise ConfigurationError(f"enabled and required must be booleans for {name}")
        command = _strings(item.get("command"), f"stages.{name}.command")
        evidence_mode = item.get(
            "evidence_mode",
            _default_evidence_mode(
                name=name,
                enabled=enabled,
                command=command,
                run_mode=mode,
            ),
        )
        if evidence_mode not in EVIDENCE_MODES:
            raise ConfigurationError(
                f"stages.{name}.evidence_mode must be one of: "
                + ", ".join(sorted(EVIDENCE_MODES))
            )
        if enabled and evidence_mode == "disabled":
            raise ConfigurationError(
                f"Enabled stage cannot use disabled evidence_mode: {name}"
            )
        if not enabled and evidence_mode != "disabled":
            raise ConfigurationError(
                f"Disabled stage must use disabled evidence_mode: {name}"
            )
        if mode == "production" and evidence_mode == "generate" and not command and name not in {
            "01_prepared_proteomes",
            "06_domains",
            "09_ligandability",
            "09b_structural_alignment",
        }:
            raise ConfigurationError(
                f"Fresh generation requires an argv command for production stage: {name}"
            )
        expected = _strings(item.get("expected_outputs"), f"stages.{name}.expected_outputs")
        threads = item.get("threads", 1)
        memory_mb = item.get("memory_mb", 8_000)
        runtime_minutes = item.get("runtime_minutes", 60)
        if required and not enabled:
            raise ConfigurationError(f"Required stage cannot be disabled: {name}")
        for value, label in (
            (threads, "threads"),
            (memory_mb, "memory_mb"),
            (runtime_minutes, "runtime_minutes"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ConfigurationError(f"stages.{name}.{label} must be a positive integer")
        missing_production_command = (
            mode == "production"
            and enabled
            and not command
            and name not in INTERNAL_PRODUCTION_STAGES
            and evidence_mode != "parent_reuse"
        )
        if missing_production_command:
            raise ConfigurationError(f"Production stage requires an argv command: {name}")
        for relative in expected:
            candidate = Path(relative)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ConfigurationError(f"Unsafe expected output for {name}: {relative}")
        stages.append(
            StageConfig(
                name,
                enabled,
                required,
                evidence_mode,
                command,
                expected,
                threads,
                memory_mb,
                runtime_minutes,
            )
        )
    parent_reuse_stages = [
        stage.name for stage in stages if stage.evidence_mode == "parent_reuse"
    ]
    if parent_reuse_stages and parent_run_root is None:
        raise ConfigurationError(
            "run.parent_run_root is required when a stage uses parent_reuse"
        )
    unsupported_parent_reuse = [
        name
        for name in parent_reuse_stages
        if STAGE_NAMES.index(name) > STAGE_NAMES.index("08_shortlist_gate")
    ]
    if unsupported_parent_reuse:
        raise ConfigurationError(
            "parent_reuse is supported only through 08_shortlist_gate: "
            + ", ".join(unsupported_parent_reuse)
        )
    structural_stage = next(
        stage for stage in stages if stage.name == "09b_structural_alignment"
    )
    if analysis_config.structural_alignment.use_for_prioritisation and not structural_stage.enabled:
        raise ConfigurationError(
            "analysis.structural_alignment.use_for_prioritisation requires the "
            "09b_structural_alignment stage to be enabled"
        )
    if (
        analysis_config.structural_alignment.require_for_final_recommendation
        and not structural_stage.enabled
    ):
        raise ConfigurationError(
            "analysis.structural_alignment.require_for_final_recommendation "
            "requires the 09b_structural_alignment stage to be enabled"
        )
    chemistry_stage = next(
        stage for stage in stages if stage.name == "09c_computational_chemistry"
    )
    if (
        chemistry_stage.enabled
        and analysis_config.computational_chemistry.component_config is None
    ):
        raise ConfigurationError(
            "Enabled stage 09c_computational_chemistry requires "
            "analysis.computational_chemistry.component_config"
        )
    if (
        chemistry_stage.enabled
        and analysis_config.computational_chemistry.candidate_manifest is None
    ):
        raise ConfigurationError(
            "Enabled stage 09c_computational_chemistry requires "
            "analysis.computational_chemistry.candidate_manifest"
        )
    canonical = json.dumps(root, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    default_shortlist = inputs.get("shortlist_manifest", "synthetic_shortlist.tsv")
    return WorkflowConfig(
        schema_version=schema_version,
        source_path=source,
        path_base=path_base,
        project_root=project_root,
        output_root=output_root,
        run_name=run_name,
        mode=mode,
        parent_run_root=parent_run_root,
        proteomes_manifest=_resolve_path(
            inputs.get("proteomes_manifest"), base, "inputs.proteomes_manifest"
        ),
        seeds_manifest=_resolve_path(inputs.get("seeds_manifest"), base, "inputs.seeds_manifest"),
        shortlist_manifest=_resolve_path(
            default_shortlist, base, "inputs.shortlist_manifest"
        ),
        benchmarking=BenchmarkConfig(
            sample_interval_seconds=float(sample_interval),
            collect_slurm_accounting=collect_slurm,
        ),
        reporting=ReportingConfig(**reporting_values),
        resources=ResourceConfig(
            candidate_evidence=_optional_path(
                inputs.get("candidate_evidence"), base, "inputs.candidate_evidence"
            ),
            candidate_evidence_manifest=_optional_path(
                inputs.get("candidate_evidence_manifest"),
                base,
                "inputs.candidate_evidence_manifest",
            ),
            orthofinder_archive=_optional_path(
                inputs.get("orthofinder_archive"), base, "inputs.orthofinder_archive"
            ),
            orthology_species_manifest=_optional_path(
                inputs.get("orthology_species_manifest"),
                base,
                "inputs.orthology_species_manifest",
            ),
            inherited_sqlite=_optional_path(
                inputs.get("inherited_sqlite"), base, "inputs.inherited_sqlite"
            ),
            expression_manifest=_optional_path(
                inputs.get("expression_manifest"), base, "inputs.expression_manifest"
            ),
            ligandability_manifest=_optional_path(
                inputs.get("ligandability_manifest"),
                base,
                "inputs.ligandability_manifest",
            ),
            domain_annotation_manifest=_optional_path(
                inputs.get("domain_annotation_manifest"),
                base,
                "inputs.domain_annotation_manifest",
            ),
            domain_cache_root=_optional_path(
                inputs.get("domain_cache_root"), base, "inputs.domain_cache_root"
            )
            or (output_root / "_shared_resource_cache" / "interpro").resolve(),
            e3_domain_catalogue=_optional_path(
                inputs.get("e3_domain_catalogue"),
                base,
                "inputs.e3_domain_catalogue",
            ),
        ),
        analysis=analysis_config,
        tools=tool_configs,
        stages=tuple(stages),
        digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def previous_stage(name: str) -> str | None:
    """Return the immediately preceding stage, if one exists."""
    try:
        index = STAGE_NAMES.index(name)
    except ValueError as exc:
        raise ConfigurationError(f"Unknown stage: {name}") from exc
    return None if index == 0 else STAGE_NAMES[index - 1]


def stage_dependencies(name: str) -> tuple[str, ...]:
    """Return the scientific prerequisites for a stage.

    Args:
        name: Stable stage identifier.

    Returns:
        Ordered prerequisite stage names.

    Raises:
        ConfigurationError: If the stage name is unknown.
    """
    try:
        return STAGE_DEPENDENCIES[name]
    except KeyError as exc:
        raise ConfigurationError(f"Unknown stage: {name}") from exc


def stage_purpose(name: str) -> tuple[str, str]:
    """Return the action and scientific rationale for a stage.

    Args:
        name: Stable stage identifier.

    Returns:
        Two strings containing what the stage does and why it is required.

    Raises:
        ConfigurationError: If the stage name is unknown.
    """
    try:
        return STAGE_PURPOSES[name]
    except KeyError as exc:
        raise ConfigurationError(f"Unknown stage: {name}") from exc


def stage_interpretation(name: str) -> tuple[str, str]:
    """Return the supported interpretation and scientific limitation for a stage.

    Args:
        name: Stable stage identifier.

    Returns:
        Two strings describing what the result supports and what it does not establish.

    Raises:
        ConfigurationError: If the stage name is unknown.
    """
    try:
        return STAGE_INTERPRETATIONS[name]
    except KeyError as exc:
        raise ConfigurationError(f"Unknown stage: {name}") from exc


def stage_ancestors(name: str) -> tuple[str, ...]:
    """Return every direct and indirect prerequisite in stable stage order.

    Args:
        name: Stable stage identifier.

    Returns:
        De-duplicated prerequisite stage names.
    """
    discovered: set[str] = set()

    def visit(stage_name: str) -> None:
        """Recursively collect prerequisites for one known stage."""
        for dependency in stage_dependencies(stage_name):
            if dependency not in discovered:
                discovered.add(dependency)
                visit(dependency)

    visit(name)
    return tuple(stage_name for stage_name in STAGE_NAMES if stage_name in discovered)
