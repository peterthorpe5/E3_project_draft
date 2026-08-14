# Standalone Shiny app entry point.
#
# This app is deliberately thin: large data access is pushed through DuckDB
# views, filters are applied lazily where possible, and only bounded result
# tables are collected for display. Keep it this way as new project modules are
# added; the app should orchestrate queries rather than perform heavy imports.

library(bslib)
library(dplyr)
library(DT)
library(duckplyr)
library(shiny)
library(shinycssloaders)
library(stringr)

source("R/utils.R")
source("R/excel_export.R")
source("R/fasta_export.R")
source("R/plot_pdf_export.R")
source("R/data_source_report.R")
source("R/result_sections.R")
source("R/resource_source.R")
source("R/app_config.R")
source("R/data_sources.R")
source("R/query_helpers.R")
source("R/resource_helpers.R")
source("R/glossary.R")
source("R/ranking_explorer.R")
source("R/threshold_explorer.R")
source("R/druggability_visualisations.R")
source("R/candidate_visualisations.R")
source("R/structural_alignment_visualisations.R")
source("R/workflow_schematic.R")
source("R/pocket_review.R")
source("R/orthology_explorer.R")
source("R/deepclust_explorer.R")
source("R/human_hog_explorer.R")
source("R/prestructure_hog_explorer.R")
source("R/unified_search.R")
source("R/tab_help.R")
source("R/module_resource_overview.R")
source("R/module_resource_browser.R")
source("R/module_data_sources.R")
source("R/module_grant_overview.R")
source("R/module_glossary.R")
source("R/module_result_section.R")
source("R/module_threshold_explorer.R")
source("R/module_candidate_visualisations.R")
source("R/module_pocket_review.R")
source("R/module_deepclust_explorer.R")
source("R/module_orthology_explorer.R")
source("R/module_human_hog_explorer.R")
source("R/module_prestructure_hog_explorer.R")
source("R/module_unified_search.R")

# Configuration can come from command-line arguments, environment variables, or
# defaults. See README.md for the supported options.
app_config <- get_app_config(args = commandArgs(trailingOnly = TRUE))
pocket_review_config <- prepare_pocket_review(
  explicit_dir = app_config$pocket_review_dir,
  resource_source = app_config$resource_source
)
pocket_review_config <- register_pocket_review_resource(pocket_review_config)

