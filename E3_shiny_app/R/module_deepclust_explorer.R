#' DeepClust and 1KP sequence-neighbourhood panel.

deepclust_onekp_ui <- function(id) {
  ns <- shiny::NS(id)
  shiny::tagList(
    shiny::hr(),
    shiny::h3("DeepClust and 1KP sequence neighbourhoods"),
    shiny::p(
      class = "grant-question",
      paste(
        "This complementary discovery view includes 1KP sequences clustered",
        "by DeepClust. It does not call them OrthoFinder orthologues, and",
        "cluster membership alone does not establish E3 ligase function."
      )
    ),
    shiny::uiOutput(ns("availability")),
    shiny::uiOutput(ns("metrics")),
    shiny::p(class = "small text-muted", shiny::textOutput(ns("source_caption"))),
    bslib::layout_columns(
      shiny::checkboxInput(
        ns("log_onekp_species_axis"),
        "Log-transform 1KP-species axis",
        value = FALSE
      ),
      shiny::checkboxInput(
        ns("log_neighbourhood_count_axis"),
        "Log-transform neighbourhood-count axis",
        value = FALSE
      ),
      col_widths = c(6, 6)
    ),
    shiny::uiOutput(ns("log_notice")),
    shinycssloaders::withSpinner(
      plotly::plotlyOutput(ns("coverage_distribution"), height = "600px")
    ),
    shiny::downloadButton(
      ns("download_coverage_pdf"),
      "Download 1KP coverage graph as PDF"
    ),
    shiny::h4("Filter sequence neighbourhoods"),
    bslib::layout_columns(
      shiny::textAreaInput(
        ns("seed_queries"),
        "Inherited E3 seed identifier(s)",
        value = "",
        placeholder = "One or several identifiers"
      ),
      shiny::radioButtons(
        ns("seed_match_mode"),
        "When several seeds are entered",
        choices = c("Match any entered seed" = "any", "Match every entered seed" = "all"),
        selected = "any",
        inline = TRUE
      ),
      shiny::textInput(
        ns("cluster_query"),
        "DeepClust representative contains",
        value = ""
      ),
      shiny::selectInput(
        ns("onekp_mode"),
        "1KP coverage",
        choices = c(
          "All neighbourhoods, including no 1KP coverage" = "all",
          "At least one raw 1KP member" = "raw",
          "At least one strict 1KP member" = "strict"
        )
      ),
      shiny::numericInput(
        ns("minimum_onekp_species"),
        "Minimum strict parsed 1KP species",
        value = 0,
        min = 0,
        max = 1000000,
        step = 1
      ),
      shiny::numericInput(
        ns("max_rows"),
        "Maximum neighbourhoods to display",
        value = 1000,
        min = 1,
        max = 100000,
        step = 100
      ),
      col_widths = rep(6, 6)
    ),
    tabular_download_buttons(
      ns = ns,
      tsv_id = "download_summary",
      excel_id = "download_summary_excel",
      tsv_label = "Download filtered neighbourhoods as TSV",
      excel_label = "Download filtered neighbourhoods as Excel"
    ),
    shinycssloaders::withSpinner(DT::DTOutput(ns("summary_table"))),
    shiny::p(
      class = "small text-muted",
      paste(
        "The current integrated release publishes cluster-level 1KP counts,",
        "not its full 25-million-sequence member relation. Exact 1KP member",
        "rows therefore remain unavailable here rather than being inferred."
      )
    )
  )
}

