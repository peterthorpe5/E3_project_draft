"""Recorded-method and threshold annotations for scientific application tabs."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from e3app.errors import AppError

LOGGER = logging.getLogger(__name__)

TM_SCORE_REFERENCE_URL = "https://doi.org/10.1093/bioinformatics/btq066"


@dataclass(frozen=True)
class MethodSection:
    """One titled group of method statements."""

    heading: str
    bullets: tuple[str, ...]


@dataclass(frozen=True)
class MethodReference:
    """One external method reference."""

    label: str
    url: str


@dataclass(frozen=True)
class MethodAnnotation:
    """Complete collapsed method annotation for one application tab."""

    introduction: str
    sections: tuple[MethodSection, ...]
    interpretation_boundary: str
    references: tuple[MethodReference, ...] = ()


METHOD_ANNOTATIONS = {
    "Workflow schematic": MethodAnnotation(
        introduction=(
            "The schematic represents the recorded grant-aligned production workflow. "
            "Hard gates, continuous ranking scores and missing-evidence states were retained "
            "as separate evidence layers."
        ),
        sections=(
            MethodSection(
                heading="Primary pre-structure gates",
                bullets=(
                    "At least 0.90 of the 12 target plant species were required; all six "
                    "mandatory crop species were required.",
                    "Domain support was required in at least 0.80 of domain-assessed species, "
                    "and expression support in at least 0.80 of expression-assessed species.",
                ),
            ),
            MethodSection(
                heading="Primary structural gates",
                bullets=(
                    "At least 0.75 target-species structural coverage, minimum member "
                    "druggability 0.50, all-member pocket mapping, a conserved pocket-bearing "
                    "sequence region and strict 3D support were required.",
                    "Unavailable evidence remained explicit and was not converted into a "
                    "measured biological failure.",
                ),
            ),
        ),
        interpretation_boundary=(
            "Passing the workflow prioritises a group for review; it does not establish E3 "
            "activity, compound binding or successful targeted degradation."
        ),
    ),
    "Computational recommendations": MethodAnnotation(
        introduction=(
            "The authoritative ordering combines hard grant-aligned gates with transparent "
            "continuous scores. A high score cannot repair a failed mandatory gate."
        ),
        sections=(
            MethodSection(
                heading="Recorded continuous weights",
                bullets=(
                    "Pre-structure: 0.10 discovery + 0.35 orthology + 0.20 domain + 0.35 "
                    "expression.",
                    "Structural base: 0.55 ligandability + 0.45 pocket conservation; final: "
                    "0.60 pre-structure + 0.40 structural base.",
                    "The direct 3D numerical refinement weight was 0.00. Recorded 3D evidence "
                    "remained available as explicit eligibility and support gates.",
                ),
            ),
            MethodSection(
                heading="Ordering and gates",
                bullets=(
                    "Ordering used gate tier, final score, evidence completeness and then a "
                    "stable identifier.",
                    "Primary numeric gates were target species 0.90, mandatory species 1.00, "
                    "domains 0.80, expression 0.80, structural species 0.75 and minimum member "
                    "druggability 0.50.",
                ),
            ),
        ),
        interpretation_boundary=(
            "Weight and druggability controls in this app are sensitivity analyses and never "
            "overwrite the recorded ranking or source resource."
        ),
    ),
    "Threshold explorer": MethodAnnotation(
        introduction=(
            "This page re-evaluates evidence already stored in the completed resource. It does "
            "not rerun annotation, expression, pocket prediction or structural alignment."
        ),
        sections=(
            MethodSection(
                heading="Recorded core defaults",
                bullets=(
                    "Target species 0.90; mandatory species 1.00; domain-assessed species 0.80; "
                    "expression-assessed species 0.80; structurally supported species 0.75; "
                    "minimum member druggability 0.50.",
                    "The recorded structural profile also required domain and expression "
                    "evidence, a conserved region, all-member mapping and strict 3D support.",
                ),
            ),
            MethodSection(
                heading="Optional post-hoc controls",
                bullets=(
                    "When explicitly enabled, starting values are evidence completeness 0.80, "
                    "mean pocket pLDDT fraction 0.70, predictor agreement 0.50 and mean aligned "
                    "pocket-region overlap 0.25.",
                    "Optional 3D starting values are mean minimum TM-score 0.50, mean pocket "
                    "overlap 0.50 and mean structural chemical-group conservation 0.60.",
                ),
            ),
        ),
        interpretation_boundary=(
            "Optional controls are disabled until selected. Their starting values must not be "
            "reported as additional production gates."
        ),
    ),
    "Independent structural-review shortlist": MethodAnnotation(
        introduction=(
            "The shortlist deliberately ranks candidates before structural evidence is "
            "considered, so that new structural review is not circularly selected by existing "
            "pocket or alignment results."
        ),
        sections=(
            MethodSection(
                heading="Included evidence",
                bullets=(
                    "The authoritative root-level HOG pre-structure rank uses discovery, "
                    "orthology/species, E3-associated domain and expression evidence.",
                    "The default is the top 200 HOGs and the control can expand to 500. The "
                    "recorded pre-structure-pass filter is optional.",
                ),
            ),
            MethodSection(
                heading="Excluded evidence",
                bullets=(
                    "AlphaFold model, pocket, druggability, mapping, sequence-conservation, "
                    "3D-alignment and structural tie-break fields are excluded.",
                ),
            ),
        ),
        interpretation_boundary=(
            "This is a review queue, not a newly recalculated primary candidate ranking."
        ),
    ),
    "Orthology": MethodAnnotation(
        introduction=(
            "OrthoFinder 2.5.5 results were integrated without conflating phylogenetic HOGs, "
            "original orthogroups and DeepClust sequence neighbourhoods."
        ),
        sections=(
            MethodSection(
                heading="Evolutionary grouping",
                bullets=(
                    "Root-level N0.HOG groups reconcile gene trees with the species tree and "
                    "are the primary evolutionary units used for final prioritisation.",
                    "Original OG groups are retained as a broader legacy view. DeepClust "
                    "clusters are non-phylogenetic discovery inputs.",
                ),
            ),
            MethodSection(
                heading="Grant-aligned species gate",
                bullets=(
                    "At least 0.90 of the 12 configured target plants and all six mandatory crop "
                    "species were required for the primary pre-structure gate.",
                    "With 12 target plants, the 0.90 threshold requires at least 11 represented "
                    "species.",
                ),
            ),
        ),
        interpretation_boundary=(
            "Membership in the same HOG supports evolutionary relatedness; it does not prove "
            "conserved E3 function, pocket equivalence or ligand binding."
        ),
    ),
    "Domains": MethodAnnotation(
        introduction=(
            "Target-plant proteins were annotated through the cached InterPro protein API and "
            "compared with the project's curated catalogue of E3-associated Pfam domains."
        ),
        sections=(
            MethodSection(
                heading="Catalogue and support rule",
                bullets=(
                    "The catalogue contains RING, HECT, F-box, U-box, IBR/RBR, Cullin, SOCS-box "
                    "and VHL-box family-support entries.",
                    "A species was supported when an assessed member contained at least one "
                    "catalogued E3-associated domain. The group gate required support in at "
                    "least 0.80 of domain-assessed species.",
                ),
            ),
            MethodSection(
                heading="Availability handling",
                bullets=(
                    "Annotated proteins with no catalogue match were assessed negatives. "
                    "Unavailable annotations were excluded from the biological denominator and "
                    "reported separately.",
                ),
            ),
        ),
        interpretation_boundary=(
            "A catalogue hit supports an E3-associated family or complex role; it does not by "
            "itself establish complete architecture, catalytic activity or substrate specificity."
        ),
    ),
    "Expression": MethodAnnotation(
        introduction=(
            "Expression Atlas matrices were summarised without treating missing or ambiguously "
            "mapped genes as measured zero expression."
        ),
        sections=(
            MethodSection(
                heading="Context and species thresholds",
                bullets=(
                    "For each experiment group, median TPM of at least 0.50 was context-positive; "
                    "FPKM was used only when that experiment had no TPM matrix.",
                    "A uniquely mapped gene had broad expression support when at least 0.50 of "
                    "its available Atlas contexts were positive.",
                    "The evolutionary-group gate required expression support in at least 0.80 "
                    "of expression-assessed target species.",
                ),
            ),
            MethodSection(
                heading="Missingness",
                bullets=(
                    "No mapping, ambiguous mapping and no expression records are explicit "
                    "availability states and are not interpreted as biological absence.",
                ),
            ),
        ),
        interpretation_boundary=(
            "Expression support shows that a candidate was detected broadly in available data; "
            "it does not demonstrate protein abundance, E3 activity or suitability in every tissue."
        ),
    ),
    "Ligandability": MethodAnnotation(
        introduction=(
            "The structural campaign retrieved AlphaFold Database models, ran FPocket 4.2.2 and "
            "rescored the resulting FPocket cavities with P2Rank 2.5.1."
        ),
        sections=(
            MethodSection(
                heading="AlphaFold model quality",
                bullets=(
                    "AlphaFold was not run locally. The highest recoverable canonical monomer "
                    "model version was selected per UniProt accession and provenance was recorded.",
                    "A whole-model QC flag passed when at least 0.50 of residues had pLDDT at "
                    "least 70. The integrated selector did not use this flag as a standalone "
                    "exclusion gate; pocket-local confidence was evaluated separately.",
                    "API cross-check tolerances were 0.01 for the fraction and 0.25 pLDDT units "
                    "for the mean.",
                ),
            ),
            MethodSection(
                heading="Pocket selection and quality",
                bullets=(
                    "The integrated pocket-mapping pass used mapping fraction at least 0.95. The "
                    "component also retained ambiguous rows and a stricter mapping_qc_pass flag "
                    "that required the same fraction with zero ambiguous mappings.",
                    "At least 0.70 of all predicted pocket residues required mapped pLDDT at "
                    "least 70; unmapped or ambiguous residues therefore could not inflate this "
                    "conservative fraction.",
                    "Selected-pocket druggability required FPocket score at least 0.50. P2Rank "
                    "used fpocket-rescore with rescore_2024; MATCHED was required for predictor "
                    "agreement, with no separate P2Rank probability cutoff.",
                ),
            ),
        ),
        interpretation_boundary=(
            "P2Rank reordered the FPocket cavity set rather than providing an independent cavity "
            "set. Predicted druggability is a computational prioritisation signal, not binding "
            "proof."
        ),
    ),
    "Pocket conservation": MethodAnnotation(
        introduction=(
            "Selected pocket residues were mapped to one-based protein coordinates and compared "
            "in MAFFT --auto protein alignments before any 3D conservation call."
        ),
        sections=(
            MethodSection(
                heading="Sequence-region thresholds",
                bullets=(
                    "Pocket mapping required at least 0.95. Pocket-local confidence required "
                    "at least 0.70 of all predicted pocket residues to map with pLDDT at least "
                    "70, so unmapped or ambiguous residues could not inflate the fraction.",
                    "Pocket regions were linked when pairwise aligned-region overlap was at least "
                    "0.25. Conserved-region support required at least two reusable mapped members "
                    "and mean overlap at least 0.25.",
                ),
            ),
            MethodSection(
                heading="Recorded score",
                bullets=(
                    "Pocket-conservation score = 0.30 component coverage + 0.25 region overlap + "
                    "0.20 chemical-group conservation + 0.15 minimum druggability + 0.10 pocket "
                    "pLDDT support.",
                ),
            ),
        ),
        interpretation_boundary=(
            "A conserved pocket-bearing sequence region does not demonstrate the same 3D cavity; "
            "that was evaluated separately by structural superposition."
        ),
    ),
    "3D structures & pockets": MethodAnnotation(
        introduction=(
            "This view displays the recorded plant structural campaign; it does not run structure "
            "prediction, pocket prediction or alignment inside the app."
        ),
        sections=(
            MethodSection(
                heading="Why one protein represented each plant species",
                bullets=(
                    "The parent campaign retained one deterministic representative per "
                    "target species and evolutionary group so that paralogue-rich species "
                    "could not contribute more structures simply because they contained "
                    "more accessions.",
                    "When a group contained several Arabidopsis thaliana accessions, the "
                    "ordering first preferred a likely full-length sequence (0.75 to 1.35 "
                    "times the group's median species-maximum length), then a reviewed "
                    "record, an original input candidate, a mapped record, length closest "
                    "to that group reference, the longer sequence, and finally stable "
                    "accession and raw-identifier tie-breaks.",
                    "Every selected and non-selected alternative, its within-species rank "
                    "and its selection reason are retained in "
                    "structural_representative_selection_audit. Selection is therefore "
                    "auditable and computationally reproducible; it is not a claim that "
                    "the selected paralogue is biologically superior.",
                ),
            ),
            MethodSection(
                heading="AlphaFold Database acquisition and QC",
                bullets=(
                    "Canonical monomer mmCIF models were retrieved for representatives from the "
                    "12 target plant species. No human model was selected in this campaign.",
                    "Files required valid mmCIF coordinate content and recorded source URL, model "
                    "version and SHA-256 checksum. Missing models were unavailable evidence, not "
                    "poor-quality structures.",
                    "A whole-model QC flag used at least 0.50 of residues at pLDDT at least 70, "
                    "but was not a standalone downstream exclusion gate. PAE was downloaded where "
                    "available but was not a formal production gate.",
                ),
            ),
            MethodSection(
                heading="Pocket evidence and viewer",
                bullets=(
                    "FPocket 4.2.2 generated cavities; P2Rank 2.5.1 fpocket-rescore with "
                    "rescore_2024 reordered those cavities. Mapping 0.95, pocket pLDDT fraction "
                    "0.70 and druggability 0.50 were the main pocket thresholds.",
                    "The portable HTML view shows rotatable C-alpha traces and selected pocket "
                    "residues. It is not a full atomistic surface, docking result or molecular "
                    "dynamics simulation.",
                ),
            ),
        ),
        interpretation_boundary=(
            "High pLDDT supports local model confidence but does not establish the correctness of "
            "domain placement, cavity dynamics or ligand binding."
        ),
    ),
    "Pocket-aligned sequences": MethodAnnotation(
        introduction=(
            "These are MAFFT --auto protein alignments annotated with the selected pocket's "
            "one-based FASTA positions. They are distinct from the later whole-structure "
            "alignments."
        ),
        sections=(
            MethodSection(
                heading="Mapping and overlap",
                bullets=(
                    "The integrated mapping pass required at least 0.95 of pocket residues to map. "
                    "Ambiguous and unmapped attempts were retained; the component's stricter "
                    "mapping_qc_pass flag also required zero ambiguity.",
                    "The aligned pocket-region linkage threshold was 0.25 overlap relative to the "
                    "smaller region. The recorded top-five alternative-pocket review remained a "
                    "sensitivity analysis and did not replace the strict rank-one pocket.",
                ),
            ),
        ),
        interpretation_boundary=(
            "Aligned sequence position is evidence for a shared pocket-bearing region, not for an "
            "equivalent 3D pocket shape."
        ),
    ),
    "3D alignment": MethodAnnotation(
        introduction=(
            "Python orchestrated two specialist compiled structural aligners, US-align build "
            "20241201 and TM-align build 20240303, and applied each recorded transformation to "
            "the pocket coordinates."
        ),
        sections=(
            MethodSection(
                heading="Fixed reference model",
                bullets=(
                    "After one representative was retained per target plant species, the "
                    "eligible reference ordering preferred high-confidence structural status, "
                    "pocket-predictor agreement, pocket mapping, pocket-local pLDDT and predicted "
                    "druggability, followed by accession as the final tie-break.",
                    "Species identity was not an ordering field. A Medicago truncatula reference, "
                    "for example, means that its representative led this evidence hierarchy; it "
                    "does not identify an ancestral, universally closest or biologically superior "
                    "protein.",
                    "Every other eligible model was transformed onto this one fixed coordinate "
                    "frame so centroid and pocket-overlap comparisons remained directly "
                    "comparable within the group.",
                ),
            ),
            MethodSection(
                heading="Global fold threshold",
                bullets=(
                    "Each aligner reports TM-scores normalised by both structure lengths; the "
                    "lower score was retained. Both aligners had to meet TM-score at least 0.50.",
                    "The 0.50 value is an established approximate same-fold/topology boundary, "
                    "not a threshold invented for this project. It does not itself establish "
                    "that two pockets occupy the same position.",
                ),
            ),
            MethodSection(
                heading="Pocket-position and strict-conservation thresholds",
                bullets=(
                    "Same-position support required centroid distance at most 8 Angstrom, "
                    "symmetric pocket overlap at least 0.50 and the global TM-score rule. Residue "
                    "proximity was assessed within 4 Angstrom.",
                    "Pairwise strict local conservation additionally required structural-residue "
                    "match at least 0.50 and chemical-group conservation at least 0.60.",
                    "A group-level call required group support at least 0.75 among eligible "
                    "members, with both aligners agreeing for each assessed mobile member.",
                    "Top-five alternative-pocket results were retained as sensitivity evidence and "
                    "did not overwrite the strict rank-one result.",
                ),
            ),
        ),
        interpretation_boundary=(
            "TM-score measures global fold similarity. Pocket centroid, overlap and local residue "
            "tests answer the separate question of whether the selected cavities correspond."
        ),
        references=(
            MethodReference(
                label=(
                    "Xu and Zhang (2010), How significant is a protein structure similarity "
                    "with TM-score = 0.5?"
                ),
                url=TM_SCORE_REFERENCE_URL,
            ),
        ),
    ),
    "Human & plant 3D alignment": MethodAnnotation(
        introduction=(
            "This separately labelled extension adds Homo sapiens members to the selected "
            "plant HOGs while preserving each group's recorded plant reference and the original "
            "plant-only result. Human AlphaFold Database models and pockets are processed with "
            "the same versioned methods and thresholds used for the plant campaign."
        ),
        sections=(
            MethodSection(
                heading="Scope and comparability",
                bullets=(
                    "Human membership comes from the same root-level OrthoFinder HOG authority "
                    "used in the app's Plant & human HOGs view; only exact, uniquely resolved "
                    "protein accessions and published sequences enter structural processing.",
                    "The human-inclusive outputs are stored under a separate analysis scope. "
                    "They do not change pre-structure rank, post-structure rank or the strict "
                    "plant-only support calls.",
                ),
            ),
            MethodSection(
                heading="Why these human members and this plant reference were used",
                bullets=(
                    "All exact Homo sapiens accessions published in the qualifying "
                    "OrthoFinder group were carried into the extension; the workflow did "
                    "not choose one favoured human paralogue. A human member appears in a "
                    "3D pair only when its model, selected pocket and coordinate mapping "
                    "are eligible. Exact sequence-only members remain in the supplementary "
                    "FASTA inventory.",
                    "The fixed plant reference was inherited unchanged from the completed "
                    "plant structural summary. The extension supplied it as a preferred "
                    "reference manifest and failed closed if that accession was not an "
                    "eligible selected-pocket model; it never chose a new reference to make "
                    "a human comparison look stronger.",
                    "In the parent structural analysis, the reference among the selected "
                    "one-per-species representatives was ordered by high-confidence "
                    "structural-evidence status, predictor agreement, pocket mapping "
                    "fraction, pocket pLDDT fraction and druggability, followed by accession "
                    "as the deterministic final tie-break.",
                    "Species identity was not part of that ordering. A Medicago truncatula "
                    "reference, for example, records which eligible representative ranked first "
                    "on the evidence fields; it is not an ancestral or preferred-species claim.",
                ),
            ),
            MethodSection(
                heading="Matched structural rules",
                bullets=(
                    "US-align and TM-align both compare each eligible member with the preserved "
                    "plant reference. The lower length-normalised TM-score must be at least 0.50.",
                    "Same-position support retains centroid distance at most 8 Angstrom and "
                    "symmetric pocket overlap at least 0.50. Strict local support retains the "
                    "4 Angstrom residue distance, 0.50 residue-match, 0.60 chemical-group and "
                    "0.75 group-support thresholds.",
                ),
            ),
        ),
        interpretation_boundary=(
            "Human and plant co-membership and predicted structural correspondence support "
            "comparative prioritisation; they do not demonstrate conserved E3 activity, ligand "
            "binding, degradation or transferable PROTAC pharmacology."
        ),
        references=(
            MethodReference(
                label=(
                    "Xu and Zhang (2010), How significant is a protein structure similarity "
                    "with TM-score = 0.5?"
                ),
                url=TM_SCORE_REFERENCE_URL,
            ),
        ),
    ),
    "Computational chemistry": MethodAnnotation(
        introduction=(
            "The completed project resource records a preliminary open-source, residue-derived "
            "pharmacophore hand-off. The wider chemistry programme has now passed to the "
            "computational chemistry team."
        ),
        sections=(
            MethodSection(
                heading="Executed and non-executed methods",
                bullets=(
                    "The open structure-guided pharmacophore method generated hypotheses from "
                    "mapped pocket residues and their chemical classes.",
                    "AlphaFold3, FMOPhore and FrAncestor were explicitly NOT_RUN in this workflow. "
                    "A blank or NOT_RUN state is not a failed chemistry result.",
                ),
            ),
        ),
        interpretation_boundary=(
            "Pharmacophore features are computational hypotheses for expert review; they are not "
            "docking scores, affinity estimates or experimentally demonstrated binding sites."
        ),
    ),
    "Provenance and QC": MethodAnnotation(
        introduction=(
            "Scientific tables were written with stable identifiers, recorded thresholds and "
            "source-level provenance so that decisions can be audited without relying on the app."
        ),
        sections=(
            MethodSection(
                heading="Recorded controls",
                bullets=(
                    "Downloaded structures and reused assets retain source paths or URLs, model or "
                    "tool versions and SHA-256 checksums where supplied by the producing stage.",
                    "Missing, unavailable, not assessed and failed evidence states remain "
                    "distinct. App sliders never rewrite the integrated DuckDB or Parquet "
                    "evidence.",
                ),
            ),
        ),
        interpretation_boundary=(
            "The integrated DuckDB is the detailed relational authority. Candidate-level Parquet "
            "files are portable summaries and do not contain every one-to-many evidence row."
        ),
    ),
}


def method_annotation(*, tab_name: str) -> MethodAnnotation:
    """Return the recorded-method annotation for one scientific tab.

    Args:
        tab_name: Exact user-facing tab label.

    Returns:
        Maintained method annotation for the requested tab.

    Raises:
        AppError: If the tab has no maintained method annotation.
    """
    try:
        annotation = METHOD_ANNOTATIONS[tab_name]
    except KeyError as exc:
        raise AppError(
            f"No method and threshold annotation is defined for tab: {tab_name}"
        ) from exc
    LOGGER.debug("Loaded method annotation for tab=%s", tab_name)
    return annotation


def method_annotation_markdown(*, tab_name: str) -> str:
    """Render one annotation as Streamlit-compatible Markdown.

    Args:
        tab_name: Exact user-facing tab label.

    Returns:
        Markdown containing the introduction, sections, boundary and references.
    """
    annotation = method_annotation(tab_name=tab_name)
    blocks = [annotation.introduction]
    for section in annotation.sections:
        blocks.append(f"**{section.heading}**")
        blocks.extend(f"- {bullet}" for bullet in section.bullets)
    blocks.append(
        f"**Interpretation boundary:** {annotation.interpretation_boundary}"
    )
    if annotation.references:
        blocks.append("**Method reference**")
        blocks.extend(
            f"- [{reference.label}]({reference.url})"
            for reference in annotation.references
        )
    return "\n\n".join(blocks)
