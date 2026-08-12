#' Linked candidate and expression visualisation module.

#' Candidate visualisation UI.
#'
#' @param id Module identifier.
#' @return Shiny UI.
candidate_visualisations_ui <- function(id) {
  ns <- shiny::NS(id)
  bslib::navset_card_tab(
    bslib::nav_panel(
      "Candidate landscape",
      shiny::h2("Interactive candidate landscape"),
      shiny::p(
        class = "text-muted",
        paste(
          "Choose documented evidence scales for each visual dimension.",
          "Selecting a point links the candidate evidence and expression views."
        )
      ),
      shiny::textOutput(ns("candidate_relation_caption")),
      bslib::layout_columns(
        shiny::selectInput(ns("x_metric"), "X-axis", choices = "Loading..."),
        shiny::selectInput(ns("y_metric"), "Y-axis", choices = "Loading..."),
        shiny::selectInput(ns("colour_metric"), "Point colour", choices = "Loading..."),
        shiny::selectInput(ns("size_metric"), "Point size", choices = "Loading..."),
        col_widths = c(3, 3, 3, 3)
      ),
      shinycssloaders::withSpinner(
        plotly::plotlyOutput(ns("candidate_landscape"), height = "650px")
      ),
      shiny::selectizeInput(
        ns("selected_candidate"),
        "Selected candidate",
        choices = "Loading..."
      ),
      shiny::h4("Selected candidate summary"),
      DT::DTOutput(ns("selected_candidate_table")),
      shiny::hr(),
      shiny::h4("Evidence rows behind the selected candidate"),
      bslib::layout_columns(
        shiny::selectInput(
          ns("evidence_relation"),
          "Supporting evidence table",
          choices = "Loading..."
        ),
        shiny::numericInput(
          ns("evidence_rows"),
          "Maximum supporting rows",
          value = 1000,
          min = 1,
          max = 10000
        ),
        col_widths = c(8, 4)
      ),
      tabular_download_buttons(
        ns = ns,
        tsv_id = "download_candidate_evidence",
        excel_id = "download_candidate_evidence_excel",
        tsv_label = "Download selected candidate evidence as TSV",
        excel_label = "Download selected candidate evidence as Excel"
      ),
      shinycssloaders::withSpinner(DT::DTOutput(ns("candidate_evidence_table")))
    ),
    bslib::nav_panel(
      "Expression heatmap",
      shiny::h2("Cross-species expression heatmap"),
      shiny::p(
        class = "text-muted",
        paste(
          "Each cell is the median for one candidate, species and biological",
          "context. Blank cells are unavailable mapped contexts, not measured zero."
        )
      ),
      shiny::selectizeInput(
        ns("heatmap_candidates"),
        "Candidate groups (maximum 25)",
        choices = character(),
        multiple = TRUE
      ),
      bslib::layout_columns(
        shiny::selectInput(ns("heatmap_context"), "Heatmap context", choices = "Loading..."),
        shiny::selectInput(ns("heatmap_unit"), "Expression unit", choices = "Loading..."),
        shiny::selectInput(ns("heatmap_species"), "Species", choices = "All species"),
        shiny::checkboxInput(
          ns("heatmap_log"),
          "Use log2(1 + expression)",
          value = TRUE
        ),
        col_widths = c(3, 3, 3, 3)
      ),
      shinycssloaders::withSpinner(
        plotly::plotlyOutput(ns("expression_heatmap"), height = "750px")
      ),
      tabular_download_buttons(
        ns = ns,
        tsv_id = "download_heatmap_cells",
        excel_id = "download_heatmap_cells_excel",
        tsv_label = "Download expression heatmap cells as TSV",
        excel_label = "Download expression heatmap cells as Excel"
      ),
      shiny::h4("Aggregated heatmap cells"),
      DT::DTOutput(ns("heatmap_table"))
    ),
    bslib::nav_panel(
      "Species & tissue expression",
      shiny::h2("Linked species and tissue expression profiles"),
      shiny::p(
        class = "text-muted",
        paste(
          "Inspect every available tissue-annotated Atlas context separately",
          "for each species. The plot aggregates all matching contexts before",
          "the exact-row display limit is applied."
        )
      ),
      shiny::selectizeInput(
        ns("profile_candidate"),
        "Candidate group",
        choices = character()
      ),
      bslib::layout_columns(
        shiny::selectInput(ns("profile_unit"), "Expression unit", choices = "Loading..."),
        shiny::selectInput(ns("profile_species"), "Species filter", choices = "All species"),
        shiny::checkboxInput(
          ns("profile_log"),
          "Use log2(1 + expression)",
          value = TRUE
        ),
        shiny::numericInput(
          ns("profile_rows"),
          "Maximum exact source rows",
          value = 10000,
          min = 100,
          max = 50000,
          step = 100
        ),
        col_widths = c(3, 3, 3, 3)
      ),
      shinycssloaders::withSpinner(
        plotly::plotlyOutput(ns("species_tissue_profile"), height = "900px")
      ),
      shiny::h4("Group-level expression evidence states"),
      DT::DTOutput(ns("profile_evidence_states")),
      shiny::h4("Aggregated species/tissue profile"),
      DT::DTOutput(ns("profile_summary_table")),
      tabular_download_buttons(
        ns = ns,
        tsv_id = "download_profile_rows",
        excel_id = "download_profile_rows_excel",
        tsv_label = "Download exact species/tissue expression rows as TSV",
        excel_label = "Download exact species/tissue expression rows as Excel"
      ),
      shiny::h4("Exact Expression Atlas rows behind the profile"),
      shiny::uiOutput(ns("profile_limit_notice")),
      DT::DTOutput(ns("profile_rows_table"))
    ),
    bslib::nav_panel(
      "Volcano eligibility",
      shiny::h2("Differential-expression volcano plot"),
      shiny::uiOutput(ns("volcano_availability")),
      bslib::layout_columns(
        shiny::selectInput(
          ns("volcano_relation"),
          "Differential-expression relation",
          choices = character()
        ),
        shiny::numericInput(
          ns("volcano_effect"),
          "Absolute log2 fold-change threshold",
          value = 1.0,
          min = 0,
          max = 20,
          step = 0.1
        ),
        shiny::numericInput(
          ns("volcano_significance"),
          "Significance threshold",
          value = 0.05,
          min = 0.000001,
          max = 1,
          step = 0.01
        ),
        col_widths = c(6, 3, 3)
      ),
      shinycssloaders::withSpinner(
        plotly::plotlyOutput(ns("volcano_plot"), height = "700px")
      ),
      tabular_download_buttons(
        ns = ns,
        tsv_id = "download_volcano_rows",
        excel_id = "download_volcano_rows_excel",
        tsv_label = "Download plotted differential-expression rows as TSV",
        excel_label = "Download plotted differential-expression rows as Excel"
      ),
      DT::DTOutput(ns("volcano_table"))
    )
  )
}

