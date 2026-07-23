#' Reusable grant-facing result section with independent column controls.

#' Result-section UI.
#'
#' @param id Module identifier.
#' @param section Stable result-section identifier.
#' @return Shiny UI.
result_section_ui <- function(id, section) {
  if (!section %in% names(result_section_specs)) {
    stop(paste0("Unknown result section: ", section), call. = FALSE)
  }
  ns <- shiny::NS(id)
  specification <- result_section_specs[[section]]
  shiny::tagList(
    shiny::h3(specification$title),
    shiny::p(class = "grant-question", specification$question),
    bslib::layout_columns(
      shiny::selectInput(
        ns("relation"),
        "Result table",
        choices = "Loading..."
      ),
      shiny::numericInput(
        ns("max_rows"),
        "Rows to display",
        value = 500,
        min = 1,
        max = 10000
      ),
      shiny::actionButton(
        ns("preview"),
        "Refresh results",
        class = "btn-primary"
      ),
      col_widths = c(5, 3, 4)
    ),
    shiny::div(
      class = "column-selector-panel",
      shiny::h4("Columns to display"),
      shiny::p(
        class = "small text-muted",
        "Each section keeps its own selection. All source columns remain available."
      ),
      shiny::div(
        class = "column-selector-actions",
        shiny::actionButton(ns("select_defaults"), "Grant defaults"),
        shiny::actionButton(ns("select_all"), "Select all"),
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
    shiny::downloadButton(ns("download_tsv"), "Download displayed rows as TSV"),
    shinycssloaders::withSpinner(DT::DTOutput(ns("result_table")))
  )
}

#' Result-section server.
#'
#' @param id Module identifier.
#' @param section Stable result-section identifier.
#' @param resource_source Flexible result source.
#' @param max_rows Global row cap.
#' @return Reactive containing the displayed result.
result_section_server <- function(
  id,
  section,
  resource_source,
  max_rows = 1000L
) {
  shiny::moduleServer(id, function(input, output, session) {
    available_relations <- shiny::reactiveVal(character())
    available_columns <- shiny::reactiveVal(character())

    load_relations <- function() {
      if (!resource_source_available(resource_source)) {
        shiny::updateSelectInput(
          session,
          "relation",
          choices = "Result source not configured"
        )
        return(invisible(character()))
      }
      relations <- tryCatch(
        collect_resource_view_names(resource_source),
        error = function(error) {
          shiny::showNotification(
            paste("Could not list result tables:", conditionMessage(error)),
            type = "error",
            duration = NULL
          )
          character()
        }
      )
      selected <- relations_for_result_section(relations, section)
      if (length(selected) == 0L) {
        selected <- "No recognised result table"
      }
      available_relations(selected)
      shiny::updateSelectInput(
        session,
        "relation",
        choices = selected,
        selected = selected[[1L]]
      )
      invisible(selected)
    }

    load_columns <- function(relation) {
      if (
        is.null(relation) ||
          relation %in% c(
            "Loading...",
            "Result source not configured",
            "No recognised result table"
          )
      ) {
        available_columns(character())
        shiny::updateCheckboxGroupInput(
          session,
          "selected_columns",
          choices = character(),
          selected = character()
        )
        return(invisible(character()))
      }
      columns <- tryCatch(
        collect_resource_columns(resource_source, relation),
        error = function(error) {
          shiny::showNotification(
            paste("Could not inspect result columns:", conditionMessage(error)),
            type = "error",
            duration = NULL
          )
          tibble::tibble(column_name = character())
        }
      )
      names <- as.character(columns$column_name)
      selected <- default_result_columns(section, names)
      available_columns(names)
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = names,
        selected = selected
      )
      invisible(names)
    }

    shiny::observeEvent(TRUE, load_relations(), once = TRUE)
    shiny::observeEvent(input$relation, load_columns(input$relation))
    shiny::observeEvent(input$select_defaults, {
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = available_columns(),
        selected = default_result_columns(section, available_columns())
      )
    })
    shiny::observeEvent(input$select_all, {
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = available_columns(),
        selected = available_columns()
      )
    })
    shiny::observeEvent(input$select_none, {
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = available_columns(),
        selected = character()
      )
    })

    displayed <- shiny::eventReactive(
      list(input$preview, input$relation, input$selected_columns, input$max_rows),
      {
        if (
          is.null(input$relation) ||
            input$relation %in% c(
              "Loading...",
              "Result source not configured",
              "No recognised result table"
            )
        ) {
          return(tibble::tibble(
            message = "No recognised result table is available for this section."
          ))
        }
        if (length(input$selected_columns) == 0L) {
          return(tibble::tibble(message = "Select at least one result column."))
        }
        row_limit <- min(
          max(1L, as.integer(input$max_rows)),
          as.integer(max_rows)
        )
        tryCatch(
          collect_selected_result(
            resource_source = resource_source,
            relation = input$relation,
            selected_columns = input$selected_columns,
            max_rows = row_limit
          ),
          error = function(error) {
            shiny::showNotification(
              paste("Could not query result table:", conditionMessage(error)),
              type = "error",
              duration = NULL
            )
            tibble::tibble(error = conditionMessage(error))
          }
        )
      },
      ignoreNULL = FALSE
    )

    output$result_table <- DT::renderDT({
      DT::datatable(
        displayed(),
        rownames = FALSE,
        filter = "top",
        extensions = "Buttons",
        options = list(
          pageLength = 25,
          scrollX = TRUE,
          deferRender = TRUE,
          dom = "tip"
        )
      )
    })
    output$download_tsv <- shiny::downloadHandler(
      filename = function() {
        paste0(section, "_", input$relation %||% "results", ".tsv")
      },
      content = function(path) {
        utils::write.table(
          displayed(),
          file = path,
          sep = "\t",
          quote = TRUE,
          row.names = FALSE,
          na = ""
        )
      }
    )
    displayed
  })
}
