#' Expression table UI.
#'
#' Creates the filtered expression table panel. Only a bounded number of rows is
#' collected for display.
#'
#' @param id Module identifier.
#' @return Shiny UI elements.
expression_table_ui <- function(id) {
  ns <- shiny::NS(id)

  shiny::tagList(
    shiny::p(
      "The table is row-limited for display. Filters are applied in DuckDB before data are collected."
    ),
    shinycssloaders::withSpinner(DT::DTOutput(ns("expression_table")))
  )
}

#' Expression table server.
#'
#' Collects a limited number of filtered rows for display using direct DuckDB
#' SQL. This avoids materialising the large joined expression view in R.
#'
#' @param id Module identifier.
#' @param duckdb_path Path to the DuckDB database.
#' @param filters Reactive returning the current filter list.
#' @param max_rows Maximum rows collected for display.
#' @return No return value.
expression_table_server <- function(id, duckdb_path, filters, max_rows = 1000L) {
  shiny::moduleServer(id, function(input, output, session) {
    output$expression_table <- DT::renderDT({
      display_table <- tryCatch(
        expr = collect_expression_display_sql(
          duckdb_path = duckdb_path,
          filters = filters(),
          max_rows = max_rows
        ),
        error = function(error) {
          shiny::showNotification(
            paste("Failed to collect expression table:", conditionMessage(error)),
            type = "error",
            duration = NULL
          )
          tibble::tibble(error = conditionMessage(error))
        }
      )

      DT::datatable(
        display_table,
        rownames = FALSE,
        filter = "top",
        options = list(
          pageLength = 25,
          scrollX = TRUE,
          deferRender = TRUE
        )
      )
    })
  })
}
