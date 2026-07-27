#' Gene lookup UI.
#'
#' Creates a compact gene lookup panel.
#'
#' @param id Module identifier.
#' @return Shiny UI elements.
gene_lookup_ui <- function(id) {
  ns <- shiny::NS(id)

  shiny::tagList(
    shiny::textInput(ns("gene_query"), "Gene ID or gene name", value = ""),
    shiny::selectInput(ns("unit"), "Expression unit", choices = c("TPM", "FPKM"), selected = "TPM"),
    shiny::actionButton(ns("lookup"), "Lookup gene", class = "btn-secondary"),
    shinycssloaders::withSpinner(DT::DTOutput(ns("gene_table")))
  )
}

#' Gene lookup server.
#'
#' Performs a bounded cross-species gene lookup using direct DuckDB SQL. The
#' result is only collected after a user presses the lookup button.
#'
#' @param id Module identifier.
#' @param duckdb_path Path to the DuckDB database.
#' @param max_rows Maximum rows collected for display.
#' @return No return value.
gene_lookup_server <- function(id, duckdb_path, max_rows = 1000L) {
  shiny::moduleServer(id, function(input, output, session) {
    lookup_table <- shiny::eventReactive(input$lookup, {
      shiny::req(input$gene_query)

      tryCatch(
        expr = collect_duckdb_query(
          duckdb_path = duckdb_path,
          query = build_gene_lookup_query(
            gene_query = input$gene_query,
            expression_unit = input$unit,
            max_rows = max_rows
          )
        ),
        error = function(error) {
          shiny::showNotification(
            paste("Failed to run gene lookup:", conditionMessage(error)),
            type = "error",
            duration = NULL
          )
          tibble::tibble(error = conditionMessage(error))
        }
      )
    }, ignoreNULL = FALSE)

    output$gene_table <- DT::renderDT({
      DT::datatable(
        lookup_table(),
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
