#' Expression filter UI.
#'
#' Creates sidebar controls for filtering the expression table. The initial
#' choices are deliberately lightweight placeholders; the server module replaces
#' them with real values from DuckDB after the app starts.
#'
#' @param id Module identifier.
#' @return Shiny UI elements.
expression_filters_ui <- function(id) {
  ns <- shiny::NS(id)

  shiny::tagList(
    shiny::selectInput(ns("species_column"), "Species", choices = "All"),
    shiny::selectInput(ns("expression_unit"), "Expression unit", choices = "TPM"),
    shiny::selectInput(ns("experiment_accession"), "Experiment", choices = "All"),
    shiny::selectInput(ns("organism_part"), "Organism part", choices = "All"),
    shiny::selectInput(ns("developmental_stage"), "Developmental stage", choices = "All"),
    shiny::selectInput(ns("condition"), "Condition", choices = "All"),
    shiny::textInput(ns("gene_search"), "Gene ID / gene name contains", value = ""),
    shiny::numericInput(ns("minimum_expression"), "Minimum expression", value = 0, min = 0),
    shiny::actionButton(ns("apply_filters"), "Apply filters", class = "btn-primary")
  )
}

#' Update a select input while preserving safe defaults.
#'
#' Adds an optional `All` choice and replaces empty choice vectors with a clear
#' fallback. This keeps the UI usable when a species has sparse metadata.
#'
#' @param session Shiny session object.
#' @param input_id Input identifier within the module namespace.
#' @param choices Character vector of choices.
#' @param include_all Whether to prepend `All`.
#' @param selected Selected value.
#' @return Invisibly returns the final choices.
update_filter_select <- function(
  session,
  input_id,
  choices,
  include_all = TRUE,
  selected = NULL
) {
  unique_choices <- sort(unique(as.character(choices)))
  unique_choices <- unique_choices[!is.na(unique_choices) & unique_choices != ""]

  final_choices <- if (include_all) {
    c("All", unique_choices)
  } else {
    unique_choices
  }

  if (length(final_choices) == 0L) {
    final_choices <- "All"
  }

  if (is.null(selected) || !selected %in% final_choices) {
    selected <- final_choices[[1L]]
  }

  shiny::updateSelectInput(
    session = session,
    inputId = input_id,
    choices = final_choices,
    selected = selected
  )

  invisible(final_choices)
}

#' Safely collect filter choices.
#'
#' Wraps choice collection so the app shows a useful notification rather than a
#' permanently grey loading screen when DuckDB paths are broken or a query fails.
#'
#' @param expr Expression that returns filter choices.
#' @param session Shiny session object.
#' @param message Failure message to show to the user.
#' @return The expression result, or NULL on failure.
safely_collect_choices <- function(expr, session, message) {
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

#' Expression filter server.
#'
#' Populates filter controls from DuckDB using small filter-choice queries, not
#' from the huge expression-plus-metadata joined view. This keeps app start-up
#' responsive on large datasets.
#'
#' @param id Module identifier.
#' @param duckdb_path Path to the DuckDB database.
#' @param default_expression_unit Default expression unit.
#' @return Reactive list of filter values.
expression_filters_server <- function(
  id,
  duckdb_path,
  default_expression_unit = "TPM"
) {
  shiny::moduleServer(id, function(input, output, session) {
    # Initial species/unit choices are read once from atlas_expression_long.  Do
    # not use the joined expression-metadata view here: that view can represent
    # hundreds of millions of rows.
    shiny::observeEvent(TRUE, {
      initial_choices <- safely_collect_choices(
        expr = collect_initial_filter_choices(duckdb_path = duckdb_path),
        session = session,
        message = "Failed to load initial filter choices:"
      )

      shiny::req(!is.null(initial_choices))

      default_species <- if (length(initial_choices$species) > 0L) {
        initial_choices$species[[1L]]
      } else {
        "All"
      }

      update_filter_select(
        session = session,
        input_id = "species_column",
        choices = initial_choices$species,
        include_all = TRUE,
        selected = default_species
      )

      update_filter_select(
        session = session,
        input_id = "expression_unit",
        choices = initial_choices$expression_units,
        include_all = TRUE,
        selected = default_expression_unit
      )
    }, once = TRUE)

    # Context-dependent filters are refreshed when species or unit changes.
    shiny::observeEvent(
      eventExpr = list(input$species_column, input$expression_unit),
      handlerExpr = {
        shiny::req(input$species_column)
        shiny::req(input$expression_unit)

        context_choices <- safely_collect_choices(
          expr = collect_context_filter_choices(
            duckdb_path = duckdb_path,
            species_column = input$species_column,
            expression_unit = input$expression_unit
          ),
          session = session,
          message = "Failed to load context filter choices:"
        )

        shiny::req(!is.null(context_choices))

        update_filter_select(
          session = session,
          input_id = "experiment_accession",
          choices = context_choices$experiments,
          include_all = TRUE,
          selected = "All"
        )

        update_filter_select(
          session = session,
          input_id = "organism_part",
          choices = context_choices$organism_parts,
          include_all = TRUE,
          selected = "All"
        )

        update_filter_select(
          session = session,
          input_id = "developmental_stage",
          choices = context_choices$developmental_stages,
          include_all = TRUE,
          selected = "All"
        )

        update_filter_select(
          session = session,
          input_id = "condition",
          choices = context_choices$conditions,
          include_all = TRUE,
          selected = "All"
        )
      },
      ignoreInit = TRUE
    )

    # Store the eventReactive in a named object so it can be returned to the
    # main app and tested with shiny::testServer().
    filters <- shiny::eventReactive(input$apply_filters, {
      list(
        species_column = input$species_column,
        expression_unit = input$expression_unit,
        experiment_accession = input$experiment_accession,
        organism_part = input$organism_part,
        developmental_stage = input$developmental_stage,
        condition = input$condition,
        gene_search = input$gene_search,
        minimum_expression = input$minimum_expression %||% 0
      )
    }, ignoreNULL = FALSE)

    filters
  })
}