deepclust_onekp_server <- function(id, resource_source) {
  shiny::moduleServer(id, function(input, output, session) {
    relations <- shiny::reactiveVal(character())
    columns <- shiny::reactiveVal(character())

    shiny::observeEvent(TRUE, {
      available <- tryCatch(
        collect_resource_view_names(duckdb_path = resource_source),
        error = function(error) character()
      )
      relations(available)
      if ("candidate_evidence" %in% available) {
        fields <- tryCatch(
          collect_resource_columns(
            duckdb_path = resource_source,
            view_name = "candidate_evidence"
          )$column_name,
          error = function(error) character()
        )
        columns(fields)
      }
    }, once = TRUE)

    available <- shiny::reactive({
      "candidate_evidence" %in% relations() &&
        all(deepclust_required_columns() %in% columns())
    })

    output$availability <- shiny::renderUI({
      if (!isTRUE(available())) {
        shiny::div(
          class = "alert alert-info",
          paste(
            "This release lacks the compact candidate-evidence 1KP fields.",
            "Unavailable coverage is not interpreted as zero."
          )
        )
      }
    })

    metrics <- shiny::reactive({
      shiny::req(available())
      collect_resource_query(
        duckdb_path = resource_source,
        query = build_deepclust_metrics_query()
      )
    })

    output$metrics <- shiny::renderUI({
      values <- metrics()
      shiny::req(nrow(values) == 1L)
      metric <- function(label, field, note = NULL) {
        bslib::value_box(
          title = label,
          value = format(values[[field]][[1L]], big.mark = ",", scientific = FALSE),
          showcase = if (!is.null(note)) shiny::span(title = note, "ⓘ")
        )
      }
      bslib::layout_columns(
        metric("E3-seeded neighbourhoods", "cluster_count"),
        metric("Raw cluster-member links", "raw_cluster_member_links"),
        metric("Strict cluster-member links", "strict_cluster_member_links"),
        metric("Neighbourhoods with raw 1KP", "clusters_with_raw_onekp"),
        metric("Neighbourhoods with strict 1KP", "clusters_with_strict_onekp"),
        metric(
          "Strict 1KP cluster-species links",
          "strict_onekp_cluster_species_links",
          "The same parsed species in two clusters contributes two links."
        ),
        col_widths = rep(4, 6)
      )
    })

    output$source_caption <- shiny::renderText({
      shiny::req(available())
      paste(
        "Source: candidate_evidence from the full 1KP+ discovery resource.",
        "Counts are cluster-member, cluster-sample or cluster-species links."
      )
    })

    distribution <- shiny::reactive({
      shiny::req(available())
      collect_resource_query(
        duckdb_path = resource_source,
        query = build_deepclust_distribution_query()
      )
    })

    coverage_plot <- shiny::reactive({
      rows <- distribution()
      if (isTRUE(input$log_onekp_species_axis)) {
        rows <- rows[rows$strict_onekp_species_count > 0, , drop = FALSE]
      }
      plot <- ggplot2::ggplot(
        rows,
        ggplot2::aes(
          x = .data$strict_onekp_species_count,
          y = .data$cluster_count
        )
      ) +
        ggplot2::geom_col(fill = "#0b7a75") +
        ggplot2::labs(
          title = paste(
            "Strict 1KP species coverage across E3-seeded",
            "sequence neighbourhoods"
          ),
          x = "Strict parsed 1KP species in neighbourhood",
          y = "E3-seeded DeepClust neighbourhoods"
        ) +
        ggplot2::theme_minimal(base_size = 12)
      if (isTRUE(input$log_onekp_species_axis)) {
        plot <- plot + ggplot2::scale_x_log10()
      }
      if (isTRUE(input$log_neighbourhood_count_axis)) {
        plot <- plot + ggplot2::scale_y_log10()
      }
      plot
    })

    output$log_notice <- shiny::renderUI({
      if (isTRUE(input$log_onekp_species_axis)) {
        shiny::p(
          class = "small text-muted",
          paste(
            "The log-scaled 1KP-species axis excludes the zero-coverage bin;",
            "turn log x off to restore it."
          )
        )
      }
    })

    output$coverage_distribution <- plotly::renderPlotly({
      plotly::ggplotly(coverage_plot()) |>
        plotly::config(displaylogo = FALSE)
    })

    output$download_coverage_pdf <- shiny::downloadHandler(
      filename = function() "deepclust_onekp_species_coverage.pdf",
      content = function(path) {
        write_ggplot_pdf(plot = coverage_plot(), path = path, width = 12, height = 7)
      }
    )

    contributor_relation <- shiny::reactive({
      candidates <- c(
        "evolutionary_group_cluster_contributors",
        "final_evolutionary_group_cluster_contributors"
      )
      selected <- candidates[candidates %in% relations()]
      if (length(selected) == 0L) {
        return(NULL)
      }
      fields <- tryCatch(
        collect_resource_columns(
          duckdb_path = resource_source,
          view_name = selected[[1L]]
        )$column_name,
        error = function(error) character()
      )
      required <- c(
        "cluster_id",
        "evolutionary_group_key",
        "primary_group_type"
      )
      if (all(required %in% fields)) selected[[1L]] else NULL
    })

    summary <- shiny::reactive({
      shiny::req(available())
      collect_resource_query(
        duckdb_path = resource_source,
        query = build_deepclust_summary_query(
          available_columns = columns(),
          seed_queries = input$seed_queries,
          match_mode = input$seed_match_mode,
          onekp_mode = input$onekp_mode,
          minimum_strict_onekp_species = input$minimum_onekp_species,
          cluster_query = input$cluster_query,
          max_rows = input$max_rows,
          contributor_relation = contributor_relation()
        )
      )
    })

    output$summary_table <- DT::renderDT({
      rows <- summary()
      shiny::validate(shiny::need(
        nrow(rows) > 0L,
        "No DeepClust sequence neighbourhood matches the selected filters."
      ))
      readable_datatable(
        rows,
        rownames = FALSE,
        filter = "top",
        options = list(pageLength = 25, scrollX = TRUE, autoWidth = TRUE)
      )
    })

    output$download_summary <- shiny::downloadHandler(
      filename = function() "deepclust_onekp_sequence_neighbourhoods.tsv",
      content = function(path) {
        utils::write.table(
          summary(),
          file = path,
          sep = "\t",
          quote = FALSE,
          row.names = FALSE,
          na = ""
        )
      }
    )

    output$download_summary_excel <- shiny::downloadHandler(
      filename = function() "deepclust_onekp_sequence_neighbourhoods.xlsx",
      content = function(path) {
        write_formatted_excel(data = summary(), path = path)
      }
    )

    invisible(list(summary = summary, distribution = distribution))
  })
}
