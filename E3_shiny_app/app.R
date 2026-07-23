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
source("R/data_source_report.R")
source("R/result_sections.R")
source("R/resource_source.R")
source("R/app_config.R")
source("R/data_sources.R")
source("R/query_helpers.R")
source("R/resource_helpers.R")
source("R/module_expression_filters.R")
source("R/module_expression_summary.R")
source("R/module_expression_table.R")
source("R/module_gene_lookup.R")
source("R/module_expression_plots.R")
source("R/module_resource_overview.R")
source("R/module_resource_browser.R")
source("R/module_data_sources.R")
source("R/module_grant_overview.R")
source("R/module_result_section.R")

# Configuration can come from command-line arguments, environment variables, or
# defaults. See README.md for the supported options.
app_config <- get_app_config(args = commandArgs(trailingOnly = TRUE))

ui <- bslib::page_sidebar(
  title = "ARIA Plant E3 Evidence Reporter",
  theme = bslib::bs_theme(version = 5, bootswatch = "flatly"),
  sidebar = bslib::sidebar(
    shiny::h4("Data release"),
    shiny::p(
      class = "small",
      paste0(
        "Mode: ", app_config$resource_source$mode,
        "\nSource: ", app_config$resource_source$path
      )
    ),
    shiny::hr(),
    shiny::h4("Raw Expression Atlas filters"),
    shiny::p(
      class = "small text-muted",
      "These apply only to the four raw Expression Atlas tabs. Integrated ",
      "candidate-expression evidence has its own grant-facing section."
    ),
    expression_filters_ui("filters"),
    width = 380
  ),
  shiny::includeCSS("www/app.css"),
  bslib::navset_card_tab(
    bslib::nav_panel(
      "Grant overview",
      grant_overview_ui("grant_overview")
    ),
    bslib::nav_panel(
      "Candidates",
      result_section_ui("candidate_results", "candidates")
    ),
    bslib::nav_panel(
      "Orthology",
      result_section_ui("orthology_results", "orthology")
    ),
    bslib::nav_panel(
      "Domains",
      result_section_ui("domain_results", "domains")
    ),
    bslib::nav_panel(
      "Expression evidence",
      result_section_ui("expression_results", "expression")
    ),
    bslib::nav_panel(
      "Ligandability",
      result_section_ui("ligandability_results", "ligandability")
    ),
    bslib::nav_panel(
      "Pocket conservation",
      result_section_ui("pocket_results", "pocket_conservation")
    ),
    bslib::nav_panel(
      "3D alignment",
      result_section_ui("alignment_results", "structural_alignment")
    ),
    bslib::nav_panel(
      "All results",
      resource_browser_ui("resource_browser")
    ),
    bslib::nav_panel(
      "Provenance and QC",
      result_section_ui("provenance_results", "provenance")
    ),
    bslib::nav_panel(
      "Files used",
      data_sources_ui("data_sources")
    ),
    bslib::nav_panel(
      "Expression summary",
      expression_summary_ui("summary")
    ),
    bslib::nav_panel(
      "Expression table",
      expression_table_ui("table")
    ),
    bslib::nav_panel(
      "Gene lookup",
      gene_lookup_ui("gene_lookup")
    ),
    bslib::nav_panel(
      "Visualise expression",
      expression_plot_ui("expression_plot")
    ),
    bslib::nav_panel(
      "About",
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
)

server <- function(input, output, session) {
  grant_overview_server(
    id = "grant_overview",
    resource_source = app_config$resource_source
  )

  result_section_server(
    "candidate_results",
    "candidates",
    app_config$resource_source,
    app_config$max_table_rows
  )
  result_section_server(
    "orthology_results",
    "orthology",
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

  # Filters are collected as ordinary scalar values. Summary, table, and gene
  # lookup modules turn those values into SQL and let DuckDB do the heavy work.
  filters <- expression_filters_server(
    id = "filters",
    duckdb_path = app_config$expression_duckdb_path,
    default_expression_unit = app_config$default_expression_unit
  )

  expression_summary_server(
    id = "summary",
    duckdb_path = app_config$expression_duckdb_path,
    filters = filters
  )

  expression_table_server(
    id = "table",
    duckdb_path = app_config$expression_duckdb_path,
    filters = filters,
    max_rows = app_config$max_table_rows
  )

  gene_lookup_server(
    id = "gene_lookup",
    duckdb_path = app_config$expression_duckdb_path,
    max_rows = app_config$max_table_rows
  )

  expression_plot_server(
    id = "expression_plot",
    duckdb_path = app_config$expression_duckdb_path,
    filters = filters,
    default_max_rows = min(app_config$max_table_rows, 5000L)
  )

  output$configured_paths <- shiny::renderText({
    paste(
      "Resource DuckDB:", app_config$resource_duckdb_path,
      "\nResource master Parquet:", app_config$resource_parquet_path,
      "\nResource run directory:", app_config$resource_run_dir,
      "\nResolved resource mode:", app_config$resource_source$mode,
      "\nResource derived dir:", app_config$resource_derived_dir,
      "\nExpression DuckDB:", app_config$expression_duckdb_path,
      "\nMax display rows:", app_config$max_table_rows,
      sep = ""
    )
  })
}

shiny::shinyApp(ui = ui, server = server)
