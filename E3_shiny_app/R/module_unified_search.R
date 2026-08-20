#' Multi-field, pasted-list search module.

#' Build the complete-resource search UI.
#'
#' @param id Module identifier.
#' @return Shiny UI.
unified_search_ui <- function(id) {
  ns <- shiny::NS(id)
  shiny::tagList(
    shiny::h2("Multi-field E3 resource search"),
    shiny::p(
      class = "grant-question",
      paste(
        "Search one item or paste a list of names, N0.HOG IDs, OG IDs, E3",
        "seeds, UniProt accessions, gene names, entries or DeepClust IDs.",
        "Results retain the matched term, source relation, matched fields and",
        "every available source column."
      )
    ),
    shiny::textAreaInput(
      ns("terms"),
      "Search term(s)",
      rows = 7,
      placeholder = paste(
        "One item per line, or separated by commas/semicolons",
        "Q9SA03",
        "N0.HOG0002084",
        "FB27",
        sep = "\n"
      )
    ),
    shiny::radioButtons(
      ns("mode"),
      "Matching method",
      choices = c(
        "Smart: exact identifiers plus partial names" = "smart",
        "Exact identifiers and semicolon-list tokens" = "exact",
        "Literal contains matching" = "contains"
      ),
      selected = "smart",
      inline = TRUE
    ),
    shiny::numericInput(
      ns("max_rows_per_relation"),
      "Maximum matching rows per source relation",
      value = 250,
      min = 1,
      max = 10000,
      step = 50
    ),
    shiny::actionButton(
      ns("search"),
      "Search the complete loaded resource",
      class = "btn-primary"
    ),
    shiny::uiOutput(ns("status")),
    shiny::uiOutput(ns("metrics")),
    shiny::h3("Match summary"),
    tabular_download_buttons(
      ns,
      "download_summary_tsv",
      "download_summary_excel",
      "Download search summary as TSV",
      "Download search summary as Excel"
    ),
    shinycssloaders::withSpinner(DT::DTOutput(ns("summary_table"))),
    shiny::h3("Complete matching source rows"),
    shiny::div(
      class = "column-selector-panel",
      shiny::h4("Columns to display and download"),
      shiny::p(
        class = "small text-muted",
        paste(
          "All fields returned by every matching relation remain selectable.",
          "Choose a focused subset or select all for a complete audit."
        )
      ),
      shiny::div(
        class = "column-selector-actions",
        shiny::actionButton(ns("select_first"), "First 18 columns"),
        shiny::actionButton(ns("select_all"), "Select all columns"),
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
      ns,
      "download_matches_tsv",
      "download_matches_excel",
      "Download selected matching columns as TSV",
      "Download selected matching columns as Excel"
    ),
    shinycssloaders::withSpinner(DT::DTOutput(ns("matches_table")))
  )
}

#' Serve complete-resource list search.
#'
#' @param id Module identifier.
#' @param resource_source Flexible E3 result source.
#' @param max_rows Global maximum total rows.
#' @return Search result reactives, invisibly.
unified_search_server <- function(id, resource_source, max_rows = 1000L) {
  shiny::moduleServer(id, function(input, output, session) {
    submitted_terms <- shiny::reactiveVal(character())
    matches <- shiny::eventReactive(input$search, {
      terms <- parse_unified_search_terms(input$terms)
      shiny::validate(shiny::need(
        length(terms) > 0L,
        "Enter at least one search term."
      ))
      submitted_terms(terms)
      catalogue <- collect_resource_query(
        resource_source,
        build_unified_search_catalogue_query()
      )
      message(
        "Starting unified E3 search for ", length(terms), " unique term(s)."
      )
      result <- collect_unified_search_results(
        resource_source,
        catalogue,
        terms,
        input$mode,
        max(1L, min(10000L, as.integer(input$max_rows_per_relation))),
        max(10000L, min(100000L, as.integer(max_rows)))
      )
      message("Unified E3 search returned ", nrow(result), " row(s).")
      result
    }, ignoreInit = TRUE)

    summary <- shiny::reactive({
      summarise_unified_search_results(matches())
    })

    matching_columns <- shiny::reactive({ names(matches()) })
    shiny::observeEvent(matches(), {
      columns <- matching_columns()
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = columns,
        selected = head(columns, 18L)
      )
    })
    shiny::observeEvent(input$select_first, {
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = matching_columns(),
        selected = head(matching_columns(), 18L)
      )
    })
    shiny::observeEvent(input$select_all, {
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = matching_columns(),
        selected = matching_columns()
      )
    })
    shiny::observeEvent(input$select_none, {
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = matching_columns(),
        selected = character()
      )
    })
    displayed_matches <- shiny::reactive({
      data <- matches()
      selected <- intersect(input$selected_columns %||% character(), names(data))
      if (length(selected) == 0L) {
        return(tibble::tibble(message = "Select at least one matching-row column."))
      }
      data[, selected, drop = FALSE]
    })

    output$status <- shiny::renderUI({
      if (input$search == 0L) {
        return(shiny::div(
          class = "alert alert-info",
          "Enter one or more terms and run the search."
        ))
      }
      if (nrow(matches()) == 0L) {
        return(shiny::div(
          class = "alert alert-warning",
          "No identifier or name match was found in recognised fields."
        ))
      }
      shiny::div(
        class = "alert alert-success",
        "Search completed. Use the source and matched-field columns to audit hits."
      )
    })

    output$metrics <- shiny::renderUI({
      data <- matches()
      shiny::req(nrow(data) > 0L)
      box <- function(title, value) {
        bslib::value_box(
          title = title,
          value = format(value, big.mark = ",", scientific = FALSE)
        )
      }
      bslib::layout_columns(
        box(
          "Entered terms matched",
          paste0(
            length(unique(data$`_search_term`)),
            " / ",
            length(submitted_terms())
          )
        ),
        box("Source relations", length(unique(data$`_relation`))),
        box("Matching source rows", nrow(data)),
        col_widths = c(4, 4, 4)
      )
    })

    output$summary_table <- DT::renderDT({
      readable_datatable(summary(), rownames = FALSE, filter = "top")
    })
    output$matches_table <- DT::renderDT({
      readable_datatable(displayed_matches(), rownames = FALSE, filter = "top")
    })

    human_hog_table_downloads(
      output,
      "summary",
      summary,
      "unified_search_summary"
    )
    human_hog_table_downloads(
      output,
      "matches",
      displayed_matches,
      "unified_search_matches"
    )

    invisible(list(matches = matches, summary = summary))
  })
}
