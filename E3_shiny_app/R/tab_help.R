#' Contextual operating help for every top-level application tab.

#' Build one contextual-help entry.
#'
#' @param instruction Concise instruction for using the tab.
#' @param yields Description of the content produced by the tab.
#' @return Named list containing both help paragraphs.
tab_help_detail <- function(instruction, yields) {
  if (
    length(instruction) != 1L || is.na(instruction) ||
      !nzchar(trimws(instruction)) ||
      length(yields) != 1L || is.na(yields) || !nzchar(trimws(yields))
  ) {
    stop("Tab help requires instruction and yield paragraphs.", call. = FALSE)
  }
  list(instruction = instruction, yields = yields)
}

#' Return structured help for all primary tabs.
#'
#' @return Named list keyed by exact user-facing tab label.
tab_help_details <- function() {
  detail <- tab_help_detail
  list(
    "Grant overview" = detail(
      paste(
        "Review release-wide counts and evidence scope first. Counts are",
        "computational groups, not experimentally validated E3 ligases."
      ),
      paste(
        "A compact summary of evolutionary-group counts, evidence coverage and",
        "key Milestone 1 and 2 outcomes in the currently loaded release."
      )
    ),
    "Workflow schematic" = detail(
      paste(
        "Follow controlled inputs through each evidence stage to reporting,",
        "using the arrows to distinguish dependencies and independent evidence."
      ),
      paste(
        "A stage-by-stage process map linking discovery, orthology, domains,",
        "expression, structures, pockets, conservation, ranking and reporting,",
        "including the main handoff files."
      )
    ),
    "Glossary" = detail(
      paste(
        "Choose a section or search the table for field, threshold and status",
        "definitions before interpreting or exporting results."
      ),
      paste(
        "Searchable definitions, recorded threshold values, missing-evidence",
        "states and field interpretations, with a downloadable glossary for use",
        "outside the app."
      )
    ),
    "Computational recommendations" = detail(
      paste(
        "Review recorded ranks, gate outcomes and exclusion reasons. Sensitivity",
        "controls never overwrite the authoritative recommendation."
      ),
      paste(
        "The authoritative recommendation table, an all-members druggability",
        "sensitivity analysis, full ranking formulas and an optional exploratory",
        "reweighting table with TSV and Excel downloads."
      )
    ),
    "Threshold explorer" = detail(
      paste(
        "Change documented gates only to create a sensitivity list, then compare",
        "the separate pre-structure and structurally informed results."
      ),
      paste(
        "Matched candidate tables labelled PASS, NEAR_MISS or FAIL under the",
        "active controls, with counts, reasons, HOG context and downloadable TSV",
        "and Excel files."
      )
    ),
    "Independent structural-review shortlist" = detail(
      paste(
        "Choose the top 200 to 500 HOGs from the recorded pre-structure evidence",
        "ranking. Existing pocket and structural results are deliberately excluded."
      ),
      paste(
        "An independent root-HOG review queue with pre-structure rank and pass",
        "status, candidate and seed context, species, domain and expression",
        "evidence, human, Arabidopsis, rice and barley representatives and table downloads."
      )
    ),
    "Visual explorer" = detail(
      paste(
        "Choose candidate metrics and a group to connect overview plots to exact",
        "candidate and expression evidence."
      ),
      paste(
        "Interactive candidate-landscape, expression and differential-expression",
        "views, a selected-group evidence table and reproducible PDF figures with",
        "supporting TSV or Excel downloads."
      )
    ),
    "Candidates" = detail(
      paste(
        "Select a candidate relation and the columns required for review,",
        "increasing the bounded row count before downloading when needed."
      ),
      paste(
        "A configurable preview of candidate-level source fields from the selected",
        "relation, with displayed rows available as TSV and formatted Excel."
      )
    ),
    "Orthology" = detail(
      paste(
        "Choose root HOGs or legacy orthogroups, then apply species, taxonomy,",
        "breadth and seed filters. Membership does not prove conserved function."
      ),
      paste(
        "OrthoFinder metrics, group-size plots, filtered HOG or OG summaries and",
        "member tables, plus a separate DeepClust and 1KP sequence-neighbourhood",
        "view with downloadable supporting data."
      )
    ),
    "Human HOGs" = detail(
      paste(
        "Load root HOGs containing human input, search identifiers or names and",
        "inspect human annotations alongside every other member."
      ),
      paste(
        "A one-row-per-HOG summary, matching human member records and complete",
        "cross-species membership for selected HOGs, with TSV, Excel and available",
        "FASTA downloads."
      )
    ),
    "Plant & human HOGs" = detail(
      paste(
        "Load HOGs containing human and a curated target plant, using member rows",
        "rather than the summary alone for exact species composition."
      ),
      paste(
        "A filtered HOG summary with ranking and human context, plus human members",
        "and all plant and non-plant co-members for the selected evolutionary",
        "groups and matching downloads."
      )
    ),
    "Seed & HOG explorer" = detail(
      paste(
        "Paste one or several E3 seeds, choose Any or All matching and inspect",
        "matching HOG members and sequences before downloading FASTA."
      ),
      paste(
        "A seed-to-group match summary, complete group-member table, associated",
        "evidence for a single selected group and downloadable protein FASTA where",
        "sequences are available."
      )
    ),
    "E3 seed catalogue" = detail(
      paste(
        "Search inherited known-E3 identifiers, names and source annotations,",
        "noting whether exact seed authority or a cluster-associated fallback is used."
      ),
      paste(
        "One searchable row per available seed record with source-scope provenance,",
        "associated annotations where necessary, TSV and Excel tables and exact",
        "accession-matched FASTA where available."
      )
    ),
    "Domains" = detail(
      paste(
        "Select summary or hit-level domain evidence. Keep assessed negatives",
        "separate from unavailable annotations when interpreting fractions."
      ),
      paste(
        "Group or member domain-support summaries and exact InterPro/Pfam hit rows,",
        "including catalogue matches, E3-family interpretation, availability",
        "states and downloadable source fields."
      )
    ),
    "Expression evidence" = detail(
      paste(
        "Filter species, tissue and identifiers. Median TPM is used where available;",
        "missing mappings remain unavailable rather than measured zero."
      ),
      paste(
        "Candidate-by-experiment-context expression rows, evidence-state fields,",
        "species and tissue filters, expression plots and supporting TSV, Excel or",
        "PDF downloads where the selected view provides them."
      )
    ),
    "Ligandability" = detail(
      paste(
        "Inspect retained pockets, predictor evidence and member druggability.",
        "Predicted pockets are computational starting points, not binding validation."
      ),
      paste(
        "Selected and ranked pocket tables with FPocket and P2Rank evidence,",
        "druggability, residue-mapping quality, pocket-local pLDDT and explicit",
        "pass or availability fields for each structural representative."
      )
    ),
    "Pocket conservation" = detail(
      paste(
        "Use summaries for group status and detailed rows for residues and sequence",
        "coordinates. Conserved sequence position differs from conserved 3D shape."
      ),
      paste(
        "Group pocket-region conservation summaries, member and residue mappings,",
        "aligned coordinate evidence, conservation scores and tables that trace a",
        "call back to the selected pocket residues."
      )
    ),
    "3D structures & pockets" = detail(
      paste(
        "Select a group and member, rotate the structure and inspect the mapped",
        "pocket location before downloading review evidence."
      ),
      paste(
        "Portable interactive C-alpha and pocket-residue views, selected-group and",
        "member summaries, downloadable review images where supported and links to",
        "the exact recorded structure and pocket evidence."
      )
    ),
    "Pocket-aligned sequences" = detail(
      paste(
        "Select a group to inspect its pocket-annotated alignment. Use aligned",
        "FASTA for alignment-aware downstream analysis."
      ),
      paste(
        "A portable alignment view highlighting selected pocket-associated residues,",
        "a member summary and the exact aligned protein FASTA used for pocket-region",
        "analysis."
      )
    ),
    "3D alignment" = detail(
      paste(
        "Select a relation and group for global and pocket-local comparisons.",
        "TM-scores and pocket overlap answer distinct structural questions."
      ),
      paste(
        "An interactive TM-score versus 3D pocket-overlap map, the exact plotted",
        "rows, group and pairwise alignment tables, local residue evidence and a",
        "vector PDF of the summary plot."
      )
    ),
    "Computational chemistry" = detail(
      paste(
        "Review readiness, pharmacophore features and method status. A blank or",
        "NOT_RUN method is not evidence that a chemistry criterion failed."
      ),
      paste(
        "Available group readiness summaries, residue-derived pharmacophore feature",
        "rows, method execution states and handoff fields prepared for computational",
        "chemistry review."
      )
    ),
    "Search" = detail(
      paste(
        "Paste HOG IDs, seeds, accessions or names. Smart search reports every",
        "matching relation and column, so one term may return several rows."
      ),
      paste(
        "A term-level match summary and bounded exact source rows carrying the",
        "matched value, relation and field provenance, with downloadable summary",
        "and result tables."
      )
    ),
    "All results" = detail(
      paste(
        "Use the enriched HOG overview for one row per HOG, member detail for every",
        "member and raw relations for exact source-level audit."
      ),
      paste(
        "Joined HOG overview and member-detail views containing rankings, human and",
        "Arabidopsis, rice and barley representatives, membership and species context, plus every raw",
        "DuckDB relation under bounded preview and download controls."
      )
    ),
    "Provenance and QC" = detail(
      paste(
        "Inspect release identifiers, source files, checksums and validation",
        "outcomes before citing or transferring results. Investigate failed QC."
      ),
      paste(
        "Run, source-manifest, software-version, checksum, validation and",
        "quality-control tables identifying the producing stage and evidence state",
        "behind scientific outputs."
      )
    ),
    "Files used" = detail(
      paste(
        "Review configured source paths and discovered files to confirm that the",
        "intended release is loaded. Paths are provenance, not biological evidence."
      ),
      paste(
        "A source-file inventory and configured-path report showing which DuckDB,",
        "Parquet, tabular, FASTA and review assets were discovered for the running app."
      )
    ),
    "About" = detail(
      paste(
        "Use this page for application scope, configured paths and interpretation",
        "boundaries. All outputs remain computational recommendations."
      ),
      paste(
        "A concise description of the reporter, the relationship between the",
        "integrated DuckDB and candidate-level Parquet and the active configured",
        "resource paths."
      )
    )
  )
}

#' Return formatted help for every primary tab.
#'
#' @return Named character vector keyed by user-facing tab label.
tab_help_entries <- function() {
  details <- tab_help_details()
  vapply(details, function(entry) {
    paste(
      entry$instruction,
      "What this tab yields:",
      entry$yields,
      sep = "\n\n"
    )
  }, character(1))
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
  details <- tab_help_details()
  if (
    length(tab_name) != 1L || is.na(tab_name) ||
      !tab_name %in% names(details)
  ) {
    stop("No contextual help is defined for this tab.", call. = FALSE)
  }
  entry <- details[[tab_name]]
  shiny::tags$details(
    class = "e3-tab-help",
    shiny::tags$summary("❓ How to use this tab"),
    shiny::p(entry$instruction),
    shiny::p(
      class = "e3-tab-yield",
      shiny::strong("What this tab yields: "),
      entry$yields
    )
  )
}
