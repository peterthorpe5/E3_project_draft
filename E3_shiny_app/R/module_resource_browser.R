#' Resource browser UI.
#'
#' @param id Module identifier.
#' @return Shiny UI.
resource_browser_ui <- function(id) {
  ns <- shiny::NS(id)

  shiny::tagList(
    shiny::h3("Browse source-derived tables"),
    shiny::p(
      "Choose any DuckDB view created from the source-first Parquet layer. ",
      "Only a bounded preview is collected into R."
    ),
    bslib::layout_columns(
      shiny::selectInput(ns("view_name"), "DuckDB view", choices = "Loading..."),
      shiny::numericInput(ns("max_rows"), "Preview rows", value = 1000, min = 1, max = 10000),
      shiny::actionButton(ns("refresh"), "Refresh views"),
      shiny::actionButton(ns("preview"), "Preview table", class = "btn-primary")
    ),
    shiny::h4("Columns"),
    DT::DTOutput(ns("columns")),
    shiny::h4("Table preview"),
    shinycssloaders::withSpinner(DT::DTOutput(ns("preview_table")))
  )
}

#' Resource browser server.
#'
#' @param id Module identifier.
#' @param resource_duckdb_path Path to resource DuckDB database.
#' @return No return value.
resource_browser_server <- function(id, resource_duckdb_path) {
  shiny::moduleServer(id, function(input, output, session) {
    view_names <- shiny::reactiveVal(character())

    load_view_names <- function() {
      if (!resource_database_available(resource_duckdb_path)) {
        shiny::updateSelectInput(session, "view_name", choices = "Resource DB not configured")
        view_names(character())
        return(invisible(character()))
      }

      names <- tryCatch(
        expr = collect_resource_view_names(duckdb_path = resource_duckdb_path),
        error = function(error) {
          shiny::showNotification(
            paste("Failed to list resource views:", conditionMessage(error)),
            type = "error",
            duration = NULL
          )
          character()
        }
      )

      if (length(names) == 0L) {
        names <- "No views found"
      }

      view_names(names)
      shiny::updateSelectInput(session, "view_name", choices = names, selected = names[[1L]])
      invisible(names)
    }

    shiny::observeEvent(TRUE, load_view_names(), once = TRUE)
    shiny::observeEvent(input$refresh, load_view_names())

    output$columns <- DT::renderDT({
      shiny::req(input$view_name)
      if (input$view_name %in% c("Loading...", "No views found", "Resource DB not configured")) {
        return(DT::datatable(tibble::tibble(message = "No resource view selected."), rownames = FALSE))
      }

      columns <- tryCatch(
        expr = collect_resource_columns(
          duckdb_path = resource_duckdb_path,
          view_name = input$view_name
        ),
        error = function(error) tibble::tibble(error = conditionMessage(error))
      )

      DT::datatable(
        columns,
        rownames = FALSE,
        options = list(pageLength = 25, scrollX = TRUE)
      )
    })

    preview_data <- shiny::eventReactive(input$preview, {
      shiny::req(input$view_name)
      if (input$view_name %in% c("Loading...", "No views found", "Resource DB not configured")) {
        return(tibble::tibble(message = "No resource view selected."))
      }

      tryCatch(
        expr = collect_resource_preview(
          duckdb_path = resource_duckdb_path,
          view_name = input$view_name,
          max_rows = input$max_rows
        ),
        error = function(error) {
          shiny::showNotification(
            paste("Failed to preview resource view:", conditionMessage(error)),
            type = "error",
            duration = NULL
          )
          tibble::tibble(error = conditionMessage(error))
        }
      )
    }, ignoreNULL = FALSE)

    output$preview_table <- DT::renderDT({
      DT::datatable(
        preview_data(),
        rownames = FALSE,
        filter = "top",
        options = list(pageLength = 25, scrollX = TRUE, deferRender = TRUE)
      )
    })
  })
}
