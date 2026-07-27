#' Expression visualisation module.
#'
#' This module provides small, bounded plots for selected genes. It deliberately
#' uses direct DuckDB SQL to collect only the rows needed for display, then uses
#' ggplot2/plotly for visualisation. The plots are intended for exploration, not
#' for final statistical analysis.

#' Expression plot UI.
#'
#' Creates controls and outputs for plotting selected gene expression. The gene
#' query is required because plotting the whole expression table would be far too
#' large for an interactive Shiny app.
#'
#' @param id Module identifier.
#' @return Shiny UI elements.
expression_plot_ui <- function(id) {
  ns <- shiny::NS(id)

  shiny::tagList(
    bslib::layout_columns(
      shiny::textInput(
        inputId = ns("gene_query"),
        label = "Gene ID or gene name contains",
        value = ""
      ),
      shiny::selectInput(
        inputId = ns("group_column"),
        label = "Group expression by",
        choices = get_expression_plot_group_choices(),
        selected = "sample_or_condition"
      ),
      shiny::selectInput(
        inputId = ns("plot_type"),
        label = "Plot type",
        choices = get_expression_plot_type_choices(),
        selected = "profile"
      ),
      shiny::numericInput(
        inputId = ns("max_rows"),
        label = "Maximum rows to collect",
        value = 5000,
        min = 100,
        max = 50000,
        step = 100
      )
    ),
    shiny::actionButton(
      inputId = ns("plot_expression"),
      label = "Plot selected expression",
      class = "btn-primary"
    ),
    shiny::hr(),
    shinycssloaders::withSpinner(plotly::plotlyOutput(ns("expression_plot"))),
    shiny::hr(),
    shiny::h4("Plot data"),
    shiny::p(
      "The table below is row-limited and is intended for checking what is being plotted."
    ),
    shinycssloaders::withSpinner(DT::DTOutput(ns("plot_data_table")))
  )
}

