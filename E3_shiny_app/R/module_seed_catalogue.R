#' Dedicated inherited E3 seed catalogue module.

#' Build the E3 seed catalogue tab.
#'
#' @param id Module identifier.
#' @return Shiny UI.
seed_catalogue_ui <- function(id) {
  ns <- shiny::NS(id)
  shiny::tagList(
    shiny::h2("E3 seed catalogue"),
    shiny::div(
      class = "alert alert-info",
      paste(
        "This is the inherited known-E3 seed set used by sequence discovery.",
        "The exact known_e3_seeds authority is preferred when published;",
        "otherwise matched identifiers are reconstructed from candidate summaries",
        "and their annotations are labelled as cluster-associated. A protein",
        "sequence is shown only when the same seed identifier reconciles to a",
        "sequence-bearing HOG member in the loaded resource."
      )
    ),
    bslib::layout_columns(
      shiny::numericInput(
        ns("max_rows"),
        "Maximum seed records (up to 100,000)",
        value = 1000,
        min = 1,
        max = 100000,
        step = 100
      ),
      shiny::textAreaInput(
        ns("filter"),
        "Filter seed identifiers, names or annotations",
        placeholder = "One or several terms separated by new lines, commas or tabs",
        rows = 3
      ),
      col_widths = c(3, 9)
    ),
    shiny::uiOutput(ns("availability")),
    bslib::layout_columns(
      bslib::value_box(
        "Seed records shown",
        shiny::textOutput(ns("seed_count"))
      ),
      bslib::value_box(
        "Seeds with an exact sequence",
        shiny::textOutput(ns("sequence_count"))
      ),
      bslib::value_box(
        "Seed-to-cluster links",
        shiny::textOutput(ns("cluster_count"))
      )
    ),
    tabular_download_buttons(
      ns,
      "download_tsv",
      "download_excel",
      "Download seed catalogue as TSV",
      "Download seed catalogue as Excel"
    ),
    shiny::uiOutput(ns("fasta_download_ui")),
    shinycssloaders::withSpinner(DT::DTOutput(ns("seed_table")))
  )
}

#' Serve the E3 seed catalogue tab.
#'
#' @param id Module identifier.
#' @param resource_source Flexible E3 result source.
#' @param max_rows Global bounded row cap.
#' @return Displayed seed catalogue reactive, invisibly.
seed_catalogue_server <- function(id, resource_source, max_rows = 1000L) {
  shiny::moduleServer(id, function(input, output, session) {
    context <- shiny::reactive({
      if (!resource_source_available(resource_source = resource_source)) {
        return(seed_catalogue_capability(relation_columns = list()))
      }
      relations <- collect_resource_view_names(duckdb_path = resource_source)
      relevant <- intersect(
        c(
          seed_catalogue_authority_relation(),
          seed_catalogue_summary_relation_preference(),
          "candidate_group_member_sequences"
        ),
        relations
      )
      columns <- list()
      for (relation in relevant) {
        metadata <- collect_resource_columns(
          duckdb_path = resource_source,
          view_name = relation
        )
        columns[[relation]] <- as.character(metadata$column_name)
      }
      seed_catalogue_capability(relation_columns = columns)
    })

    catalogue <- shiny::reactive({
      capability <- context()
      if (!isTRUE(capability$available)) return(tibble::tibble())
      requested <- suppressWarnings(as.integer(input$max_rows %||% max_rows))
      if (length(requested) != 1L || is.na(requested)) {
        requested <- as.integer(max_rows)
      }
      requested <- min(max(requested, 1L), 100000L)
      tryCatch(
        collect_seed_catalogue(
          duckdb_path = resource_source,
          capability = capability,
          max_rows = requested
        ),
        error = function(error) {
          message("Could not collect the E3 seed catalogue: ", conditionMessage(error))
          shiny::showNotification(
            paste("Could not collect the E3 seed catalogue:", error$message),
            type = "error",
            duration = NULL
          )
          tibble::tibble()
        }
      )
    })

    displayed <- shiny::reactive({
      filter_seed_catalogue(data = catalogue(), query = input$filter %||% "")
    })

    output$availability <- shiny::renderUI({
      capability <- context()
      if (!isTRUE(capability$available)) {
        return(shiny::div(
          class = "alert alert-warning",
          paste(
            "The loaded release has no seed-level evidence relation.",
            "No seed catalogue is inferred from unrelated candidate identifiers."
          )
        ))
      }
      shiny::p(
        class = "small text-muted",
        paste0(
          "Catalogue source: `", capability$relation,
          "` (", capability$mode, "). Exact authority fields and cluster-associated ",
          "fallback fields are kept separate rather than silently relabelled."
        )
      )
    })

    output$seed_count <- shiny::renderText({
      format(nrow(displayed()), big.mark = ",")
    })
    output$sequence_count <- shiny::renderText({
      value <- displayed()$sequence_available %||% logical()
      format(sum(value %in% TRUE, na.rm = TRUE), big.mark = ",")
    })
    output$cluster_count <- shiny::renderText({
      value <- displayed()$source_cluster_count %||% numeric()
      format(sum(value, na.rm = TRUE), big.mark = ",", scientific = FALSE)
    })
    output$seed_table <- DT::renderDT({
      readable_datatable(
        displayed(),
        rownames = FALSE,
        filter = "top",
        options = list(pageLength = 25, scrollX = TRUE, deferRender = TRUE)
      )
    })

    output$download_tsv <- shiny::downloadHandler(
      filename = function() "e3_seed_catalogue.tsv",
      content = function(path) human_hog_write_tsv(data = displayed(), path = path)
    )
    output$download_excel <- shiny::downloadHandler(
      filename = function() "e3_seed_catalogue.xlsx",
      content = function(path) {
        write_formatted_excel(
          data = displayed(),
          path = path,
          sheet_name = "E3 seeds"
        )
      }
    )

    fasta <- shiny::reactive({
      data <- displayed()
      if (!all(c("seed_id", "protein_sequence") %in% names(data))) {
        return(tibble::tibble())
      }
      data[
        !is.na(data$protein_sequence) & nzchar(trimws(data$protein_sequence)),
        ,
        drop = FALSE
      ]
    })
    output$fasta_download_ui <- shiny::renderUI({
      if (nrow(fasta()) == 0L) {
        return(shiny::p(
          class = "small text-muted",
          "No exact seed protein sequences are available for this selection."
        ))
      }
      shiny::downloadButton(
        session$ns("download_fasta"),
        "Download available exact seed protein sequences as FASTA"
      )
    })
    output$download_fasta <- shiny::downloadHandler(
      filename = function() "e3_seed_catalogue_sequences.fasta",
      content = function(path) {
        text <- data_frame_to_fasta(
          data = fasta(),
          identifier_column = "seed_id",
          sequence_column = "protein_sequence",
          description_columns = c(
            "seed_protein_names",
            "associated_seed_protein_names",
            "sequence_species",
            "sequence_identifiers"
          )
        )
        writeLines(text, con = path, useBytes = TRUE)
      }
    )
    invisible(displayed)
  })
}
