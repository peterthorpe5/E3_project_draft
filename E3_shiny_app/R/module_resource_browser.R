#' Resource browser UI.
#'
#' @param id Module identifier.
#' @return Shiny UI.
resource_browser_ui <- function(id) {
  ns <- shiny::NS(id)

  shiny::tagList(
    shiny::h3("All results and complete HOG information"),
    shiny::p(
      paste(
        "Use an enriched HOG view to join membership; human, Arabidopsis, rice",
        "and barley representatives; explicit 3D-position and 3D-conservation",
        "status; druggability evidence; both ranking stages; and every field in",
        "the strongest HOG-linked ranking result. Raw DuckDB relations",
        "remain available for exact source-level audit."
      )
    ),
    bslib::layout_columns(
      shiny::selectInput(ns("view_name"), "Result view", choices = "Loading..."),
      shiny::numericInput(
        ns("max_rows"),
        "Preview rows",
        value = 1000,
        min = 1,
        max = 10000
      ),
      shiny::actionButton(ns("refresh"), "Refresh views"),
      shiny::actionButton(ns("preview"), "Preview table", class = "btn-primary")
    ),
    shiny::uiOutput(ns("result_guidance")),
    shiny::div(
      class = "column-selector-panel",
      shiny::h4("Columns to display"),
      shiny::div(
        class = "column-selector-actions",
        shiny::actionButton(ns("select_first"), "First 18 fields"),
        shiny::actionButton(ns("select_all"), "Select all fields"),
        shiny::actionButton(ns("select_none"), "Clear")
      ),
      shiny::checkboxGroupInput(
        ns("selected_columns"),
        label = NULL,
        choices = character(),
        selected = character(),
        inline = TRUE
      )
    ),
    shiny::h4("Column schema"),
    DT::DTOutput(ns("columns")),
    shiny::h4("Table preview"),
    tabular_download_buttons(
      ns = ns,
      tsv_id = "download_tsv",
      excel_id = "download_excel",
      tsv_label = "Download displayed rows as TSV",
      excel_label = "Download displayed rows as Excel"
    ),
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
    current_columns <- shiny::reactiveVal(character())
    enrichment_capability <- shiny::reactiveVal(list(available = FALSE))

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

      relation_columns <- tryCatch(
        expr = collect_enriched_hog_relation_columns(
          resource_source = resource_duckdb_path,
          relations = names
        ),
        error = function(error) {
          shiny::showNotification(
            paste("Failed to inspect HOG-linked views:", conditionMessage(error)),
            type = "warning",
            duration = NULL
          )
          list()
        }
      )
      capability <- enriched_hog_capability(
        relation_columns = relation_columns
      )
      enrichment_capability(capability)
      virtual_choices <- enriched_hog_result_labels()
      if (!isTRUE(capability$available)) {
        virtual_choices <- character()
      } else if (!isTRUE(capability$membership_available)) {
        virtual_choices <- virtual_choices[
          virtual_choices != enriched_hog_members_key()
        ]
      }

      view_names(names)
      raw_choices <- stats::setNames(names, names)
      choices <- c(virtual_choices, raw_choices)
      if (length(choices) == 0L) {
        choices <- "No views found"
      }
      shiny::updateSelectInput(
        session,
        "view_name",
        choices = choices,
        selected = unname(choices[[1L]])
      )
      invisible(names)
    }

    shiny::observeEvent(TRUE, load_view_names(), once = TRUE)
    shiny::observeEvent(input$refresh, load_view_names())

    output$result_guidance <- shiny::renderUI({
      shiny::req(input$view_name)
      if (input$view_name == enriched_hog_overview_key()) {
        return(shiny::div(
          class = "alert alert-info",
          paste(
            "One row represents one root HOG. Both canonical ranking stages,",
            "all original ranking fields, species representatives and HOG",
            "membership summaries are selectable. The first fields foreground",
            "strict pocket-position support, strict 3D conservation and",
            "group-level druggability. Canonical ranks use the strongest",
            "compatible field available in this release. Same-position support",
            "alone does not establish conserved pocket chemistry. Blank support",
            "flags mean unavailable or not assessed; interpret scores with their",
            "assessment-status fields."
          )
        ))
      }
      if (input$view_name == enriched_hog_members_key()) {
        return(shiny::div(
          class = "alert alert-info",
          paste(
            "One row represents one HOG member. HOG annotations and rankings",
            "repeat so every exported member row remains interpretable. When",
            "selected-pocket evidence exists, member druggability and its source",
            "are selectable too. A member with no joined selected-pocket row is",
            "unassessed, not a zero-scoring pocket."
          )
        ))
      }
      shiny::div(
        class = "alert alert-secondary",
        paste(
          "This is a raw source relation. Select all fields includes every",
          "stored field in this relation, but does not join other relations."
        )
      )
    })

    output$columns <- DT::renderDT({
      shiny::req(input$view_name)
      if (input$view_name %in% c("Loading...", "No views found", "Resource DB not configured")) {
        return(readable_datatable(
          tibble::tibble(message = "No resource view selected."),
          rownames = FALSE
        ))
      }

      columns <- tryCatch(
        expr = if (input$view_name %in% unname(enriched_hog_result_labels())) {
          enriched_hog_column_schema(
            result = input$view_name,
            capability = enrichment_capability()
          )
        } else {
          collect_resource_columns(
            duckdb_path = resource_duckdb_path,
            view_name = input$view_name
          )
        },
        error = function(error) tibble::tibble(error = conditionMessage(error))
      )
      names <- if ("column_name" %in% names(columns)) {
        as.character(columns$column_name)
      } else {
        character()
      }
      current_columns(names)
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = names,
        selected = head(names, 18L)
      )

      readable_datatable(
        columns,
        rownames = FALSE,
        options = list(pageLength = 25, scrollX = TRUE)
      )
    })
    shiny::observeEvent(input$select_first, {
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = current_columns(),
        selected = head(current_columns(), 18L)
      )
    })
    shiny::observeEvent(input$select_all, {
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = current_columns(),
        selected = current_columns()
      )
    })
    shiny::observeEvent(input$select_none, {
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = current_columns(),
        selected = character()
      )
    })

    preview_data <- shiny::eventReactive(
      list(input$preview, input$selected_columns),
      {
        shiny::req(input$view_name)
        if (
          input$view_name %in%
            c("Loading...", "No views found", "Resource DB not configured")
        ) {
          return(tibble::tibble(message = "No resource view selected."))
        }

        if (length(input$selected_columns) == 0L) {
          return(tibble::tibble(
            message = "Select at least one result column."
          ))
        }
        tryCatch(
          expr = if (input$view_name %in% unname(enriched_hog_result_labels())) {
            collect_resource_query(
              duckdb_path = resource_duckdb_path,
              query = build_enriched_hog_query(
                result = input$view_name,
                selected_columns = input$selected_columns,
                capability = enrichment_capability(),
                max_rows = input$max_rows
              )
            )
          } else {
            collect_selected_result(
              resource_source = resource_duckdb_path,
              relation = input$view_name,
              selected_columns = input$selected_columns,
              max_rows = input$max_rows
            )
          },
          error = function(error) {
            shiny::showNotification(
              paste(
                "Failed to preview result view:",
                conditionMessage(error)
              ),
              type = "error",
              duration = NULL
            )
            tibble::tibble(error = conditionMessage(error))
          }
        )
      },
      ignoreNULL = FALSE
    )

    output$preview_table <- DT::renderDT({
      readable_datatable(
        preview_data(),
        rownames = FALSE,
        filter = "top",
        options = list(pageLength = 25, scrollX = TRUE, deferRender = TRUE)
      )
    })
    output$download_tsv <- shiny::downloadHandler(
      filename = function() {
        paste0(
          "all_results_",
          safe_export_stem(input$view_name %||% "results"),
          ".tsv"
        )
      },
      content = function(path) {
        utils::write.table(
          preview_data(),
          file = path,
          sep = "\t",
          quote = TRUE,
          row.names = FALSE,
          na = ""
        )
      }
    )
    output$download_excel <- shiny::downloadHandler(
      filename = function() {
        paste0(
          "all_results_",
          safe_export_stem(input$view_name %||% "results"),
          ".xlsx"
        )
      },
      content = function(path) {
        write_formatted_excel(data = preview_data(), path = path)
      }
    )
  })
}
