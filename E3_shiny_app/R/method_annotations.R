#' Recorded-method and threshold annotations for scientific application tabs.

TM_SCORE_REFERENCE_URL <- "https://doi.org/10.1093/bioinformatics/btq066"

#' Build one method section.
#'
#' @param heading User-facing section heading.
#' @param bullets Character vector of complete method statements.
#' @return Named list describing one section.
method_annotation_section <- function(heading, bullets) {
  if (
    length(heading) != 1L || is.na(heading) || !nzchar(trimws(heading)) ||
      !is.character(bullets) || length(bullets) == 0L ||
      anyNA(bullets) || any(!nzchar(trimws(bullets)))
  ) {
    stop("Method sections require a heading and non-empty bullets.", call. = FALSE)
  }
  list(heading = heading, bullets = bullets)
}

#' Build one method reference.
#'
#' @param label Complete citation label.
#' @param url Absolute HTTPS link.
#' @return Named list describing one reference.
method_annotation_reference <- function(label, url) {
  if (
    length(label) != 1L || is.na(label) || !nzchar(trimws(label)) ||
      length(url) != 1L || is.na(url) ||
      !grepl("^https://", url)
  ) {
    stop("Method references require a label and an HTTPS URL.", call. = FALSE)
  }
  list(label = label, url = url)
}