#' Candidate visualisation server.
#'
#' @param id Module identifier.
#' @param resource_source Flexible E3 result source.
#' @param max_rows Global display-row limit.
#' @return Reactive containing the selected candidate row.
candidate_visualisations_server <- function(
  id,
  resource_source,
  max_rows = 1000L
) {
  shiny::moduleServer(id, function(input, output, session) {
    candidate_relation <- shiny::reactiveVal(NULL)
    candidate_columns <- shiny::reactiveVal(character())
    candidate_data <- shiny::reactiveVal(tibble::tibble())
    candidate_identifier <- shiny::reactiveVal(NULL)
    candidate_rank <- shiny::reactiveVal(NULL)
    expression_columns <- shiny::reactiveVal(character())
    expression_link <- shiny::reactiveVal(NULL)
    differential_capabilities <- shiny::reactiveVal(tibble::tibble())
    plot_source <- paste0("candidate_landscape_", id)
    expression_relation <- "candidate_expression_context_summary"

    initialise_visualisations <- function() {
      if (!resource_source_available(resource_source)) {
        shiny::showNotification(
          "No E3 result source is configured for visualisation.",
          type = "error",
          duration = NULL
        )
        return(invisible(NULL))
      }
      relations <- collect_resource_view_names(duckdb_path = resource_source)
      relation <- select_candidate_visual_relation(relations = relations)
      if (is.null(relation)) {
        shiny::showNotification(
          "No recognised candidate-level relation is available.",
          type = "error",
          duration = NULL
        )
        return(invisible(NULL))
      }
      columns <- as.character(
        collect_resource_columns(
          duckdb_path = resource_source,
          view_name = relation
        )$column_name
      )
      required <- candidate_visual_required_columns(columns = columns)
      identifier <- select_candidate_visual_identifier(columns = columns)
      rank_column <- select_candidate_visual_rank(columns = columns)
      metrics <- candidate_visual_available_metrics(columns = columns)
      colours <- candidate_visual_colour_choices(columns = columns)
      collected <- collect_candidate_visual_data(
        resource_source = resource_source,
        relation = relation,
        columns = required,
        max_rows = 5000L
      )
      prepared <- prepare_candidate_visual_data(
        candidate_tbl = collected,
        identifier_column = identifier,
        metric_columns = unname(metrics)
      )
      candidate_relation(relation)
      candidate_columns(columns)
      candidate_data(prepared)
      candidate_identifier(identifier)
      candidate_rank(rank_column)
      default_x <- if ("expression_species_fraction" %in% metrics) {
        "expression_species_fraction"
      } else {
        unname(metrics[[1L]])
      }
      default_y <- if ("final_score" %in% metrics) {
        "final_score"
      } else {
        unname(metrics[[min(2L, length(metrics))]])
      }
      shiny::updateSelectInput(
        session,
        "x_metric",
        choices = metrics,
        selected = default_x
      )
      shiny::updateSelectInput(
        session,
        "y_metric",
        choices = metrics,
        selected = default_y
      )
      shiny::updateSelectInput(
        session,
        "colour_metric",
        choices = c("Single colour" = "", colours),
        selected = ""
      )
      shiny::updateSelectInput(
        session,
        "size_metric",
        choices = c("Fixed size" = "", metrics),
        selected = ""
      )
      candidate_choices <- candidate_visual_display_choices(
        candidate_tbl = prepared,
        rank_column = rank_column
      )
      shiny::updateSelectizeInput(
        session,
        "selected_candidate",
        choices = candidate_choices,
        selected = unname(candidate_choices[[1L]]),
        server = TRUE
      )

      if (expression_relation %in% relations) {
        expr_columns <- as.character(
          collect_resource_columns(
            duckdb_path = resource_source,
            view_name = expression_relation
          )$column_name
        )
        link_column <- candidate_expression_link_column(
          candidate_columns = columns,
          expression_columns = expr_columns
        )
        expression_columns(expr_columns)
        expression_link(link_column)
        if (!is.null(link_column)) {
          expression_values <- trimws(as.character(prepared[[link_column]]))
          keep <- !is.na(expression_values) & nzchar(expression_values)
          expression_values <- expression_values[keep]
          expression_values <- expression_values[!duplicated(expression_values)]
          if (length(expression_values) > 0L) {
            expression_choices <- stats::setNames(
              expression_values,
              expression_values
            )
            default_heatmap <- head(expression_values, 10L)
            shiny::updateSelectizeInput(
              session,
              "heatmap_candidates",
              choices = expression_choices,
              selected = default_heatmap,
              server = TRUE
            )
            shiny::updateSelectizeInput(
              session,
              "profile_candidate",
              choices = expression_choices,
              selected = expression_values[[1L]],
              server = TRUE
            )
          }
        }
        contexts <- candidate_expression_context_choices(
          expression_columns = expr_columns
        )
        units <- collect_distinct_result_values(
          resource_source = resource_source,
          relation = expression_relation,
          column = "expression_unit"
        )
        species <- collect_distinct_result_values(
          resource_source = resource_source,
          relation = expression_relation,
          column = "species_column"
        )
        if (length(contexts) > 0L) {
          shiny::updateSelectInput(
            session,
            "heatmap_context",
            choices = contexts,
            selected = unname(contexts[[1L]])
          )
        }
        if (length(units) > 0L) {
          shiny::updateSelectInput(
            session,
            "heatmap_unit",
            choices = units,
            selected = units[[1L]]
          )
          shiny::updateSelectInput(
            session,
            "profile_unit",
            choices = units,
            selected = units[[1L]]
          )
        }
        species_choices <- c("All species" = "", species)
        shiny::updateSelectInput(
          session,
          "heatmap_species",
          choices = species_choices,
          selected = ""
        )
        shiny::updateSelectInput(
          session,
          "profile_species",
          choices = species_choices,
          selected = ""
        )
      }

      capabilities <- detect_candidate_differential_relations(
        resource_source = resource_source
      )
      differential_capabilities(capabilities)
      if (nrow(capabilities) > 0L) {
        labels <- paste0(
          capabilities$relation,
          " — ", capabilities$effect_column,
          " versus ", capabilities$significance_column
        )
        shiny::updateSelectInput(
          session,
          "volcano_relation",
          choices = stats::setNames(capabilities$relation, labels),
          selected = capabilities$relation[[1L]]
        )
      }
      invisible(prepared)
    }

    shiny::observeEvent(TRUE, {
      tryCatch(
        initialise_visualisations(),
        error = function(error) {
          shiny::showNotification(
            paste("Could not initialise visualisations:", conditionMessage(error)),
            type = "error",
            duration = NULL
          )
        }
      )
    }, once = TRUE)

    output$candidate_relation_caption <- shiny::renderText({
      shiny::req(candidate_relation())
      paste0(
        "Authoritative relation: ", candidate_relation(), "; ",
        format(nrow(candidate_data()), big.mark = ","),
        " distinct candidate groups loaded."
      )
    })

    output$candidate_landscape <- plotly::renderPlotly({
      shiny::req(
        nrow(candidate_data()) > 0L,
        input$x_metric,
        input$y_metric
      )
      build_candidate_visual_landscape_plot(
        candidate_tbl = candidate_data(),
        x_column = input$x_metric,
        y_column = input$y_metric,
        colour_column = input$colour_metric %||% "",
        size_column = input$size_metric %||% "",
        source = plot_source
      )
    })

    shiny::observeEvent(
      plotly::event_data("plotly_click", source = plot_source),
      {
        clicked <- plotly::event_data("plotly_click", source = plot_source)
        key <- clicked$key %||% clicked$customdata
        if (!is.null(key) && nzchar(as.character(key[[1L]]))) {
          shiny::updateSelectizeInput(
            session,
            "selected_candidate",
            selected = as.character(key[[1L]])
          )
        }
      },
      ignoreNULL = TRUE
    )

    selected_candidate <- shiny::reactive({
      shiny::req(input$selected_candidate, nrow(candidate_data()) > 0L)
      selected <- candidate_data() |>
        dplyr::filter(.data$.candidate_key == input$selected_candidate) |>
        dplyr::slice_head(n = 1L)
      shiny::req(nrow(selected) == 1L)
      selected
    })

    shiny::observeEvent(selected_candidate(), {
      row <- selected_candidate()
      identifiers <- candidate_visual_identifiers(candidate_row = row)
      relations <- tryCatch(
        candidate_visual_evidence_relations(
          resource_source = resource_source,
          identifiers = identifiers
        ),
        error = function(error) character()
      )
      shiny::updateSelectInput(
        session,
        "evidence_relation",
        choices = relations,
        selected = if (length(relations) == 0L) character() else relations[[1L]]
      )
      link_column <- expression_link()
      if (!is.null(link_column) && link_column %in% names(row)) {
        linked <- trimws(as.character(row[[link_column]][[1L]]))
        if (nzchar(linked)) {
          shiny::updateSelectizeInput(
            session,
            "profile_candidate",
            selected = linked
          )
          current_heatmap <- input$heatmap_candidates %||% character()
          linked_heatmap <- unique(c(linked, current_heatmap))
          shiny::updateSelectizeInput(
            session,
            "heatmap_candidates",
            selected = head(linked_heatmap, 25L)
          )
        }
      }
    })

    output$selected_candidate_table <- DT::renderDT({
      row <- selected_candidate()
      preferred <- c(
        candidate_rank(),
        candidate_identifier(),
        "primary_group_id",
        "cluster_id",
        "candidate_accessions",
        "final_score",
        "prestructure_score",
        "target_species_fraction",
        "domain_species_fraction",
        "expression_species_fraction",
        "expression_evidence_coverage_fraction",
        "ligandability_score",
        "pocket_conservation_score",
        "structural_species_fraction",
        "recommendation_status",
        "grant_aligned_prediction_status",
        "inclusion_reasons",
        "exclusion_reasons",
        "missing_evidence"
      )
      preferred <- unique(preferred[preferred %in% names(row)])
      readable_datatable(
        row[, preferred, drop = FALSE],
        rownames = FALSE,
        options = list(scrollX = TRUE, pageLength = 1L)
      )
    })

    candidate_evidence <- shiny::reactive({
      shiny::req(input$evidence_relation)
      collect_candidate_visual_evidence(
        resource_source = resource_source,
        relation = input$evidence_relation,
        identifiers = candidate_visual_identifiers(
          candidate_row = selected_candidate()
        ),
        max_rows = min(
          as.integer(input$evidence_rows %||% max_rows),
          10000L
        )
      )
    })

    output$candidate_evidence_table <- DT::renderDT({
      readable_datatable(
        candidate_evidence(),
        rownames = FALSE,
        filter = "top",
        options = list(pageLength = 25L, scrollX = TRUE, deferRender = TRUE)
      )
    })

    output$download_candidate_evidence <- shiny::downloadHandler(
      filename = function() {
        paste0(
          gsub("[^A-Za-z0-9_.-]", "_", input$selected_candidate),
          "_", input$evidence_relation, ".tsv"
        )
      },
      content = function(file) {
        utils::write.table(
          candidate_evidence(),
          file = file,
          sep = "\t",
          row.names = FALSE,
          quote = TRUE,
          na = ""
        )
      }
    )
    output$download_candidate_evidence_excel <- shiny::downloadHandler(
      filename = function() {
        paste0(
          gsub("[^A-Za-z0-9_.-]", "_", input$selected_candidate),
          "_", input$evidence_relation, ".xlsx"
        )
      },
      content = function(file) {
        write_formatted_excel(
          data = candidate_evidence(),
          path = file
        )
      }
    )

    heatmap_data <- shiny::reactive({
      shiny::req(
        expression_link(),
        length(input$heatmap_candidates) > 0L,
        input$heatmap_context,
        input$heatmap_unit
      )
      selected <- head(unique(input$heatmap_candidates), 25L)
      collect_candidate_expression_heatmap(
        resource_source = resource_source,
        relation = expression_relation,
        candidate_column = expression_link(),
        candidate_ids = selected,
        context_column = input$heatmap_context,
        expression_unit = input$heatmap_unit,
        species = input$heatmap_species %||% ""
      )
    })

    output$expression_heatmap <- plotly::renderPlotly({
      plot <- build_candidate_expression_heatmap_plot(
        expression_tbl = heatmap_data(),
        log_transform = isTRUE(input$heatmap_log)
      )
      plotly::ggplotly(plot, tooltip = "text")
    })

    output$heatmap_table <- DT::renderDT({
      readable_datatable(
        heatmap_data(),
        rownames = FALSE,
        filter = "top",
        options = list(pageLength = 25L, scrollX = TRUE)
      )
    })

    output$download_heatmap_cells <- shiny::downloadHandler(
      filename = function() "candidate_expression_heatmap_cells.tsv",
      content = function(file) {
        utils::write.table(
          heatmap_data(),
          file = file,
          sep = "\t",
          row.names = FALSE,
          quote = TRUE,
          na = ""
        )
      }
    )
    output$download_heatmap_cells_excel <- shiny::downloadHandler(
      filename = function() "candidate_expression_heatmap_cells.xlsx",
      content = function(file) {
        write_formatted_excel(
          data = heatmap_data(),
          path = file
        )
      }
    )

    profile_rows <- shiny::reactive({
      shiny::req(
        expression_link(),
        input$profile_candidate,
        input$profile_unit
      )
      collect_candidate_expression_profile(
        resource_source = resource_source,
        relation = expression_relation,
        candidate_column = expression_link(),
        candidate_id = input$profile_candidate,
        expression_unit = input$profile_unit,
        species = input$profile_species %||% "",
        max_rows = min(as.integer(input$profile_rows %||% 10000L), 50000L)
      )
    })

    profile_summary <- shiny::reactive({
      shiny::req(
        expression_link(),
        input$profile_candidate,
        input$profile_unit
      )
      summary <- collect_candidate_species_tissue_summary(
        resource_source = resource_source,
        relation = expression_relation,
        candidate_column = expression_link(),
        candidate_id = input$profile_candidate,
        expression_unit = input$profile_unit,
        species = input$profile_species %||% ""
      )
      prepare_candidate_species_tissue_summary(
        summary_tbl = summary,
        log_transform = isTRUE(input$profile_log)
      )
    })

    output$species_tissue_profile <- plotly::renderPlotly({
      plot <- build_candidate_species_tissue_plot(
        profile_tbl = profile_summary(),
        expression_unit = input$profile_unit,
        log_transform = isTRUE(input$profile_log)
      )
      plotly::ggplotly(plot, tooltip = "text")
    })

    output$profile_evidence_states <- DT::renderDT({
      shiny::req(input$profile_candidate, expression_link())
      row <- candidate_data() |>
        dplyr::filter(.data[[expression_link()]] == input$profile_candidate) |>
        dplyr::slice_head(n = 1L)
      preferred <- c(
        "expression_supported_species",
        "expression_assessed_negative_species",
        "expression_unavailable_species",
        "lead_expression_supported_species",
        "lead_expression_assessed_negative_species",
        "lead_expression_unavailable_species",
        "expression_species_fraction",
        "expression_evidence_coverage_fraction"
      )
      preferred <- preferred[preferred %in% names(row)]
      if (length(preferred) == 0L) {
        return(readable_datatable(
          tibble::tibble(
            evidence_state = "No group-level expression-state columns available"
          ),
          rownames = FALSE
        ))
      }
      readable_datatable(
        row[, preferred, drop = FALSE],
        rownames = FALSE,
        options = list(scrollX = TRUE, pageLength = 1L)
      )
    })

    output$profile_summary_table <- DT::renderDT({
      readable_datatable(
        profile_summary(),
        rownames = FALSE,
        filter = "top",
        options = list(pageLength = 25L, scrollX = TRUE)
      )
    })

    output$profile_rows_table <- DT::renderDT({
      readable_datatable(
        profile_rows(),
        rownames = FALSE,
        filter = "top",
        options = list(pageLength = 25L, scrollX = TRUE, deferRender = TRUE)
      )
    })

    output$profile_limit_notice <- shiny::renderUI({
      limit <- min(as.integer(input$profile_rows %||% 10000L), 50000L)
      if (nrow(profile_rows()) < limit) {
        return(NULL)
      }
      shiny::div(
        class = "alert alert-info",
        paste(
          "The exact-row table reached its selected display/download limit.",
          "The plotted species/tissue summary remains complete because it was",
          "aggregated before that limit."
        )
      )
    })

    output$download_profile_rows <- shiny::downloadHandler(
      filename = function() {
        paste0(
          gsub("[^A-Za-z0-9_.-]", "_", input$profile_candidate),
          "_species_tissue_expression.tsv"
        )
      },
      content = function(file) {
        utils::write.table(
          profile_rows(),
          file = file,
          sep = "\t",
          row.names = FALSE,
          quote = TRUE,
          na = ""
        )
      }
    )
    output$download_profile_rows_excel <- shiny::downloadHandler(
      filename = function() {
        paste0(
          gsub("[^A-Za-z0-9_.-]", "_", input$profile_candidate),
          "_species_tissue_expression.xlsx"
        )
      },
      content = function(file) {
        write_formatted_excel(
          data = profile_rows(),
          path = file
        )
      }
    )

    output$volcano_availability <- shiny::renderUI({
      capabilities <- differential_capabilities()
      if (nrow(capabilities) == 0L) {
        return(shiny::div(
          class = "alert alert-info",
          paste(
            "This release contains absolute Expression Atlas context summaries,",
            "not candidate-level differential tests with both log2 fold changes",
            "and P/FDR/Q values. A volcano plot would be statistically invalid",
            "and is not fabricated. This view activates automatically when a",
            "future release includes the required fields."
          )
        ))
      }
      shiny::div(
        class = "alert alert-success",
        "A valid effect-size and significance relation is available."
      )
    })

    selected_volcano_capability <- shiny::reactive({
      capabilities <- differential_capabilities()
      shiny::req(nrow(capabilities) > 0L, input$volcano_relation)
      selected <- capabilities |>
        dplyr::filter(.data$relation == input$volcano_relation) |>
        dplyr::slice_head(n = 1L)
      shiny::req(nrow(selected) == 1L)
      selected
    })

    volcano_rows <- shiny::reactive({
      collect_resource_query(
        duckdb_path = resource_source,
        query = build_candidate_volcano_query(
          capability = selected_volcano_capability()
        )
      )
    })

    output$volcano_plot <- plotly::renderPlotly({
      capability <- selected_volcano_capability()
      plot <- build_candidate_volcano_plot(
        differential_tbl = volcano_rows(),
        effect_threshold = as.numeric(input$volcano_effect),
        significance_threshold = as.numeric(input$volcano_significance),
        significance_label = capability$significance_column[[1L]]
      )
      plotly::ggplotly(plot, tooltip = "text")
    })

    output$volcano_table <- DT::renderDT({
      readable_datatable(
        volcano_rows(),
        rownames = FALSE,
        filter = "top",
        options = list(pageLength = 25L, scrollX = TRUE)
      )
    })

    output$download_volcano_rows <- shiny::downloadHandler(
      filename = function() {
        paste0(input$volcano_relation, "_volcano_rows.tsv")
      },
      content = function(file) {
        utils::write.table(
          volcano_rows(),
          file = file,
          sep = "\t",
          row.names = FALSE,
          quote = TRUE,
          na = ""
        )
      }
    )
    output$download_volcano_rows_excel <- shiny::downloadHandler(
      filename = function() {
        paste0(input$volcano_relation, "_volcano_rows.xlsx")
      },
      content = function(file) {
        write_formatted_excel(
          data = volcano_rows(),
          path = file
        )
      }
    )

    selected_candidate
  })
}
