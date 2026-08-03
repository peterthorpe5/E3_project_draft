#' Scientific glossary and threshold definitions.
#'
#' These definitions describe the immutable completed top-200 analysis. They are
#' kept in code so the glossary and the threshold controls share wording.

#' Return plain-language help for every numeric threshold control.
#'
#' @return Named character vector.
threshold_help_texts <- function() {
  c(
    target_species_fraction = paste(
      "The proportion of the 12 configured target plant species represented",
      "in the evolutionary group. The table reports the represented count,",
      "total and fraction."
    ),
    mandatory_species_fraction = paste(
      "The proportion of the six mandatory crop species represented:",
      "barley, rice, tomato, potato, wheat and maize. The recorded primary",
      "analysis required all six."
    ),
    domain_species_fraction = paste(
      "Among species for which a group member has usable domain annotation,",
      "the proportion with a catalogued E3-associated domain. Species without",
      "usable annotation are reported as unavailable and are not silently",
      "counted as domain-negative."
    ),
    expression_species_fraction = paste(
      "Among species whose group member mapped uniquely to an available",
      "Expression Atlas gene, the proportion with broad expression support.",
      "Unmapped or unavailable species are reported separately and are not",
      "treated as measured zero expression."
    ),
    structural_species_fraction = paste(
      "The proportion of the 12 target species represented by a member",
      "contributing to the conserved pocket-bearing structural component.",
      "This is coverage, not a TM-score."
    ),
    minimum_druggability_score = paste(
      "The lowest selected-pocket druggability score among assessed members",
      "of the group. Using the minimum makes the gate an",
      "all-assessed-members requirement."
    )
  )
}

#' Return one threshold-control help string.
#'
#' @param id Stable threshold identifier.
#' @return Plain-language character scalar.
threshold_help_text <- function(id) {
  definitions <- threshold_help_texts()
  if (length(id) != 1L || is.na(id) || !id %in% names(definitions)) {
    stop(paste0("Unknown threshold help identifier: ", id), call. = FALSE)
  }
  unname(definitions[[id]])
}

#' Build one glossary record.
#'
#' @param section Broad glossary section.
#' @param term User-facing term.
#' @param definition Plain-language definition.
#' @param recorded_rule Exact completed-analysis rule, when relevant.
#' @return One-row tibble.
glossary_record <- function(section, term, definition, recorded_rule = "") {
  tibble::tibble(
    Section = section,
    Term = term,
    `Plain-language definition` = definition,
    `Recorded top-200 rule` = recorded_rule
  )
}