#' Return maintained method annotations.
#'
#' @return Named list keyed by exact user-facing tab label.
method_annotation_entries <- function() {
  section <- method_annotation_section
  reference <- method_annotation_reference
  list(
    "Workflow schematic" = list(
      introduction = paste(
        "The schematic represents the recorded grant-aligned production workflow.",
        "Hard gates, continuous ranking scores and missing-evidence states were",
        "retained as separate evidence layers."
      ),
      sections = list(
        section("Primary pre-structure gates", c(
          paste(
            "At least 0.90 of the 12 target plant species were required; all six",
            "mandatory crop species were required."
          ),
          paste(
            "Domain support was required in at least 0.80 of domain-assessed",
            "species, and expression support in at least 0.80 of",
            "expression-assessed species."
          )
        )),
        section("Primary structural gates", c(
          paste(
            "At least 0.75 target-species structural coverage, minimum member",
            "druggability 0.50, all-member pocket mapping, a conserved",
            "pocket-bearing sequence region and strict 3D support were required."
          ),
          paste(
            "Unavailable evidence remained explicit and was not converted into",
            "a measured biological failure."
          )
        ))
      ),
      interpretation_boundary = paste(
        "Passing the workflow prioritises a group for review; it does not",
        "establish E3 activity, compound binding or successful targeted degradation."
      ),
      references = list()
    ),
    "Computational recommendations" = list(
      introduction = paste(
        "The authoritative ordering combines hard grant-aligned gates with",
        "transparent continuous scores. A high score cannot repair a failed",
        "mandatory gate."
      ),
      sections = list(
        section("Recorded continuous weights", c(
          paste(
            "Pre-structure: 0.10 discovery + 0.35 orthology + 0.20 domain +",
            "0.35 expression."
          ),
          paste(
            "Structural base: 0.55 ligandability + 0.45 pocket conservation;",
            "final: 0.60 pre-structure + 0.40 structural base."
          ),
          paste(
            "The direct 3D numerical refinement weight was 0.00. Recorded 3D",
            "evidence remained available as explicit eligibility and support gates."
          )
        )),
        section("Ordering and gates", c(
          paste(
            "Ordering used gate tier, final score, evidence completeness and",
            "then a stable identifier."
          ),
          paste(
            "Primary numeric gates were target species 0.90, mandatory species",
            "1.00, domains 0.80, expression 0.80, structural species 0.75 and",
            "minimum member druggability 0.50."
          )
        ))
      ),
      interpretation_boundary = paste(
        "Weight and druggability controls in this app are sensitivity analyses",
        "and never overwrite the recorded ranking or source resource."
      ),
      references = list()
    ),
    "Threshold explorer" = list(
      introduction = paste(
        "This page re-evaluates evidence already stored in the completed",
        "resource. It does not rerun annotation, expression, pocket prediction",
        "or structural alignment."
      ),
      sections = list(
        section("Recorded core defaults", c(
          paste(
            "Target species 0.90; mandatory species 1.00; domain-assessed species",
            "0.80; expression-assessed species 0.80; structurally supported",
            "species 0.75; minimum member druggability 0.50."
          ),
          paste(
            "The recorded structural profile also required domain and expression",
            "evidence, a conserved region, all-member mapping and strict 3D support."
          )
        )),
        section("Optional post-hoc controls", c(
          paste(
            "When explicitly enabled, starting values are evidence completeness",
            "0.80, mean pocket pLDDT fraction 0.70, predictor agreement 0.50 and",
            "mean aligned pocket-region overlap 0.25."
          ),
          paste(
            "Optional 3D starting values are mean minimum TM-score 0.50, mean",
            "pocket overlap 0.50 and mean structural chemical-group conservation 0.60."
          )
        ))
      ),
      interpretation_boundary = paste(
        "Optional controls are disabled until selected. Their starting values",
        "must not be reported as additional production gates."
      ),
      references = list()
    ),
    "Independent structural-review shortlist" = list(
      introduction = paste(
        "The shortlist deliberately ranks candidates before structural evidence",
        "is considered, so that new structural review is not circularly selected",
        "by existing pocket or alignment results."
      ),
      sections = list(
        section("Included evidence", c(
          paste(
            "The authoritative root-level HOG pre-structure rank uses discovery,",
            "orthology/species, E3-associated domain and expression evidence."
          ),
          paste(
            "The default is the top 200 HOGs and the control can expand to 500.",
            "The recorded pre-structure-pass filter is optional."
          )
        )),
        section("Excluded evidence", c(
          paste(
            "AlphaFold model, pocket, druggability, mapping, sequence-conservation,",
            "3D-alignment and structural tie-break fields are excluded."
          )
        ))
      ),
      interpretation_boundary = paste(
        "This is a review queue, not a newly recalculated primary candidate ranking."
      ),
      references = list()
    ),
    "Orthology" = list(
      introduction = paste(
        "OrthoFinder 2.5.5 results were integrated without conflating phylogenetic",
        "HOGs, original orthogroups and DeepClust sequence neighbourhoods."
      ),
      sections = list(
        section("Evolutionary grouping", c(
          paste(
            "Root-level N0.HOG groups reconcile gene trees with the species tree",
            "and are the primary evolutionary units used for final prioritisation."
          ),
          paste(
            "Original OG groups are retained as a broader legacy view. DeepClust",
            "clusters are non-phylogenetic discovery inputs."
          )
        )),
        section("Grant-aligned species gate", c(
          paste(
            "At least 0.90 of the 12 configured target plants and all six mandatory",
            "crop species were required for the primary pre-structure gate."
          ),
          paste(
            "With 12 target plants, the 0.90 threshold requires at least 11",
            "represented species."
          )
        ))
      ),
      interpretation_boundary = paste(
        "Membership in the same HOG supports evolutionary relatedness; it does",
        "not prove conserved E3 function, pocket equivalence or ligand binding."
      ),
      references = list()
    ),
    "Domains" = list(
      introduction = paste(
        "Target-plant proteins were annotated through the cached InterPro protein",
        "API and compared with the project's curated catalogue of E3-associated",
        "Pfam domains."
      ),
      sections = list(
        section("Catalogue and support rule", c(
          paste(
            "The catalogue contains RING, HECT, F-box, U-box, IBR/RBR, Cullin,",
            "SOCS-box and VHL-box family-support entries."
          ),
          paste(
            "A species was supported when an assessed member contained at least",
            "one catalogued E3-associated domain. The group gate required support",
            "in at least 0.80 of domain-assessed species."
          )
        )),
        section("Availability handling", c(
          paste(
            "Annotated proteins with no catalogue match were assessed negatives.",
            "Unavailable annotations were excluded from the biological denominator",
            "and reported separately."
          )
        ))
      ),
      interpretation_boundary = paste(
        "A catalogue hit supports an E3-associated family or complex role; it does",
        "not by itself establish complete architecture, catalytic activity or",
        "substrate specificity."
      ),
      references = list()
    ),
    "Expression evidence" = list(
      introduction = paste(
        "Expression Atlas matrices were summarised without treating missing or",
        "ambiguously mapped genes as measured zero expression."
      ),
      sections = list(
        section("Context and species thresholds", c(
          paste(
            "For each experiment group, median TPM of at least 0.50 was",
            "context-positive; FPKM was used only when that experiment had no",
            "TPM matrix."
          ),
          paste(
            "A uniquely mapped gene had broad expression support when at least",
            "0.50 of its available Atlas contexts were positive."
          ),
          paste(
            "The evolutionary-group gate required expression support in at least",
            "0.80 of expression-assessed target species."
          )
        )),
        section("Missingness", c(
          paste(
            "No mapping, ambiguous mapping and no expression records are explicit",
            "availability states and are not interpreted as biological absence."
          )
        ))
      ),
      interpretation_boundary = paste(
        "Expression support shows that a candidate was detected broadly in",
        "available data; it does not demonstrate protein abundance, E3 activity",
        "or suitability in every tissue."
      ),
      references = list()
    ),
    "Ligandability" = list(
      introduction = paste(
        "The structural campaign retrieved AlphaFold Database models, ran FPocket",
        "4.2.2 and rescored the resulting FPocket cavities with P2Rank 2.5.1."
      ),
      sections = list(
        section("AlphaFold model quality", c(
          paste(
            "AlphaFold was not run locally. The highest recoverable canonical",
            "monomer model version was selected per UniProt accession and",
            "provenance was recorded."
          ),
          paste(
            "A whole-model QC flag passed when at least 0.50 of residues had",
            "pLDDT at least 70. The integrated selector did not use this flag as",
            "a standalone exclusion gate; pocket-local confidence was evaluated",
            "separately."
          ),
          paste(
            "API cross-check tolerances were 0.01 for the fraction and 0.25",
            "pLDDT units for the mean."
          )
        )),
        section("Pocket selection and quality", c(
          paste(
            "The integrated pocket-mapping pass used mapping fraction at least",
            "0.95. The component also retained ambiguous rows and a stricter",
            "mapping_qc_pass flag that required the same fraction with zero",
            "ambiguous mappings."
          ),
          paste(
            "At least 0.70 of all predicted pocket residues required mapped",
            "pLDDT at least 70; unmapped or ambiguous residues therefore could",
            "not inflate this conservative fraction."
          ),
          paste(
            "Selected-pocket druggability required FPocket score at least 0.50.",
            "P2Rank used fpocket-rescore with rescore_2024; MATCHED was required",
            "for predictor agreement, with no separate P2Rank probability cutoff."
          )
        ))
      ),
      interpretation_boundary = paste(
        "P2Rank reordered the FPocket cavity set rather than providing an",
        "independent cavity set. Predicted druggability is a computational",
        "prioritisation signal, not binding proof."
      ),
      references = list()
    ),
    "Pocket conservation" = list(
      introduction = paste(
        "Selected pocket residues were mapped to one-based protein coordinates",
        "and compared in MAFFT --auto protein alignments before any 3D",
        "conservation call."
      ),
      sections = list(
        section("Sequence-region thresholds", c(
          paste(
            "Pocket mapping required at least 0.95. Pocket-local confidence",
            "required at least 0.70 of all predicted pocket residues to map with",
            "pLDDT at least 70, so unmapped or ambiguous residues could not",
            "inflate the fraction."
          ),
          paste(
            "Pocket regions were linked when pairwise aligned-region overlap was",
            "at least 0.25. Conserved-region support required at least two reusable",
            "mapped members and mean overlap at least 0.25."
          )
        )),
        section("Recorded score", c(
          paste(
            "Pocket-conservation score = 0.30 component coverage + 0.25 region",
            "overlap + 0.20 chemical-group conservation + 0.15 minimum",
            "druggability + 0.10 pocket pLDDT support."
          )
        ))
      ),
      interpretation_boundary = paste(
        "A conserved pocket-bearing sequence region does not demonstrate the",
        "same 3D cavity; that was evaluated separately by structural superposition."
      ),
      references = list()
    ),
    "3D structures & pockets" = list(
      introduction = paste(
        "This view displays the recorded plant structural campaign; it does not",
        "run structure prediction, pocket prediction or alignment inside the app."
      ),
      sections = list(
        section("AlphaFold Database acquisition and QC", c(
          paste(
            "Canonical monomer mmCIF models were retrieved for representatives",
            "from the 12 target plant species. No human model was selected in",
            "this campaign."
          ),
          paste(
            "Files required valid mmCIF coordinate content and recorded source",
            "URL, model version and SHA-256 checksum. Missing models were",
            "unavailable evidence, not poor-quality structures."
          ),
          paste(
            "A whole-model QC flag used at least 0.50 of residues at pLDDT at",
            "least 70, but was not a standalone downstream exclusion gate. PAE",
            "was downloaded where available but was not a formal production gate."
          )
        )),
        section("Pocket evidence and viewer", c(
          paste(
            "FPocket 4.2.2 generated cavities; P2Rank 2.5.1 fpocket-rescore with",
            "rescore_2024 reordered those cavities. Mapping 0.95, pocket pLDDT",
            "fraction 0.70 and druggability 0.50 were the main pocket thresholds."
          ),
          paste(
            "The portable HTML view shows rotatable C-alpha traces and selected",
            "pocket residues. It is not a full atomistic surface, docking result",
            "or molecular dynamics simulation."
          )
        ))
      ),
      interpretation_boundary = paste(
        "High pLDDT supports local model confidence but does not establish the",
        "correctness of domain placement, cavity dynamics or ligand binding."
      ),
      references = list()
    ),
    "Pocket-aligned sequences" = list(
      introduction = paste(
        "These are MAFFT --auto protein alignments annotated with the selected",
        "pocket's one-based FASTA positions. They are distinct from the later",
        "whole-structure alignments."
      ),
      sections = list(
        section("Mapping and overlap", c(
          paste(
            "The integrated mapping pass required at least 0.95 of pocket",
            "residues to map. Ambiguous and unmapped attempts were retained; the",
            "component's stricter mapping_qc_pass flag also required zero",
            "ambiguity."
          ),
          paste(
            "The aligned pocket-region linkage threshold was 0.25 overlap relative",
            "to the smaller region. The recorded top-five alternative-pocket",
            "review remained a sensitivity analysis and did not replace the",
            "strict rank-one pocket."
          )
        ))
      ),
      interpretation_boundary = paste(
        "Aligned sequence position is evidence for a shared pocket-bearing region,",
        "not for an equivalent 3D pocket shape."
      ),
      references = list()
    ),
    "3D alignment" = list(
      introduction = paste(
        "Python orchestrated two specialist compiled structural aligners, US-align",
        "build 20241201 and TM-align build 20240303, and applied each recorded",
        "transformation to the pocket coordinates."
      ),
      sections = list(
        section("Global fold threshold", c(
          paste(
            "Each aligner reports TM-scores normalised by both structure lengths;",
            "the lower score was retained. Both aligners had to meet TM-score",
            "at least 0.50."
          ),
          paste(
            "The 0.50 value is an established approximate same-fold/topology",
            "boundary, not a threshold invented for this project. It does not",
            "itself establish that two pockets occupy the same position."
          )
        )),
        section("Pocket-position and strict-conservation thresholds", c(
          paste(
            "Same-position support required centroid distance at most 8 Angstrom,",
            "symmetric pocket overlap at least 0.50 and the global TM-score rule.",
            "Residue proximity was assessed within 4 Angstrom."
          ),
          paste(
            "Pairwise strict local conservation additionally required",
            "structural-residue match at least 0.50 and chemical-group",
            "conservation at least 0.60."
          ),
          paste(
            "A group-level call required group support at least 0.75 among",
            "eligible members, with both aligners agreeing for each assessed",
            "mobile member."
          ),
          paste(
            "Top-five alternative-pocket results were retained as sensitivity",
            "evidence and did not overwrite the strict rank-one result."
          )
        ))
      ),
      interpretation_boundary = paste(
        "TM-score measures global fold similarity. Pocket centroid, overlap and",
        "local residue tests answer the separate question of whether the selected",
        "cavities correspond."
      ),
      references = list(reference(
        paste(
          "Xu and Zhang (2010), How significant is a protein structure similarity",
          "with TM-score = 0.5?"
        ),
        TM_SCORE_REFERENCE_URL
      ))
    ),
    "Computational chemistry" = list(
      introduction = paste(
        "The completed project resource records a preliminary open-source,",
        "residue-derived pharmacophore hand-off. The wider chemistry programme",
        "has now passed to the computational chemistry team."
      ),
      sections = list(
        section("Executed and non-executed methods", c(
          paste(
            "The open structure-guided pharmacophore method generated hypotheses",
            "from mapped pocket residues and their chemical classes."
          ),
          paste(
            "AlphaFold3, FMOPhore and FrAncestor were explicitly NOT_RUN in this",
            "workflow. A blank or NOT_RUN state is not a failed chemistry result."
          )
        ))
      ),
      interpretation_boundary = paste(
        "Pharmacophore features are computational hypotheses for expert review;",
        "they are not docking scores, affinity estimates or experimentally",
        "demonstrated binding sites."
      ),
      references = list()
    ),
    "Provenance and QC" = list(
      introduction = paste(
        "Scientific tables were written with stable identifiers, recorded",
        "thresholds and source-level provenance so that decisions can be audited",
        "without relying on the app."
      ),
      sections = list(
        section("Recorded controls", c(
          paste(
            "Downloaded structures and reused assets retain source paths or URLs,",
            "model or tool versions and SHA-256 checksums where supplied by the",
            "producing stage."
          ),
          paste(
            "Missing, unavailable, not assessed and failed evidence states remain",
            "distinct. App sliders never rewrite the integrated DuckDB or Parquet evidence."
          )
        ))
      ),
      interpretation_boundary = paste(
        "The integrated DuckDB is the detailed relational authority.",
        "Candidate-level Parquet files are portable summaries and do not contain",
        "every one-to-many evidence row."
      ),
      references = list()
    )
  )
}

