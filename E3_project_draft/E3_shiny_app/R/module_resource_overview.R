#' Resource overview UI.
#'
#' @param id Module identifier.
#' @return Shiny UI.
resource_overview_ui <- function(id) {
  ns <- shiny::NS(id)

  shiny::tagList(
    shiny::h3("Source-first E3 PROTAC resource"),
    shiny::p(
      "This tab shows the DuckDB views created from the curated source-first ",
      "Parquet rebuild. It is intentionally generic at this stage: it lets us ",
      "inspect all available source-derived tables before we freeze the final ",
      "biological schema."
    ),
    bslib::layout_columns(
      bslib::value_box("Resource views", shiny::textOutput(ns("view_count"))),
      bslib::value_box("Created views", shiny::textOutput(ns("created_count"))),
      bslib::value_box("Failed views", shiny::textOutput(ns("failed_count")))
    ),
    shiny::h4("View catalog"),
    shinycssloaders::withSpinner(DT::DTOutput(ns("view_catalog"))),
    shiny::h4("Status summary"),
    DT::DTOutput(ns("status_summary"))
  )
}

#' Resource overview server.
#'
#' @param id Module identifier.
#' @param resource_duckdb_path Path to resource DuckDB database.
#' @return No return value.
resource_overview_server <- function(id, resource_duckdb_path) {
  shiny::moduleServer(id, function(input, output, session) {
    catalog <- shiny::reactive({
      if (!resource_database_available(resource_duckdb_path)) {
        return(tibble::tibble(
          view_name = character(),
          parquet_file = character(),
          status = character(),
          error = character()
        ))
      }

      tryCatch(
        expr = collect_resource_view_catalog(duckdb_path = resource_duckdb_path),
        error = function(error) {
          shiny::showNotification(
            paste("Failed to read resource catalog:", conditionMessage(error)),
            type = "error",
            duration = NULL
          )
          tibble::tibble(
            view_name = character(),
            parquet_file = character(),
            status = character(),
            error = character()
          )
        }
      )
    })

    output$view_count <- shiny::renderText({
      format_summary_count(nrow(catalog()))
    })

    output$created_count <- shiny::renderText({
      current <- catalog()
      if (!"status" %in% names(current)) {
        return("0")
      }
      format_summary_count(sum(current$status %in% c("created", "available"), na.rm = TRUE))
    })

    output$failed_count <- shiny::renderText({
      current <- catalog()
      if (!"status" %in% names(current)) {
        return("0")
      }
      format_summary_count(sum(current$status == "failed", na.rm = TRUE))
    })

    output$view_catalog <- DT::renderDT({
      DT::datatable(
        catalog(),
        rownames = FALSE,
        filter = "top",
        options = list(pageLength = 25, scrollX = TRUE, deferRender = TRUE)
      )
    })

    output$status_summary <- DT::renderDT({
      DT::datatable(
        summarise_resource_catalog_status(catalog()),
        rownames = FALSE,
        options = list(dom = "t", paging = FALSE)
      )
    })
  })
}
