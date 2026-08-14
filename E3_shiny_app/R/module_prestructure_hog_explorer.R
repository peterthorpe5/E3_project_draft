#' Dedicated ungated pre-structure HOG ranking module.

#' Build the pre-structure ranked-HOG tab.
#'
#' @param id Module identifier.
#' @return Shiny UI.
prestructure_hog_explorer_ui <- function(id) {
  ns <- shiny::NS(id)
  shiny::tagList(
    shiny::h2("Top pre-structure ranked HOGs"),
    shiny::div(
      class = "alert alert-info",
      paste(
        "This list applies no target-species, domain, expression, pocket,",
        "druggability or structural gate. It selects root-level N0.HOG groups",
        "directly by the recorded pre-structure evolutionary-group rank."
      )
    ),
    bslib::layout_columns(
      shiny::numericInput(
        ns("top_n"),
        "Number of ranked HOGs",
        value = 200,
        min = 1,
        max = 10000,
        step = 50
      ),
      shiny::textInput(
        ns("filter"),
        "Filter within the selected top-ranked HOGs",
        placeholder = "HOG ID, accession, seed, name or representative"
      ),
      col_widths = c(4, 8)
    ),
    shiny::uiOutput(ns("availability")),
    bslib::layout_columns(
      bslib::value_box(
        "Ranked HOGs returned",
        shiny::textOutput(ns("returned_count"))
      ),
      bslib::value_box(
        "Best recorded rank",
        shiny::textOutput(ns("best_rank"))
      ),
      bslib::value_box(
        "Lowest recorded rank shown",
        shiny::textOutput(ns("lowest_rank"))
      )
    ),
    tabular_download_buttons(
      ns,
      "download_tsv",
      "download_excel",
      "Download ranked HOGs as TSV",
      "Download ranked HOGs as Excel"
    ),
    shinycssloaders::withSpinner(DT::DTOutput(ns("ranked_hog_table")))
  )
}

#' Serve the pre-structure ranked-HOG tab.
#'
#' @param id Module identifier.
#' @param resource_source Flexible E3 result source.
#' @param max_rows Global bounded row cap.
#' @return Displayed ranked HOG reactive, invisibly.
prestructure_hog_explorer_server <- function(
  id,
  resource_source,
  max_rows = 1000L
) {
  shiny::moduleServer(id, function(input, output, session) {
    context <- shiny::reactive({
      tryCatch({
        if (!resource_source_available(resource_source = resource_source)) {
          return(NULL)
        }
        relations <- collect_resource_view_names(
          duckdb_path = resource_source
        )
        columns <- human_hog_relation_columns(
          resource_source = resource_source,
          relations = relations
        )
        source <- select_prestructure_hog_source(relation_columns = columns)
        if (is.null(source)) return(NULL)
        source$membership_columns <-
          columns$hierarchical_membership %||% character()
        source$membership_available <-
          "hierarchical_membership" %in% relations
        source
      }, error = function(error) {
        message(
          "Could not inspect the pre-structure HOG source: ",
          conditionMessage(error)
        )
        shiny::showNotification(
          paste("Could not inspect the ranked-HOG source:", error$message),
          type = "error"
        )
        NULL
      })
    })

    ranked <- shiny::reactive({
      source <- context()
      if (is.null(source)) return(tibble::tibble())
      requested <- suppressWarnings(as.integer(input$top_n %||% 200L))
      requested <- min(max(1L, requested), as.integer(max_rows), 10000L)
      tryCatch({
        query <- build_prestructure_ranked_hog_query(
          relation = source$relation,
          available = source$columns,
          rank_column = source$rank_column,
          max_hogs = requested,
          membership_available = source$membership_available,
          membership_columns = source$membership_columns
        )
        result <- collect_resource_query(
          duckdb_path = resource_source,
          query = query
        )
        message(
          "Collected ", nrow(result),
          " ungated pre-structure ranked HOGs from ", source$relation
        )
        result
      }, error = function(error) {
        message(
          "Could not collect pre-structure ranked HOGs: ",
          conditionMessage(error)
        )
        shiny::showNotification(
          paste("Could not collect ranked HOGs:", error$message),
          type = "error"
        )
        tibble::tibble()
      })
    })

    displayed <- shiny::reactive({
      filter_prestructure_ranked_hogs(
        data = ranked(),
        query = input$filter %||% ""
      )
    })

    rank_summary <- shiny::reactive({
      source <- context()
      rank_column <- if (is.null(source)) NA_character_ else source$rank_column
      summarise_prestructure_hog_ranks(
        data = displayed(),
        rank_column = rank_column
      )
    })

    output$availability <- shiny::renderUI({
      source <- context()
      if (is.null(source)) {
        return(shiny::div(
          class = "alert alert-warning",
          paste(
            "The source lacks primary_group_id and an authoritative",
            "pre-structure evolutionary-group rank."
          )
        ))
      }
      shiny::p(
        class = "small text-muted",
        paste0(
          "Authoritative source: `", source$relation, "`; rank field: `",
          source$rank_column, "`. Human and Arabidopsis representatives are ",
          "added from root-level membership where available."
        )
      )
    })

    output$returned_count <- shiny::renderText({
      format(rank_summary()$returned_count, big.mark = ",")
    })
    format_rank <- function(value) {
      if (is.na(value)) return("—")
      format(value, big.mark = ",", scientific = FALSE)
    }
    output$best_rank <- shiny::renderText({
      format_rank(rank_summary()$best_rank)
    })
    output$lowest_rank <- shiny::renderText({
      format_rank(rank_summary()$lowest_rank)
    })

    output$ranked_hog_table <- DT::renderDT({
      readable_datatable(
        displayed(),
        rownames = FALSE,
        filter = "top",
        extensions = "Buttons",
        options = list(
          pageLength = 25,
          scrollX = TRUE,
          deferRender = TRUE,
          dom = "Bfrtip",
          buttons = c("colvis")
        )
      )
    })
    output$download_tsv <- shiny::downloadHandler(
      filename = function() {
        paste0("top_", input$top_n %||% 200L, "_prestructure_ranked_hogs.tsv")
      },
      content = function(path) {
        human_hog_write_tsv(data = displayed(), path = path)
      }
    )
    output$download_excel <- shiny::downloadHandler(
      filename = function() {
        paste0("top_", input$top_n %||% 200L, "_prestructure_ranked_hogs.xlsx")
      },
      content = function(path) {
        write_formatted_excel(
          data = displayed(),
          path = path,
          sheet_name = "Ranked HOGs"
        )
      }
    )
    invisible(displayed)
  })
}