#' Return one maintained method annotation.
#'
#' @param tab_name Exact user-facing tab label.
#' @return Named annotation list.
method_annotation_entry <- function(tab_name) {
  entries <- method_annotation_entries()
  if (
    length(tab_name) != 1L || is.na(tab_name) ||
      !tab_name %in% names(entries)
  ) {
    stop(
      "No method and threshold annotation is defined for this tab.",
      call. = FALSE
    )
  }
  entries[[tab_name]]
}

#' Build a collapsed method and threshold box.
#'
#' @param tab_name Exact user-facing tab label.
#' @return HTML details element.
method_annotation_ui <- function(tab_name) {
  entry <- method_annotation_entry(tab_name = tab_name)
  section_tags <- lapply(entry$sections, function(section) {
    shiny::tagList(
      shiny::h5(section$heading),
      shiny::tags$ul(lapply(section$bullets, shiny::tags$li))
    )
  })
  reference_tags <- if (length(entry$references) == 0L) {
    NULL
  } else {
    shiny::tagList(
      shiny::h5("Method reference"),
      shiny::tags$ul(lapply(entry$references, function(reference) {
        shiny::tags$li(shiny::tags$a(
          href = reference$url,
          target = "_blank",
          rel = "noopener noreferrer",
          reference$label
        ))
      }))
    )
  }
  shiny::tags$details(
    class = "e3-method-help",
    shiny::tags$summary("ⓘ Methods and thresholds"),
    shiny::p(entry$introduction),
    section_tags,
    shiny::p(
      class = "e3-method-boundary",
      shiny::strong("Interpretation boundary: "),
      entry$interpretation_boundary
    ),
    reference_tags
  )
}
