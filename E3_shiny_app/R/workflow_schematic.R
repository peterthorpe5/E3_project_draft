#' End-to-end workflow schematic for the grant-facing reporter.

#' Return the ordered content used by the workflow schematic.
#'
#' @return Named list of stage specifications.
workflow_schematic_stages <- function() {
  list(
    inputs = list(
      stage = "Stages 00–01",
      title = "Controlled inputs and prepared proteomes",
      operation = paste(
        "Validate manifests and checksums, then create consistently named",
        "proteomes so discovery and OrthoFinder use the same species panel."
      ),
      output = "Provenance-bound, analysis-ready protein sequences.",
      phase = "preparation",
      optional = FALSE
    ),
    discovery = list(
      stage = "Stages 02–03",
      title = "E3-seeded sequence discovery",
      operation = paste(
        "Use reviewed and ubiquitin-associated seeds, tantan masking, DeepClust",
        "clustering and alignment reconciliation to expand the candidate set",
        "without declaring every cluster member to be an E3."
      ),
      output = "Stable DeepClust candidate and seed-evidence authority.",
      phase = "sequence",
      optional = FALSE
    ),
    orthofinder = list(
      stage = "Stage 04",
      title = "Independent evolutionary grouping",
      operation = paste(
        "Run or reuse OrthoFinder 2.5.5 on the same proteome panel to define",
        "orthogroups and hierarchical orthogroups independently of DeepClust."
      ),
      output = "Run-specific OrthoFinder group membership.",
      phase = "sequence",
      optional = FALSE
    ),
    orthology = list(
      stage = "Stage 05",
      title = "Candidate-to-orthology reconciliation",
      operation = paste(
        "Reconcile protein identifiers explicitly and map DeepClust candidates",
        "to primary OrthoFinder groups, members and target-species breadth."
      ),
      output = "Evolutionary groups with traceable member proteins.",
      phase = "sequence",
      optional = FALSE
    ),
    domains = list(
      stage = "Stage 06",
      title = "E3-associated domain evidence",
      operation = paste(
        "Collect Pfam and InterPro annotations and assess the fraction of",
        "domain-assessable species with a catalogued E3-associated domain."
      ),
      output = "Domain support, availability and gate fields.",
      phase = "biology",
      optional = FALSE
    ),
    expression = list(
      stage = "Stage 07",
      title = "Expression evidence",
      operation = paste(
        "Map members uniquely to Expression Atlas records and retain tissue",
        "context. Broad support uses the recorded median-TPM threshold of 0.5."
      ),
      output = "Expression support, mapping status and missingness.",
      phase = "biology",
      optional = FALSE
    ),
    shortlist = list(
      stage = "Stage 08",
      title = "Pre-structure prioritisation",
      operation = paste(
        "Apply mandatory discovery, orthology, domain and expression gates",
        "separately from the weighted pre-structure score."
      ),
      output = paste(
        "Traceable shortlist for computationally expensive structure work."
      ),
      phase = "integration",
      optional = FALSE
    ),
    ligandability = list(
      stage = "Stage 09",
      title = "Structures, pockets and pocket conservation",
      operation = paste(
        "Assess AlphaFold model confidence; define FPocket cavities; rescore",
        "those cavities with P2Rank; map lining residues; and measure",
        "druggability, predictor agreement and pocket-region conservation."
      ),
      output = paste(
        "Selected-pocket, residue, ligandability and conservation evidence."
      ),
      phase = "structure",
      optional = FALSE
    ),
    alignment = list(
      stage = "Stage 09b",
      title = "Three-dimensional pocket comparison",
      operation = paste(
        "Use US-align and TM-align, 3D pocket overlap and centroid distance to",
        "test whether selected pockets occupy comparable structural positions."
      ),
      output = "Strict rank-one 3D support plus separate sensitivity evidence.",
      phase = "structure",
      optional = FALSE
    ),
    chemistry = list(
      stage = "Stage 09c · optional",
      title = "Computational chemistry hand-off",
      operation = paste(
        "When enabled, derive residue-based pharmacophore features and optional",
        "open-fragment priorities without changing the recorded Milestone 1 rank."
      ),
      output = "Chemistry-ready evidence for later ligand investigation.",
      phase = "optional",
      optional = TRUE
    ),
    integration = list(
      stage = "Stage 10",
      title = "Integrated scoring, gates and consolidation",
      operation = paste(
        "Join all evidence; keep hard gates separate from continuous scores;",
        "order deterministically; and consolidate related DeepClust rows under",
        "one lead cluster per primary OrthoFinder group."
      ),
      output = paste(
        "Authoritative evolutionary-group prioritisation and audit trail."
      ),
      phase = "integration",
      optional = FALSE
    ),
    reporting = list(
      stage = "Stage 11",
      title = "App-ready computational recommendations",
      operation = paste(
        "Publish validated DuckDB, Parquet, TSV and Excel hand-offs for the R",
        "and Python evidence browsers."
      ),
      output = "Reviewable recommendations, evidence tables and provenance.",
      phase = "reporting",
      optional = FALSE
    )
  )
}

