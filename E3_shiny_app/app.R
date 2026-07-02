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

# Configuration can come from command-line arguments, environment variables, or
# defaults. See README.md for the supported options.
app_config <- get_app_config(args = commandArgs(trailingOnly = TRUE))

ui <- bslib::page_sidebar(
  title = "E3 PROTAC Resource Explorer",
  theme = bslib::bs_theme(version = 5, bootswatch = "flatly"),
  sidebar = bslib::sidebar(
    shiny::h4("Expression filters"),
    shiny::p(
      class = "small text-muted",
      "These filters apply only to the Expression Atlas tabs. The resource ",
      "browser tabs inspect the source-first E3 Parquet/DuckDB layer directly."
    ),
    expression_filters_ui("filters"),
    width = 380
  ),
  shiny::includeCSS("www/app.css"),
  bslib::navset_card_tab(
    bslib::nav_panel(
      "Resource overview",
      resource_overview_ui("resource_overview")
    ),
    bslib::nav_panel(
      "Browse resource tables",
      resource_browser_ui("resource_browser")
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
        "This app now has two layers. The first is the source-first E3 PROTAC ",
        "Parquet/DuckDB resource generated from the curated inherited files. ",
        "The second is the Expression Atlas DuckDB produced by the separate ",
        "expression-downloader pipeline."
      ),
      shiny::p(
        "The source-first layer is intentionally provenance-heavy. It exposes ",
        "all copied and converted inputs, including tabular files, FASTA-derived ",
        "tables, preserved SQL/text files, and inherited Parquet outputs."
      ),
      shiny::p(
        "The next biological layer should add curated views such as protein ",
        "records, sequence records, literature evidence, GO evidence, ",
        "ligandability scores, and later Orthofinder/HOG membership."
      ),
      shiny::h4("Configured paths"),
      shiny::verbatimTextOutput("configured_paths")
    )
  )
)

server <- function(input, output, session) {
  resource_overview_server(
    id = "resource_overview",
    resource_duckdb_path = app_config$resource_duckdb_path
  )

  resource_browser_server(
    id = "resource_browser",
    resource_duckdb_path = app_config$resource_duckdb_path
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
      "\nResource derived dir:", app_config$resource_derived_dir,
      "\nExpression DuckDB:", app_config$expression_duckdb_path,
      "\nMax display rows:", app_config$max_table_rows,
      sep = ""
    )
  })
}

shiny::shinyApp(ui = ui, server = server)
