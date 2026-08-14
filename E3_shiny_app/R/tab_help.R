#' Contextual question-mark help for every top-level application tab.

tab_help_entries <- function() {
  c(
    "Grant overview" = paste(
      "Review release-wide counts and evidence scope first.",
      "Counts are computational groups, not experimentally validated E3 ligases."
    ),
    "Workflow schematic" = paste(
      "Follow controlled inputs through each evidence stage to reporting.",
      "Use the arrows to identify dependencies and independently generated evidence."
    ),
    "Glossary" = paste(
      "Choose a section or search the table for field, threshold and status",
      "definitions. Download it when interpreting results outside the app."
    ),
    "Computational recommendations" = paste(
      "Review recorded ranks, gate outcomes and exclusion reasons.",
      "Sensitivity controls never overwrite the authoritative recommendation."
    ),
    "Threshold explorer" = paste(
      "Change documented gates to create sensitivity lists, then compare the",
      "separate pre-structure and structurally informed tables and downloads."
    ),
    "Pre-structure ranked HOGs" = paste(
      "Choose how many HOGs to return. The recorded pre-structure HOG rank is",
      "used directly without biological, pocket, druggability or structural gates."
    ),
    "Visual explorer" = paste(
      "Choose candidate metrics and a group to connect overview plots to exact",
      "candidate and expression evidence. Download PDFs or supporting table rows."
    ),
    "Candidates" = paste(
      "Select a candidate relation and the columns required for review.",
      "Increase the bounded row count before downloading when needed."
    ),
    "Orthology" = paste(
      "Choose root HOGs or legacy orthogroups, then apply species, taxonomy,",
      "breadth and seed filters. Membership does not prove conserved function."
    ),
    "Human HOGs" = paste(
      "Load root HOGs containing human input, search identifiers or names,",
      "and inspect human annotations alongside every other member."
    ),
    "Plant & human HOGs" = paste(
      "Load HOGs containing human and a curated target plant.",
      "Use the summary for ranking and member rows for exact species composition."
    ),
    "Seed & HOG explorer" = paste(
      "Paste one or several E3 seeds, choose Any or All matching, and inspect",
      "matching HOG members and sequences before downloading FASTA."
    ),
    "Domains" = paste(
      "Select summary or hit-level domain evidence. Keep assessed negatives",
      "separate from unavailable annotations when interpreting fractions."
    ),
    "Expression evidence" = paste(
      "Filter species, tissue and identifiers. Median TPM is used where available;",
      "missing mappings are unavailable evidence rather than measured zero."
    ),
    "Ligandability" = paste(
      "Inspect retained pockets, predictor evidence and member druggability.",
      "Predicted pockets are computational starting points, not binding validation."
    ),
    "Pocket conservation" = paste(
      "Use summaries for group status and detailed rows for residues and sequence",
      "coordinates. Conserved sequence position differs from conserved 3D shape."
    ),
    "3D structures & pockets" = paste(
      "Select a group and member, rotate the structure and inspect pocket surfaces.",
      "Use the controls to download review images and exact supporting evidence."
    ),
    "Pocket-aligned sequences" = paste(
      "Select a group to inspect its pocket-annotated alignment.",
      "Download aligned FASTA for alignment-aware downstream analysis."
    ),
    "3D alignment" = paste(
      "Select a relation and group for global and pocket-local comparisons.",
      "TM-scores and pocket overlap answer distinct structural questions."
    ),
    "Computational chemistry" = paste(
      "Review readiness, pharmacophore features and method status.",
      "A blank or NOT_RUN method is not evidence that a chemistry criterion failed."
    ),
    "Search" = paste(
      "Paste HOG IDs, seeds, accessions or names. Smart search reports every",
      "matching relation and column, so one term may return several rows."
    ),
    "All results" = paste(
      "Choose any loaded relation for schema-level audit and select columns",
      "before previewing. Downloads contain only the bounded requested rows."
    ),
    "Provenance and QC" = paste(
      "Inspect release identifiers, source files, checksums and validation",
      "outcomes before citing or transferring results. Investigate failed QC."
    ),
    "Files used" = paste(
      "Review configured source paths and discovered files to confirm that the",
      "intended release is loaded. Paths are provenance, not biological evidence."
    ),
    "About" = paste(
      "Use this page for the application scope, configured paths and interpretation",
      "boundary. All outputs remain computational recommendations."
    )
  )
}

#' Return help for one maintained tab.
#'
#' @param tab_name Exact user-facing tab label.
#' @return Contextual help text.
tab_help_text <- function(tab_name) {
  entries <- tab_help_entries()
  if (
    length(tab_name) != 1L || is.na(tab_name) ||
      !tab_name %in% names(entries)
  ) {
    stop("No contextual help is defined for this tab.", call. = FALSE)
  }
  unname(entries[[tab_name]])
}

#' Build a collapsed question-mark help box.
#'
#' @param tab_name Exact user-facing tab label.
#' @return HTML details element.
tab_help_ui <- function(tab_name) {
  shiny::tags$details(
    class = "e3-tab-help",
    shiny::tags$summary("❓ How to use this tab"),
    shiny::p(tab_help_text(tab_name = tab_name))
  )
}