ui <- bslib::page_navbar(
  title = "ARIA Plant E3 Evidence Reporter",
  id = "main_navigation",
  theme = bslib::bs_theme(version = 5, bootswatch = "flatly"),
  header = shiny::includeCSS("www/app.css"),
    bslib::nav_panel(
      "Grant overview",
      tab_help_ui(tab_name = "Grant overview"),
      grant_overview_ui("grant_overview")
    ),
    bslib::nav_panel(
      "Workflow schematic",
      tab_help_ui(tab_name = "Workflow schematic"),
      workflow_schematic_ui()
    ),
    bslib::nav_panel(
      "Glossary",
      tab_help_ui(tab_name = "Glossary"),
      glossary_ui("glossary")
    ),
    bslib::nav_panel(
      "Computational recommendations",
      tab_help_ui(tab_name = "Computational recommendations"),
      result_section_ui("final_recommendation_results", "final_recommendations")
    ),
    bslib::nav_panel(
      "Threshold explorer",
      tab_help_ui(tab_name = "Threshold explorer"),
      threshold_explorer_ui("threshold_explorer")
    ),
    bslib::nav_panel(
      "Pre-structure ranked HOGs",
      tab_help_ui(tab_name = "Pre-structure ranked HOGs"),
      prestructure_hog_explorer_ui(id = "prestructure_ranked_hogs")
    ),
    bslib::nav_panel(
      "Visual explorer",
      tab_help_ui(tab_name = "Visual explorer"),
      candidate_visualisations_ui("candidate_visualisations")
    ),
    bslib::nav_panel(
      "Candidates",
      tab_help_ui(tab_name = "Candidates"),
      result_section_ui("candidate_results", "candidates")
    ),
    bslib::nav_panel(
      "Orthology",
      tab_help_ui(tab_name = "Orthology"),
      orthology_explorer_ui("orthology_explorer")
    ),
    bslib::nav_panel(
      "Human HOGs",
      tab_help_ui(tab_name = "Human HOGs"),
      human_hog_explorer_ui(
        "human_hogs",
        plant_required = FALSE
      )
    ),
    bslib::nav_panel(
      "Plant & human HOGs",
      tab_help_ui(tab_name = "Plant & human HOGs"),
      human_hog_explorer_ui(
        "plant_and_human_hogs",
        plant_required = TRUE
      )
    ),
    bslib::nav_panel(
      "Seed & HOG explorer",
      tab_help_ui(tab_name = "Seed & HOG explorer"),
      seed_group_explorer_ui("seed_group_explorer")
    ),
    bslib::nav_panel(
      "Domains",
      tab_help_ui(tab_name = "Domains"),
      result_section_ui("domain_results", "domains")
    ),
    bslib::nav_panel(
      "Expression evidence",
      tab_help_ui(tab_name = "Expression evidence"),
      result_section_ui("expression_results", "expression")
    ),
    bslib::nav_panel(
      "Ligandability",
      tab_help_ui(tab_name = "Ligandability"),
      result_section_ui("ligandability_results", "ligandability")
    ),
    bslib::nav_panel(
      "Pocket conservation",
      tab_help_ui(tab_name = "Pocket conservation"),
      result_section_ui("pocket_results", "pocket_conservation")
    ),
    bslib::nav_panel(
      "3D structures & pockets",
      tab_help_ui(tab_name = "3D structures & pockets"),
      pocket_review_ui("structure_review", focus = "structure")
    ),
    bslib::nav_panel(
      "Pocket-aligned sequences",
      tab_help_ui(tab_name = "Pocket-aligned sequences"),
      pocket_review_ui("alignment_review", focus = "alignment")
    ),
    bslib::nav_panel(
      "3D alignment",
      tab_help_ui(tab_name = "3D alignment"),
      result_section_ui("alignment_results", "structural_alignment")
    ),
    bslib::nav_panel(
      "Computational chemistry",
      tab_help_ui(tab_name = "Computational chemistry"),
      result_section_ui("chemistry_results", "computational_chemistry")
    ),
    bslib::nav_panel(
      "Search",
      tab_help_ui(tab_name = "Search"),
      unified_search_ui("unified_search")
    ),
    bslib::nav_panel(
      "All results",
      tab_help_ui(tab_name = "All results"),
      resource_browser_ui("resource_browser")
    ),
    bslib::nav_panel(
      "Provenance and QC",
      tab_help_ui(tab_name = "Provenance and QC"),
      result_section_ui("provenance_results", "provenance")
    ),
    bslib::nav_panel(
      "Files used",
      tab_help_ui(tab_name = "Files used"),
      data_sources_ui("data_sources")
    ),
    bslib::nav_panel(
      "About",
      tab_help_ui(tab_name = "About"),
      shiny::h3("About this app"),
      shiny::p(
        "This reporter answers the grant-facing questions across candidate ",
        "discovery, OrthoFinder groups, domains, expression, ligandability and ",
        "pocket conservation. It can use an integrated DuckDB, one candidate ",
        "master Parquet or the current set of workflow-stage Parquets."
      ),
      shiny::p(
        "Detailed one-to-many evidence remains available in normalised relations. ",
        "The single master Parquet is the convenient candidate-level hand-off; it ",
        "does not discard group members, pockets or residue mappings from DuckDB."
      ),
      shiny::p(
        "All results are computational. They do not establish E3 activity, ",
        "compound binding or induced degradation."
      ),
      shiny::h4("Configured paths"),
      shiny::verbatimTextOutput("configured_paths")
    )
)

