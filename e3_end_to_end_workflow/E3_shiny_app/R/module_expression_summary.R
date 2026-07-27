#' Expression summary UI.
#'
#' Creates summary cards for the current filter selection. The values are filled
#' by direct DuckDB aggregation queries on the server side.
#'
#' @param id Module identifier.
#' @return Shiny UI elements.
expression_summary_ui <- function(id) {
  ns <- shiny::NS(id)

  shiny::tagList(
    bslib::layout_columns(
      bslib::value_box("Rows", shiny::textOutput(ns("row_count"))),
      bslib::value_box("Genes", shiny::textOutput(ns("gene_count"))),
      bslib::value_box("Experiments", shiny::textOutput(ns("experiment_count"))),
      bslib::value_box("Groups", shiny::textOutput(ns("group_count")))
    ),
    shiny::h4("Metadata coverage"),
    DT::DTOutput(ns("metadata_coverage"))
  )
}

#' Format a summary count for display.
#'
#' Converts a scalar numeric/integer count into a human-readable string. Missing
#' or invalid values become `0` rather than surfacing as an unhelpful Shiny error.
#'
#' @param value Count value.
#' @return Formatted character value.
format_summary_count <- function(value) {
  if (is.null(value) || length(value) == 0L || is.na(value[[1L]])) {
    return("0")
  }

  format(as.numeric(value[[1L]]), big.mark = ",", scientific = FALSE)
}

#' Safely evaluate a small summary query.
#'
#' Keeps Shiny summary cards readable if DuckDB reports an error. The underlying
#' error is also shown as a notification so debugging information is not lost.
#'
#' @param expr Expression returning a tibble.
#' @param session Shiny session.
#' @param message User-facing error prefix.
#' @return Query result or NULL.
safely_collect_summary <- function(expr, session, message) {
  tryCatch(
    expr = force(expr),
    error = function(error) {
      shiny::showNotification(
        paste(message, conditionMessage(error)),
        type = "error",
        duration = NULL
      )
      NULL
    }
  )
}

#' Expression summary server.
#'
#' Computes small summary and metadata-coverage tables using direct DuckDB SQL.
#' This is more robust than deriving summaries from a large joined lazy frame and
#' avoids displaying opaque `[object Object]` errors in the value boxes.
#'
#' @param id Module identifier.
#' @param duckdb_path Path to the DuckDB database.
#' @param filters Reactive returning the current filter list.
#' @return No return value.
expression_summary_server <- function(id, duckdb_path, filters) {
  shiny::moduleServer(id, function(input, output, session) {
    summary_table <- shiny::reactive({
      result <- safely_collect_summary(
        expr = collect_expression_summary(
          duckdb_path = duckdb_path,
          filters = filters()
        ),
        session = session,
        message = "Failed to summarise expression selection:"
      )

      if (is.null(result)) {
        return(tibble::tibble(
          rows = NA_real_,
          genes = NA_real_,
          experiments = NA_real_,
          groups = NA_real_
        ))
      }

      result
    })

    coverage_table <- shiny::reactive({
      result <- safely_collect_summary(
        expr = collect_metadata_coverage(
          duckdb_path = duckdb_path,
          filters = filters()
        ),
        session = session,
        message = "Failed to summarise metadata coverage:"
      )

      if (is.null(result)) {
        return(tibble::tibble(
          rows = NA_real_,
          rows_with_organism_part = NA_real_,
          rows_with_developmental_stage = NA_real_,
          rows_with_condition = NA_real_
        ))
      }

      result
    })

    output$row_count <- shiny::renderText({
      format_summary_count(summary_table()$rows)
    })

    output$gene_count <- shiny::renderText({
      format_summary_count(summary_table()$genes)
    })

    output$experiment_count <- shiny::renderText({
      format_summary_count(summary_table()$experiments)
    })

    output$group_count <- shiny::renderText({
      format_summary_count(summary_table()$groups)
    })

    output$metadata_coverage <- DT::renderDT({
      DT::datatable(
        coverage_table(),
        rownames = FALSE,
        options = list(dom = "t", paging = FALSE)
      )
    })
  })
}