#' Expression plot server.
#'
#' Collects a bounded set of expression rows for a user-selected gene query and
#' renders one of several exploratory plots. All project-wide filters from the
#' sidebar are applied before data are collected.
#'
#' @param id Module identifier.
#' @param duckdb_path Path to the DuckDB database.
#' @param filters Reactive returning sidebar filter values.
#' @param default_max_rows Default maximum number of rows collected for plotting.
#' @return No return value.
expression_plot_server <- function(
  id,
  duckdb_path,
  filters,
  default_max_rows = 5000L
) {
  shiny::moduleServer(id, function(input, output, session) {
    plot_data <- shiny::eventReactive(input$plot_expression, {
      shiny::req(input$gene_query)

      active_filters <- filters()
      active_filters$gene_search <- input$gene_query

      max_rows <- normalise_plot_max_rows(
        value = input$max_rows,
        default = default_max_rows
      )

      tryCatch(
        expr = collect_expression_plot_data(
          duckdb_path = duckdb_path,
          filters = active_filters,
          max_rows = max_rows
        ),
        error = function(error) {
          shiny::showNotification(
            paste("Failed to collect plot data:", conditionMessage(error)),
            type = "error",
            duration = NULL
          )
          tibble::tibble()
        }
      )
    }, ignoreNULL = TRUE)

    output$expression_plot <- plotly::renderPlotly({
      current_data <- plot_data()

      if (nrow(current_data) == 0L) {
        return(plotly::ggplotly(make_empty_expression_plot(
          "No rows matched the selected gene and filters."
        )))
      }

      plot_object <- build_expression_plot(
        expression_tbl = current_data,
        group_column = input$group_column,
        plot_type = input$plot_type
      )

      plotly::ggplotly(plot_object)
    })

    output$plot_data_table <- DT::renderDT({
      current_data <- plot_data()

      DT::datatable(
        current_data,
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

#' Get plot grouping choices.
#'
#' Returns the columns that users can use as the x-axis/grouping variable for
#' expression plots. These are intentionally limited to columns expected in the
#' metadata-aware expression view.
#'
#' @return Named character vector of group choices.
get_expression_plot_group_choices <- function() {
  c(
    "Expression group / sample" = "sample_or_condition",
    "Organism part" = "organism_part",
    "Developmental stage" = "developmental_stage",
    "Condition" = "condition",
    "Experiment accession" = "experiment_accession"
  )
}

#' Get plot-type choices.
#'
#' Returns the exploratory plot types currently supported by the app.
#'
#' @return Named character vector of plot type choices.
get_expression_plot_type_choices <- function() {
  c(
    "Mean profile" = "profile",
    "Distribution" = "distribution",
    "Heatmap" = "heatmap"
  )
}

#' Normalise maximum plot row count.
#'
#' Converts user input into a safe integer limit for plot-data collection. This
#' prevents accidental collection of very large tables.
#'
#' @param value User-supplied row limit.
#' @param default Default row limit if the value is missing or invalid.
#' @param minimum Minimum allowed row limit.
#' @param maximum Maximum allowed row limit.
#' @return Integer row limit.
normalise_plot_max_rows <- function(
  value,
  default = 5000L,
  minimum = 100L,
  maximum = 50000L
) {
  numeric_value <- suppressWarnings(as.integer(value[[1L]]))

  if (is.na(numeric_value)) {
    return(as.integer(default))
  }

  numeric_value <- max(as.integer(minimum), numeric_value)
  numeric_value <- min(as.integer(maximum), numeric_value)

  as.integer(numeric_value)
}

#' Select a valid plot grouping column.
#'
#' Falls back to `sample_or_condition` when the requested column is absent. This
#' keeps plotting robust as future data sources add or omit metadata fields.
#'
#' @param expression_tbl Collected expression tibble.
#' @param group_column Requested grouping column.
#' @return Valid grouping column name.
choose_plot_group_column <- function(expression_tbl, group_column) {
  valid_columns <- unname(get_expression_plot_group_choices())

  if (is.null(group_column) || !group_column %in% valid_columns) {
    return("sample_or_condition")
  }

  if (!group_column %in% names(expression_tbl)) {
    return("sample_or_condition")
  }

  group_column
}

#' Add a plot group column.
#'
#' Creates a standard `plot_group` column from a selected metadata field. Missing
#' or blank group labels are replaced with `Unknown` so they can still be shown
#' in plots and tables.
#'
#' @param expression_tbl Collected expression tibble.
#' @param group_column Grouping column to use.
#' @return Tibble with a `plot_group` column.
add_plot_group <- function(expression_tbl, group_column = "sample_or_condition") {
  selected_column <- choose_plot_group_column(
    expression_tbl = expression_tbl,
    group_column = group_column
  )

  expression_tbl |>
    dplyr::mutate(
      plot_group = as.character(.data[[selected_column]]),
      plot_group = dplyr::if_else(
        condition = is.na(.data$plot_group) | .data$plot_group == "",
        true = "Unknown",
        false = .data$plot_group
      )
    )
}

#' Summarise expression for plotting.
#'
#' Aggregates collected expression values by gene and plot group. This gives a
#' compact table that can support profile and heatmap plots without requiring
#' further DuckDB queries.
#'
#' @param expression_tbl Collected expression tibble.
#' @param group_column Grouping column to use.
#' @return Summary tibble with mean, median and sample count.
prepare_expression_plot_summary <- function(
  expression_tbl,
  group_column = "sample_or_condition"
) {
  add_plot_group(
    expression_tbl = expression_tbl,
    group_column = group_column
  ) |>
    dplyr::group_by(
      .data$gene_id,
      .data$gene_name,
      .data$plot_group,
      .data$expression_unit
    ) |>
    dplyr::summarise(
      mean_expression = mean(.data$expression_value, na.rm = TRUE),
      median_expression = stats::median(.data$expression_value, na.rm = TRUE),
      n_values = dplyr::n(),
      .groups = "drop"
    )
}

#' Make an empty placeholder plot.
#'
#' Creates a simple ggplot object with a message. This is used when a query
#' returns no rows or when a plot type is unavailable.
#'
#' @param message Message to display.
#' @return ggplot object.
make_empty_expression_plot <- function(message) {
  ggplot2::ggplot() +
    ggplot2::annotate(
      geom = "text",
      x = 0,
      y = 0,
      label = message,
      size = 5
    ) +
    ggplot2::theme_void()
}

#' Build a mean expression profile plot.
#'
#' Plots mean expression for each gene across the selected grouping variable.
#'
#' @param summary_tbl Output from `prepare_expression_plot_summary()`.
#' @return ggplot object.
build_expression_profile_plot <- function(summary_tbl) {
  if (nrow(summary_tbl) == 0L) {
    return(make_empty_expression_plot("No expression rows available to plot."))
  }

  ggplot2::ggplot(
    data = summary_tbl,
    mapping = ggplot2::aes(
      x = .data$plot_group,
      y = .data$mean_expression,
      colour = .data$gene_id,
      group = .data$gene_id,
      text = paste0(
        "Gene: ", .data$gene_id,
        "<br>Gene name: ", .data$gene_name,
        "<br>Group: ", .data$plot_group,
        "<br>Mean expression: ", signif(.data$mean_expression, 4),
        "<br>n: ", .data$n_values
      )
    )
  ) +
    ggplot2::geom_line() +
    ggplot2::geom_point() +
    ggplot2::labs(
      x = "Group",
      y = "Mean expression",
      colour = "Gene ID"
    ) +
    ggplot2::theme_minimal() +
    ggplot2::theme(axis.text.x = ggplot2::element_text(angle = 45, hjust = 1))
}

#' Build an expression distribution plot.
#'
#' Shows raw expression-value distributions across the selected grouping
#' variable. This is useful for checking replicate/sample spread.
#'
#' @param expression_tbl Collected expression tibble.
#' @param group_column Grouping column to use.
#' @return ggplot object.
build_expression_distribution_plot <- function(
  expression_tbl,
  group_column = "sample_or_condition"
) {
  plot_tbl <- add_plot_group(
    expression_tbl = expression_tbl,
    group_column = group_column
  )

  if (nrow(plot_tbl) == 0L) {
    return(make_empty_expression_plot("No expression rows available to plot."))
  }

  ggplot2::ggplot(
    data = plot_tbl,
    mapping = ggplot2::aes(
      x = .data$plot_group,
      y = .data$expression_value,
      colour = .data$gene_id,
      text = paste0(
        "Gene: ", .data$gene_id,
        "<br>Gene name: ", .data$gene_name,
        "<br>Group: ", .data$plot_group,
        "<br>Expression: ", signif(.data$expression_value, 4)
      )
    )
  ) +
    ggplot2::geom_boxplot(outlier.shape = NA) +
    ggplot2::geom_jitter(width = 0.2, alpha = 0.5) +
    ggplot2::labs(
      x = "Group",
      y = "Expression",
      colour = "Gene ID"
    ) +
    ggplot2::theme_minimal() +
    ggplot2::theme(axis.text.x = ggplot2::element_text(angle = 45, hjust = 1))
}

#' Build a gene-by-group heatmap.
#'
#' Displays mean expression as tiles for each gene/group combination.
#'
#' @param summary_tbl Output from `prepare_expression_plot_summary()`.
#' @return ggplot object.
build_expression_heatmap_plot <- function(summary_tbl) {
  if (nrow(summary_tbl) == 0L) {
    return(make_empty_expression_plot("No expression rows available to plot."))
  }

  ggplot2::ggplot(
    data = summary_tbl,
    mapping = ggplot2::aes(
      x = .data$plot_group,
      y = .data$gene_id,
      fill = .data$mean_expression,
      text = paste0(
        "Gene: ", .data$gene_id,
        "<br>Gene name: ", .data$gene_name,
        "<br>Group: ", .data$plot_group,
        "<br>Mean expression: ", signif(.data$mean_expression, 4),
        "<br>n: ", .data$n_values
      )
    )
  ) +
    ggplot2::geom_tile() +
    ggplot2::labs(
      x = "Group",
      y = "Gene ID",
      fill = "Mean expression"
    ) +
    ggplot2::theme_minimal() +
    ggplot2::theme(axis.text.x = ggplot2::element_text(angle = 45, hjust = 1))
}

#' Build the requested expression plot.
#'
#' Dispatches to the plot builder selected by the user.
#'
#' @param expression_tbl Collected expression tibble.
#' @param group_column Grouping column to use.
#' @param plot_type Plot type: `profile`, `distribution`, or `heatmap`.
#' @return ggplot object.
build_expression_plot <- function(
  expression_tbl,
  group_column = "sample_or_condition",
  plot_type = "profile"
) {
  if (identical(plot_type, "distribution")) {
    return(build_expression_distribution_plot(
      expression_tbl = expression_tbl,
      group_column = group_column
    ))
  }

  summary_tbl <- prepare_expression_plot_summary(
    expression_tbl = expression_tbl,
    group_column = group_column
  )

  if (identical(plot_type, "heatmap")) {
    return(build_expression_heatmap_plot(summary_tbl = summary_tbl))
  }

  build_expression_profile_plot(summary_tbl = summary_tbl)
}