#' Render one workflow stage card.
#'
#' @param key Stable stage key.
#' @param stages Named stage specifications.
#' @return Shiny tag for the selected stage.
workflow_stage_card <- function(key, stages = workflow_schematic_stages()) {
  if (!is.character(key) || length(key) != 1L || !nzchar(key)) {
    stop("Workflow stage key must be one non-empty string.", call. = FALSE)
  }
  if (!key %in% names(stages)) {
    stop(paste0("Unknown workflow stage: ", key), call. = FALSE)
  }
  stage <- stages[[key]]
  classes <- c(
    "workflow-stage",
    paste0("workflow-phase-", stage$phase),
    if (isTRUE(stage$optional)) "workflow-stage-optional"
  )
  shiny::tags$section(
    class = paste(classes[nzchar(classes)], collapse = " "),
    shiny::div(class = "workflow-stage-id", stage$stage),
    shiny::h4(stage$title),
    shiny::p(stage$operation),
    shiny::p(
      class = "workflow-output",
      shiny::strong("Output: "),
      stage$output
    )
  )
}

#' Render the complete end-to-end workflow schematic.
#'
#' @return Shiny UI containing the method and evidence-dependency map.
workflow_schematic_ui <- function() {
  stages <- workflow_schematic_stages()
  card <- function(key) workflow_stage_card(key = key, stages = stages)
  arrow <- function() {
    shiny::div(class = "workflow-arrow", `aria-hidden` = "true", "↓")
  }
  merge_label <- function(text) {
    shiny::div(class = "workflow-merge-label", text)
  }
  shiny::tagList(
    shiny::h3("End-to-end method and evidence workflow"),
    shiny::p(
      class = "text-muted",
      paste(
        "Follow the arrows from controlled inputs to the app-ready computational",
        "recommendations. Parallel boxes show evidence streams generated",
        "independently before reconciliation."
      )
    ),
    shiny::div(
      class = "alert alert-info",
      paste(
        "The arrows represent computational dependencies and evidence integration,",
        "not proof of biological causality. Stage 09c is an optional chemistry",
        "hand-off and did not contribute to the recorded Milestone 1 ranking."
      )
    ),
    shiny::div(
      class = "e3-workflow",
      role = "figure",
      `aria-label` = "End-to-end ARIA plant E3 computational evidence workflow",
      card("inputs"),
      arrow(),
      shiny::div(
        class = "workflow-branch",
        shiny::div(class = "workflow-lane", card("discovery")),
        shiny::div(class = "workflow-lane", card("orthofinder"))
      ),
      merge_label("Candidate and OrthoFinder evidence reconciled"),
      arrow(),
      card("orthology"),
      arrow(),
      shiny::div(
        class = "workflow-branch",
        shiny::div(class = "workflow-lane", card("domains")),
        shiny::div(class = "workflow-lane", card("expression"))
      ),
      merge_label("Independent biological evidence combined"),
      arrow(),
      card("shortlist"),
      arrow(),
      card("ligandability"),
      arrow(),
      shiny::div(
        class = "workflow-branch",
        shiny::div(class = "workflow-lane", card("alignment")),
        shiny::div(class = "workflow-lane", card("chemistry"))
      ),
      merge_label("Recorded structural evidence and optional hand-off"),
      arrow(),
      card("integration"),
      arrow(),
      card("reporting"),
      shiny::div(
        class = "workflow-boundary",
        paste(
          "Computational prioritisation → structural, chemical and",
          "experimental validation"
        )
      )
    )
  )
}