#' Build the complete glossary table.
#'
#' @return Tibble with section, term, definition and recorded rule.
scientific_glossary <- function() {
  add <- glossary_record
  dplyr::bind_rows(
    add(
      "Groups and identifiers", "Seed",
      paste(
        "A protein supplied as prior E3 evidence to initiate candidate",
        "discovery. A seed is discovery evidence; it is not automatically a final candidate."
      )
    ),
    add(
      "Groups and identifiers", "Normalised seed",
      paste(
        "A seed after identifier cleaning, de-duplication and provenance",
        "retention, represented by the accession used consistently by the workflow."
      )
    ),
    add(
      "Groups and identifiers", "Non-seed member",
      paste(
        "An OrthoFinder-group protein that was not in the seed set. It is",
        "retained because orthology places it in the same evolutionary group."
      )
    ),
    add(
      "Groups and identifiers", "DeepClust cluster",
      paste(
        "A sequence-similarity discovery cluster. Several DeepClust clusters",
        "can contribute to one evolutionary group, so it is not the final counting unit."
      )
    ),
    add(
      "Groups and identifiers", "Orthogroup",
      paste(
        "An OrthoFinder group of genes descended from one gene in the last",
        "common ancestor of the analysed species, labelled with an OG identifier."
      )
    ),
    add(
      "Groups and identifiers", "Hierarchical orthogroup (HOG)",
      paste(
        "An OrthoFinder evolutionary group defined at a named species-tree",
        "node. Current resource identifiers commonly begin N0.HOG."
      )
    ),
    add(
      "Groups and identifiers", "Evolutionary candidate group",
      paste(
        "The final decision unit after explicit OrthoFinder mapping and",
        "deterministic de-duplication. Headline counts use this unit."
      )
    ),
    add(
      "Decision language", "Gate",
      paste(
        "A required yes/no rule. A candidate passes a combined analysis only",
        "when it satisfies every enabled gate."
      )
    ),
    add(
      "Decision language", "Gated / gated out",
      paste(
        "Excluded from the current passing list because at least one enabled",
        "gate was not met. This is not proof of biological inactivity."
      )
    ),
    add(
      "Decision language", "Strict / stringent",
      paste(
        "The immutable primary rule set: rank-one selected pockets, every",
        "enabled gate, and both structural aligners where 3D support is required."
      )
    ),
    add(
      "Decision language", "Sensitivity analysis",
      paste(
        "An exploratory list produced by changing app thresholds or named",
        "alternative rules. It does not replace the strict primary result."
      )
    ),
    add(
      "Decision language", "Assessed",
      "The necessary data were available and the relevant computational test was performed."
    ),
    add(
      "Decision language", "Unavailable / not assessed",
      paste(
        "The necessary evidence was absent or the group was outside the",
        "analysed cohort. This is not a negative biological result."
      )
    ),
    add(
      "Pre-structure thresholds", "Minimum target-species fraction",
      threshold_help_text("target_species_fraction"),
      "At least 0.90 (90%) of 12 configured target species."
    ),
    add(
      "Pre-structure thresholds", "Minimum mandatory-species fraction",
      threshold_help_text("mandatory_species_fraction"),
      "1.00: all six mandatory crop species."
    ),
    add(
      "Pre-structure thresholds",
      "Minimum domain-supported assessed-species fraction",
      threshold_help_text("domain_species_fraction"),
      "At least 0.80 (80%) of species with usable domain annotation."
    ),
    add(
      "Pre-structure thresholds", "Positive expression measurement",
      paste(
        "A mapped gene-by-condition TPM or FPKM measurement above the",
        "configured value, distinct from an unmapped gene or unavailable experiment."
      ),
      "Greater than 0.0 TPM/FPKM in the completed run."
    ),
    add(
      "Pre-structure thresholds", "Broad expression support for one mapped gene",
      "The fraction of that gene's available Atlas measurements classified as positive.",
      "At least 0.50 (50%) of measurements were greater than 0.0."
    ),
    add(
      "Pre-structure thresholds",
      "Minimum expression-supported assessed-species fraction",
      threshold_help_text("expression_species_fraction"),
      "At least 0.80 (80%) of uniquely mapped, expression-assessed species."
    ),
    add(
      "Expression evidence states", "NOT_MAPPED",
      paste(
        "No candidate alias matched an Atlas gene identifier uniquely. Any",
        "displayed zero counts are placeholders for absent mapped evidence,",
        "not measured zero expression."
      )
    ),
    add(
      "Expression evidence states", "NO_EXPRESSION_RECORDS",
      paste(
        "A unique gene mapping exists, but the imported Atlas resource contains",
        "no expression measurements for that gene."
      )
    ),
    add(
      "Expression evidence states", "LIMITED_OR_ZERO_EXPRESSION",
      paste(
        "Expression was measured, but fewer than half of available measurements",
        "exceeded the recorded positive-expression threshold."
      )
    ),
    add(
      "Expression evidence states", "BROAD_EXPRESSION_SUPPORTED",
      paste(
        "Expression was measured and at least half of available measurements",
        "exceeded the recorded positive-expression threshold."
      )
    ),
    add(
      "Expression evidence states", "Tissue / organism part",
      paste(
        "The sample's anatomical source as supplied by Atlas metadata, for",
        "example leaf or root. Original labels are retained because wording varies."
      )
    ),
    add(
      "Pocket and structural thresholds",
      "Minimum structurally supported species fraction",
      threshold_help_text("structural_species_fraction"),
      "At least 0.75 (75%) of the 12 target species."
    ),
    add(
      "Pocket and structural thresholds", "Minimum member druggability score",
      threshold_help_text("minimum_druggability_score"),
      "At least 0.50 for the lowest-scoring assessed member."
    ),
    add(
      "Pocket and structural thresholds", "Conserved pocket-bearing sequence region",
      paste(
        "The selected pocket maps to sequence coordinates and the corresponding",
        "region is sufficiently conserved across assessed group members."
      ),
      "Mapping 0.95; pocket pLDDT 0.70; region overlap 0.25."
    ),
    add(
      "Pocket and structural thresholds", "Same 3D pocket position supported",
      paste(
        "After whole-structure superposition, selected pockets occupy a",
        "corresponding position by global similarity, centroid and overlap rules."
      ),
      "TM-score at least 0.50; centroid at most 8 Å; overlap at least 0.50."
    ),
    add(
      "Pocket and structural thresholds",
      "Strictly conserved corresponding 3D pocket",
      paste(
        "The rank-one pocket passes the same-position test and structurally",
        "matched residues pass residue and chemical conservation; group support",
        "and both structural aligners must support the conclusion."
      ),
      paste(
        "Residue match 0.50; chemical conservation 0.60; group support 0.75;",
        "residue distance at most 4 Å."
      )
    ),
    add("Result labels", "PASS", "Meets every currently selected app gate."),
    add("Result labels", "NEAR_MISS", "Fails exactly one selected app gate."),
    add("Result labels", "FAIL", "Fails two or more selected app gates."),
    add(
      "Result labels", "NOT_STRUCTURALLY_ASSESSED",
      paste(
        "Outside the 200-group structural cohort or lacking a required",
        "structural result; not classified as a structural failure."
      )
    )
  )
}
