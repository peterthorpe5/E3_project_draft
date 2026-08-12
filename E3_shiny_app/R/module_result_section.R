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
    if (identical(section, "expression")) {
      shiny::div(
        class = "alert alert-info",
        paste(
          "NOT_MAPPED means that no unique Atlas gene mapping was found.",
          "Zero count fields in a legacy relation are not measured zero",
          "expression. Corrected records use the median of Atlas's five-number",
          "summary and classify TPM values at least 0.5 as context-positive.",
          "Tissue choices appear when the selected relation contains",
          "organism_part metadata."
        )
      )
    },
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
    if (identical(section, "expression")) {
      shiny::tagList(
        bslib::layout_columns(
          shiny::selectInput(
            ns("expression_species"),
            "Species",
            choices = "All species"
          ),
          shiny::selectInput(
            ns("expression_tissue"),
            "Tissue / organism part",
            choices = "All tissues"
          ),
          shiny::textInput(
            ns("expression_search"),
            "Candidate group, accession or gene",
            value = ""
          ),
          col_widths = c(3, 3, 6)
        ),
        bslib::layout_columns(
          shiny::selectInput(
            ns("expression_metadata_status"),
            "Tissue metadata status",
            choices = "All metadata states"
          ),
          shiny::selectInput(
            ns("expression_positive"),
            "Median TPM threshold",
            choices = c(
              "All values" = "",
              "At least 0.5 TPM" = "true",
              "Below 0.5 TPM" = "false"
            )
          ),
          col_widths = c(6, 6)
        )
      )
    },
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
    tabular_download_buttons(
      ns = ns,
      tsv_id = "download_tsv",
      excel_id = "download_excel",
      tsv_label = "Download displayed rows as TSV",
      excel_label = "Download displayed rows as Excel"
    ),
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
      if (identical(section, "expression")) {
        expression_filter_choices <- function(column, all_label) {
          if (!column %in% names) {
            return(stats::setNames("", all_label))
          }
          values <- tryCatch(
            collect_distinct_result_values(
              resource_source = resource_source,
              relation = relation,
              column = column
            ),
            error = function(error) {
              character()
            }
          )
          c(stats::setNames("", all_label), values)
        }
        shiny::updateSelectInput(
          session,
          "expression_species",
          choices = expression_filter_choices(
            "species_column",
            "All species"
          ),
          selected = ""
        )
        shiny::updateSelectInput(
          session,
          "expression_tissue",
          choices = expression_filter_choices(
            "organism_part",
            "All tissues"
          ),
          selected = ""
        )
        shiny::updateSelectInput(
          session,
          "expression_metadata_status",
          choices = expression_filter_choices(
            "metadata_status",
            "All metadata states"
          ),
          selected = ""
        )
      }
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
      list(
        input$preview,
        input$relation,
        input$selected_columns,
        input$max_rows,
        input$expression_species,
        input$expression_tissue,
        input$expression_metadata_status,
        input$expression_positive,
        input$expression_search
      ),
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
          if (identical(section, "expression")) {
            collect_filtered_expression_result(
              resource_source = resource_source,
              relation = input$relation,
              selected_columns = input$selected_columns,
              available_columns = available_columns(),
              species = input$expression_species %||% "",
              tissue = input$expression_tissue %||% "",
              metadata_status = input$expression_metadata_status %||% "",
              expression_positive = input$expression_positive %||% "",
              search = input$expression_search %||% "",
              max_rows = row_limit
            )
          } else {
            collect_selected_result(
              resource_source = resource_source,
              relation = input$relation,
              selected_columns = input$selected_columns,
              max_rows = row_limit
            )
          },
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
    output$download_excel <- shiny::downloadHandler(
      filename = function() {
        paste0(section, "_", input$relation %||% "results", ".xlsx")
      },
      content = function(path) {
        write_formatted_excel(
          data = displayed(),
          path = path
        )
      }
    )
    displayed
  })
}