server <- function(input, output, session) {
  glossary_server(id = "glossary")
  grant_overview_server(
    id = "grant_overview",
    resource_source = app_config$resource_source
  )
  threshold_explorer_server(
    id = "threshold_explorer",
    resource_source = app_config$resource_source,
    max_rows = app_config$max_table_rows
  )
  prestructure_hog_explorer_server(
    id = "prestructure_ranked_hogs",
    resource_source = app_config$resource_source,
    max_rows = app_config$max_table_rows
  )
  candidate_visualisations_server(
    id = "candidate_visualisations",
    resource_source = app_config$resource_source,
    max_rows = app_config$max_table_rows
  )
  orthology_explorer_server(
    id = "orthology_explorer",
    resource_source = app_config$resource_source,
    max_rows = app_config$max_table_rows
  )
  human_hog_explorer_server(
    id = "human_hogs",
    resource_source = app_config$resource_source,
    max_rows = app_config$max_table_rows,
    plant_required = FALSE
  )
  human_hog_explorer_server(
    id = "plant_and_human_hogs",
    resource_source = app_config$resource_source,
    max_rows = app_config$max_table_rows,
    plant_required = TRUE
  )
  seed_group_explorer_server(
    id = "seed_group_explorer",
    resource_source = app_config$resource_source,
    max_rows = app_config$max_table_rows
  )
  unified_search_server(
    id = "unified_search",
    resource_source = app_config$resource_source,
    max_rows = app_config$max_table_rows
  )
  pocket_review_server(
    id = "structure_review",
    review_config = pocket_review_config,
    focus = "structure"
  )
  pocket_review_server(
    id = "alignment_review",
    review_config = pocket_review_config,
    focus = "alignment"
  )

  result_section_server(
    "final_recommendation_results",
    "final_recommendations",
    app_config$resource_source,
    app_config$max_table_rows
  )
  result_section_server(
    "candidate_results",
    "candidates",
    app_config$resource_source,
    app_config$max_table_rows
  )
  result_section_server(
    "domain_results",
    "domains",
    app_config$resource_source,
    app_config$max_table_rows
  )
  result_section_server(
    "expression_results",
    "expression",
    app_config$resource_source,
    app_config$max_table_rows
  )
  result_section_server(
    "ligandability_results",
    "ligandability",
    app_config$resource_source,
    app_config$max_table_rows
  )
  result_section_server(
    "pocket_results",
    "pocket_conservation",
    app_config$resource_source,
    app_config$max_table_rows
  )
  result_section_server(
    "alignment_results",
    "structural_alignment",
    app_config$resource_source,
    app_config$max_table_rows
  )
  result_section_server(
    "chemistry_results",
    "computational_chemistry",
    app_config$resource_source,
    app_config$max_table_rows
  )
  result_section_server(
    "provenance_results",
    "provenance",
    app_config$resource_source,
    app_config$max_table_rows
  )
  resource_browser_server(
    id = "resource_browser",
    resource_duckdb_path = app_config$resource_source
  )

  data_sources_server(
    id = "data_sources",
    resource_derived_dir = app_config$resource_derived_dir
  )

  output$configured_paths <- shiny::renderText({
    paste(
      "Resource DuckDB:", app_config$resource_duckdb_path,
      "\nResource master Parquet:", app_config$resource_parquet_path,
      "\nResource run directory:", app_config$resource_run_dir,
      "\nResolved resource mode:", app_config$resource_source$mode,
      "\nResource derived dir:", app_config$resource_derived_dir,
      "\nPocket-review bundle:", pocket_review_config$path,
      "\nPocket-review available:", pocket_review_config$available,
      "\nExpression DuckDB:", app_config$expression_duckdb_path,
      "\nMax display rows:", app_config$max_table_rows,
      sep = ""
    )
  })
}

shiny::shinyApp(ui = ui, server = server)
