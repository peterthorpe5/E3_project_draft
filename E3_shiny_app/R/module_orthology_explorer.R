#' Expanded OrthoFinder and inherited E3 seed exploration modules.

#' Shared OrthoFinder grouping-level UI.
#'
#' @param input_id Namespaced input identifier.
#' @return Radio-button control.
orthology_group_type_ui <- function(input_id) {
  shiny::tagList(
    shiny::radioButtons(
      inputId = input_id,
      label = "OrthoFinder grouping level",
      choices = stats::setNames(
        c("hierarchical_orthogroup", "orthogroup"),
        c(
          paste0(
            "Root-level phylogenetic HOGs ",
            "(N0.HOG…; recommended)"
          ),
          paste0(
            "Original MCL orthogroups ",
            "(OG…; broader legacy view)"
          )
        )
      ),
      selected = "hierarchical_orthogroup",
      inline = TRUE
    ),
    shiny::p(
      class = "small text-muted",
      paste(
        "HOG means hierarchical orthogroup. N0.HOG… groups reconcile rooted",
        "gene trees with the species tree and are used by final prioritisation;",
        "OG… groups are the original MCL-based Orthogroups.tsv legacy view."
      )
    )
  )
}

#' Expanded Orthology tab UI.
#'
#' @param id Module identifier.
#' @return Shiny UI.
orthology_explorer_ui <- function(id) {
  ns <- shiny::NS(id)
  shiny::tagList(
    shiny::h2("Expanded cross-species orthology"),
    shiny::p(
      class = "grant-question",
      paste(
        "This page summarises OrthoFinder membership independently of",
        "DeepClust. The recommended N0 hierarchical orthogroups are",
        "phylogenetic evolutionary groups; original OG groups are retained as",
        "a legacy MCL view. A DeepClust cluster remains a non-phylogenetic",
        "sequence-neighbourhood input to candidate discovery."
      )
    ),
    orthology_group_type_ui(ns("group_type")),
    shiny::uiOutput(ns("availability")),
    shiny::uiOutput(ns("metrics")),
    shiny::p(class = "small text-muted", shiny::textOutput(ns("source_caption"))),
    bslib::layout_columns(
      shiny::checkboxInput(
        ns("log_group_size_axis"),
        "Log-transform group-size axis",
        value = FALSE
      ),
      shiny::checkboxInput(
        ns("log_group_count_axis"),
        "Log-transform group-count axis",
        value = FALSE
      ),
      col_widths = c(6, 6)
    ),
    shinycssloaders::withSpinner(
      plotly::plotlyOutput(ns("size_distribution"), height = "620px")
    ),
    shiny::downloadButton(
      ns("download_size_distribution_pdf"),
      "Download group-size graph as PDF"
    ),
    shiny::p(
      class = "small text-muted",
      paste(
        "The one-species category is deliberately retained; these groups are",
        "not discarded as uninformative."
      )
    ),
    shiny::h3("Filter OrthoFinder groups"),
    bslib::layout_columns(
      shiny::selectizeInput(
        ns("required_species"),
        "Must contain every selected species",
        choices = character(),
        multiple = TRUE
      ),
      shiny::selectInput(
        ns("breadth"),
        "Species breadth",
        choices = c(
          "All breadth classes" = "all",
          "One species only" = "one_species",
          "Multiple species, but not all" = "multiple_species",
          "Every input species" = "all_species"
        )
      ),
      shiny::selectizeInput(
        ns("taxonomy_roles"),
        "Must contain a member from any selected curated taxonomy role",
        choices = character(),
        multiple = TRUE
      ),
      shiny::selectizeInput(
        ns("taxonomy_taxa"),
        "Curated taxa (any selected taxon)",
        choices = character(),
        multiple = TRUE
      ),
      shiny::checkboxInput(
        ns("seeded_only"),
        "Only groups linked to inherited E3 seed evidence",
        value = FALSE
      ),
      col_widths = c(6, 6, 6, 6, 6)
    ),
    shiny::numericInput(
      ns("max_rows"),
      "Maximum groups to display",
      value = 1000,
      min = 1,
      max = 100000,
      step = 100
    ),
    shiny::p(class = "small text-muted", shiny::textOutput(ns("taxonomy_caption"))),
    tabular_download_buttons(
      ns = ns,
      tsv_id = "download_groups",
      excel_id = "download_groups_excel",
      tsv_label = "Download filtered groups as TSV",
      excel_label = "Download filtered groups as Excel"
    ),
    shinycssloaders::withSpinner(DT::DTOutput(ns("group_table"))),
    bslib::accordion(
      bslib::accordion_panel(
        "Browse the underlying orthology relations",
        result_section_ui(ns("source_tables"), "orthology")
      )
    ),
    deepclust_onekp_ui(ns("deepclust"))
  )
}

#' Expanded Orthology tab server.
#'
#' @param id Module identifier.
#' @param resource_source Flexible E3 result source.
#' @param max_rows Global display-row limit.
#' @return Selected summary and plot reactives, invisibly.
orthology_explorer_server <- function(
  id,
  resource_source,
  max_rows = 1000L
) {
  shiny::moduleServer(id, function(input, output, session) {
    relations <- shiny::reactiveVal(character())
    species <- shiny::reactiveVal(character())
    taxonomy <- load_species_taxonomy()

    deepclust_onekp_server(
      id = "deepclust",
      resource_source = resource_source
    )

    result_section_server(
      id = "source_tables",
      section = "orthology",
      resource_source = resource_source,
      max_rows = max_rows
    )

    shiny::observeEvent(TRUE, {
      available <- tryCatch(
        collect_resource_view_names(duckdb_path = resource_source),
        error = function(error) character()
      )
      relations(available)
    }, once = TRUE)

    relation <- shiny::reactive({
      requested <- orthology_relation_name(input$group_type)
      if (requested %in% relations()) requested else NULL
    })

    seed_relation_available <- shiny::reactive({
      "candidate_group_member_sequences" %in% relations()
    })

    shiny::observeEvent(relation(), {
      shiny::req(!is.null(relation()))
      rows <- collect_resource_query(
        duckdb_path = resource_source,
        query = build_orthology_species_query(relation = relation())
      )
      values <- as.character(rows$species)
      species(values)
      shiny::updateSelectizeInput(
        session,
        "required_species",
        choices = values,
        selected = character(),
        server = TRUE
      )
      represented <- taxonomy[
        taxonomy$source_species_name %in% values,
        ,
        drop = FALSE
      ]
      taxon_labels <- paste0(
        represented$canonical_species_name,
        " (NCBI taxon ",
        represented$taxon_id,
        ")"
      )
      shiny::updateSelectizeInput(
        session,
        "taxonomy_taxa",
        choices = stats::setNames(
          represented$source_species_name,
          taxon_labels
        ),
        selected = character(),
        server = TRUE
      )
      roles <- sort(unique(as.character(represented$role)))
      roles <- roles[!is.na(roles) & nzchar(roles)]
      shiny::updateSelectizeInput(
        session,
        "taxonomy_roles",
        choices = stats::setNames(
          roles,
          tools::toTitleCase(gsub("_", " ", roles))
        ),
        selected = character(),
        server = TRUE
      )
    }, ignoreNULL = TRUE)

    output$availability <- shiny::renderUI({
      if (is.null(relation())) {
        shiny::div(
          class = "alert alert-info",
          paste(
            "The selected membership relation is unavailable in this release.",
            "Unavailable membership is not interpreted as absence."
          )
        )
      }
    })

    metrics <- shiny::reactive({
      shiny::req(!is.null(relation()))
      collect_resource_query(
        duckdb_path = resource_source,
        query = build_orthology_metrics_query(
          relation = relation(),
          seed_relation_available = seed_relation_available()
        )
      )
    })

    output$metrics <- shiny::renderUI({
      values <- metrics()
      if (nrow(values) == 0L) {
        return(shiny::div(class = "alert alert-info", "No membership rows found."))
      }
      metric <- function(label, value, note = NULL) {
        bslib::value_box(
          title = label,
          value = format(value, big.mark = ",", scientific = FALSE),
          showcase = if (!is.null(note)) shiny::span(title = note, "ⓘ")
        )
      }
      bslib::layout_columns(
        metric("Input sequence memberships", values$input_sequences[[1L]]),
        metric("Input species", values$input_species[[1L]]),
        metric("OrthoFinder groups", values$group_count[[1L]]),
        metric("Groups with E3 seed evidence", values$seeded_group_count[[1L]]),
        metric(
          "Groups containing every species",
          values$all_species_group_count[[1L]]
        ),
        metric(
          "Largest group",
          values$largest_group_size[[1L]],
          as.character(values$largest_group_id[[1L]])
        ),
        col_widths = rep(4, 6)
      )
    })

    output$source_caption <- shiny::renderText({
      shiny::req(!is.null(relation()))
      paste0(
        "Source: ", relation(),
        ". Counts refer to the currently selected OrthoFinder grouping level."
      )
    })

    size_data <- shiny::reactive({
      shiny::req(!is.null(relation()))
      collect_resource_query(
        duckdb_path = resource_source,
        query = build_orthology_size_distribution_query(relation = relation())
      )
    })

    size_ggplot <- shiny::reactive({
      rows <- size_data()
      plot <- ggplot2::ggplot(
        rows,
        ggplot2::aes(
          x = .data$member_count,
          y = .data$group_count,
          fill = .data$species_breadth
        )
      ) +
        ggplot2::geom_col() +
        ggplot2::scale_fill_manual(values = c(
          "One species only" = "#8c6bb1",
          "Multiple species (not all)" = "#3182bd",
          "All input species" = "#31a354"
        )) +
        ggplot2::labs(
          title = "OrthoFinder group-size distribution",
          x = "Members in OrthoFinder group",
          y = "Number of groups",
          fill = "Species breadth"
        ) +
        ggplot2::theme_minimal(base_size = 12)
      if (isTRUE(input$log_group_size_axis)) {
        plot <- plot + ggplot2::scale_x_log10()
      }
      if (isTRUE(input$log_group_count_axis)) {
        plot <- plot + ggplot2::scale_y_log10()
      }
      plot
    })

    output$size_distribution <- plotly::renderPlotly({
      plotly::ggplotly(size_ggplot()) |>
        plotly::config(displaylogo = FALSE)
    })

    output$download_size_distribution_pdf <- shiny::downloadHandler(
      filename = function() {
        paste0(input$group_type, "_size_distribution.pdf")
      },
      content = function(path) {
        ggplot2::ggsave(
          filename = path,
          plot = size_ggplot(),
          device = "pdf",
          width = 12,
          height = 7,
          units = "in"
        )
      }
    )

    taxonomy_species <- shiny::reactive({
      selected_roles <- as.character(input$taxonomy_roles %||% character())
      selected_taxa <- as.character(input$taxonomy_taxa %||% character())
      role_species <- taxonomy$source_species_name[
        taxonomy$role %in% selected_roles
      ]
      if (length(selected_roles) > 0L && length(selected_taxa) > 0L) {
        return(intersect(role_species, selected_taxa))
      }
      if (length(selected_roles) > 0L) role_species else selected_taxa
    })

    output$taxonomy_caption <- shiny::renderText({
      mapped <- intersect(species(), taxonomy$source_species_name)
      paste(
        "Curated taxonomy mapping covers",
        length(mapped), "of", length(species()),
        "exact source labels; the remainder stay explicitly unclassified."
      )
    })

    groups <- shiny::reactive({
      shiny::req(!is.null(relation()))
      collect_resource_query(
        duckdb_path = resource_source,
        query = build_orthology_group_summary_query(
          relation = relation(),
          required_species = input$required_species %||% character(),
          taxonomy_species = taxonomy_species(),
          breadth = input$breadth %||% "all",
          seeded_only = isTRUE(input$seeded_only),
          max_rows = input$max_rows %||% max_rows,
          seed_relation_available = seed_relation_available()
        )
      )
    })

    output$group_table <- DT::renderDT({
      table <- groups()
      shiny::validate(shiny::need(nrow(table) > 0L, "No groups match the filters."))
      readable_datatable(
        table,
        rownames = FALSE,
        filter = "top",
        options = list(pageLength = 25, scrollX = TRUE, autoWidth = TRUE)
      )
    })

    output$download_groups <- shiny::downloadHandler(
      filename = function() paste0("filtered_", input$group_type, "_summary.tsv"),
      content = function(path) {
        utils::write.table(
          groups(), path, sep = "\t", quote = FALSE,
          row.names = FALSE, na = ""
        )
      }
    )
    output$download_groups_excel <- shiny::downloadHandler(
      filename = function() paste0("filtered_", input$group_type, "_summary.xlsx"),
      content = function(path) write_formatted_excel(data = groups(), path = path)
    )

    invisible(list(groups = groups, size_plot = size_ggplot, metrics = metrics))
  })
}

#' E3 seed and HOG explorer UI.
#'
#' @param id Module identifier.
#' @return Shiny UI.
seed_group_explorer_ui <- function(id) {
  ns <- shiny::NS(id)
  shiny::tagList(
    shiny::h2("E3 seed and OrthoFinder-group explorer"),
    shiny::p(
      class = "grant-question",
      paste(
        "Select inherited E3 seed identifiers to find their root-level",
        "phylogenetic hierarchical orthogroups or original MCL orthogroups",
        "and inspect every sequence-bearing member. A seed records prior E3",
        "evidence; an unseeded member is not labelled non-E3."
      )
    ),
    orthology_group_type_ui(ns("group_type")),
    bslib::layout_columns(
      shiny::selectizeInput(
        ns("seeds"),
        "E3 seed identifiers",
        choices = character(),
        multiple = TRUE,
        options = list(placeholder = "Search and select one or more seeds")
      ),
      shiny::radioButtons(
        ns("match_mode"),
        "When several seeds are selected",
        choices = c(
          "Return groups containing any selected seed" = "any",
          "Return only groups containing all selected seeds" = "all"
        ),
        selected = "any"
      ),
      col_widths = c(7, 5)
    ),
    shiny::uiOutput(ns("availability")),
    shiny::h3("Matching OrthoFinder groups"),
    tabular_download_buttons(
      ns = ns,
      tsv_id = "download_group_summary",
      excel_id = "download_group_summary_excel",
      tsv_label = "Download matching groups as TSV",
      excel_label = "Download matching groups as Excel"
    ),
    DT::DTOutput(ns("group_summary")),
    bslib::layout_columns(
      shiny::selectizeInput(
        ns("selected_groups"),
        "Groups to inspect",
        choices = character(),
        multiple = TRUE
      ),
      shiny::selectizeInput(
        ns("species"),
        "Filter the member table by species",
        choices = character(),
        multiple = TRUE
      ),
      col_widths = c(6, 6)
    ),
    shiny::h3("Species and members in the selected groups"),
    tabular_download_buttons(
      ns = ns,
      tsv_id = "download_members",
      excel_id = "download_members_excel",
      tsv_label = "Download filtered member table as TSV",
      excel_label = "Download filtered member table as Excel"
    ),
    shiny::downloadButton(
      ns("download_members_fasta"),
      "Download filtered member protein sequences as FASTA"
    ),
    shinycssloaders::withSpinner(DT::DTOutput(ns("member_table"))),
    bslib::accordion(
      bslib::accordion_panel(
        "Associated evidence for one selected group",
        shiny::selectInput(
          ns("evidence_relation"),
          "Evidence relation",
          choices = character()
        ),
        tabular_download_buttons(
          ns = ns,
          tsv_id = "download_evidence",
          excel_id = "download_evidence_excel",
          tsv_label = "Download associated evidence as TSV",
          excel_label = "Download associated evidence as Excel"
        ),
        DT::DTOutput(ns("evidence_table"))
      )
    )
  )
}

#' E3 seed and HOG explorer server.
#'
#' @param id Module identifier.
#' @param resource_source Flexible E3 result source.
#' @param max_rows Global display-row limit.
#' @return Matching-group and filtered-member reactives, invisibly.
seed_group_explorer_server <- function(
  id,
  resource_source,
  max_rows = 1000L
) {
  shiny::moduleServer(id, function(input, output, session) {
    relations <- shiny::reactiveVal(character())

    shiny::observeEvent(TRUE, {
      available <- tryCatch(
        collect_resource_view_names(duckdb_path = resource_source),
        error = function(error) character()
      )
      relations(available)
      if ("candidate_group_member_sequences" %in% available) {
        seed_rows <- collect_resource_query(
          duckdb_path = resource_source,
          query = build_seed_identifiers_query()
        )
        shiny::updateSelectizeInput(
          session,
          "seeds",
          choices = as.character(seed_rows$seed_id),
          selected = character(),
          server = TRUE
        )
      }
    }, once = TRUE)

    relation <- shiny::reactive({
      requested <- orthology_relation_name(input$group_type)
      if (requested %in% relations()) requested else NULL
    })

    shiny::observeEvent(relation(), {
      shiny::req(!is.null(relation()))
      rows <- collect_resource_query(
        duckdb_path = resource_source,
        query = build_orthology_species_query(relation = relation())
      )
      shiny::updateSelectizeInput(
        session,
        "species",
        choices = as.character(rows$species),
        selected = character(),
        server = TRUE
      )
    }, ignoreNULL = TRUE)

    output$availability <- shiny::renderUI({
      if (!"candidate_group_member_sequences" %in% relations()) {
        shiny::div(
          class = "alert alert-info",
          paste(
            "This release has no sequence-bearing seeded-group relation.",
            "Seed search and member FASTA export are unavailable."
          )
        )
      } else if (length(input$seeds %||% character()) == 0L) {
        shiny::div(
          class = "alert alert-info",
          "Select at least one seed identifier to run the group search."
        )
      }
    })

    all_members <- shiny::reactive({
      shiny::req("candidate_group_member_sequences" %in% relations())
      shiny::req(length(input$seeds %||% character()) > 0L)
      collect_resource_query(
        duckdb_path = resource_source,
        query = build_seed_group_members_query(
          seed_identifiers = input$seeds,
          group_type = input$group_type,
          match_mode = input$match_mode,
          max_rows = min(100000L, max(as.integer(max_rows), 10000L))
        )
      )
    })

    group_summary <- shiny::reactive({
      summarise_seed_group_members(all_members())
    })

    shiny::observeEvent(group_summary(), {
      groups <- as.character(group_summary()$primary_group_id)
      shiny::updateSelectizeInput(
        session,
        "selected_groups",
        choices = groups,
        selected = groups,
        server = TRUE
      )
    }, ignoreNULL = TRUE)

    filtered_members <- shiny::reactive({
      rows <- all_members()
      groups <- input$selected_groups %||% character()
      if (length(groups) > 0L) {
        rows <- rows[rows$primary_group_id %in% groups, , drop = FALSE]
      } else {
        rows <- rows[0, , drop = FALSE]
      }
      selected_species <- input$species %||% character()
      if (length(selected_species) > 0L) {
        rows <- rows[rows$species %in% selected_species, , drop = FALSE]
      }
      rows
    })

    output$group_summary <- DT::renderDT({
      table <- group_summary()
      shiny::validate(shiny::need(nrow(table) > 0L, "No matching groups."))
      readable_datatable(table, rownames = FALSE, filter = "top")
    })
    output$member_table <- DT::renderDT({
      table <- filtered_members()
      shiny::validate(shiny::need(nrow(table) > 0L, "No matching members."))
      readable_datatable(
        table,
        rownames = FALSE,
        filter = "top",
        options = list(pageLength = 25, scrollX = TRUE, autoWidth = TRUE)
      )
    })

    output$download_group_summary <- shiny::downloadHandler(
      filename = function() "seed_search_matching_groups.tsv",
      content = function(path) {
        utils::write.table(
          group_summary(), path, sep = "\t", quote = FALSE,
          row.names = FALSE, na = ""
        )
      }
    )
    output$download_group_summary_excel <- shiny::downloadHandler(
      filename = function() "seed_search_matching_groups.xlsx",
      content = function(path) {
        write_formatted_excel(data = group_summary(), path = path)
      }
    )

    member_table_export <- shiny::reactive({
      rows <- filtered_members()
      rows[, setdiff(names(rows), "protein_sequence"), drop = FALSE]
    })
    output$download_members <- shiny::downloadHandler(
      filename = function() "seed_search_group_members.tsv",
      content = function(path) {
        utils::write.table(
          member_table_export(), path, sep = "\t", quote = FALSE,
          row.names = FALSE, na = ""
        )
      }
    )
    output$download_members_excel <- shiny::downloadHandler(
      filename = function() "seed_search_group_members.xlsx",
      content = function(path) {
        write_formatted_excel(data = member_table_export(), path = path)
      }
    )
    output$download_members_fasta <- shiny::downloadHandler(
      filename = function() "seed_search_group_members.fasta",
      content = function(path) {
        rows <- filtered_members()
        rows$fasta_identifier <- paste(
          rows$primary_group_id,
          rows$species,
          rows$internal_id,
          sep = "|"
        )
        fasta <- data_frame_to_fasta(
          data = rows,
          identifier_column = "fasta_identifier",
          sequence_column = "protein_sequence",
          description_columns = c("raw_identifier", "parsed_accession")
        )
        writeBin(charToRaw(enc2utf8(fasta)), con = path)
      }
    )

    evidence_relations <- shiny::reactive({
      groups <- input$selected_groups %||% character()
      if (length(groups) != 1L) {
        return(character())
      }
      candidate_visual_evidence_relations(
        resource_source = resource_source,
        identifiers = c(primary_group_id = groups[[1L]])
      )
    })
    shiny::observeEvent(evidence_relations(), {
      selected_relation <- if (length(evidence_relations()) > 0L) {
        evidence_relations()[[1L]]
      } else {
        character()
      }
      shiny::updateSelectInput(
        session,
        "evidence_relation",
        choices = evidence_relations(),
        selected = selected_relation
      )
    })
    evidence <- shiny::reactive({
      groups <- input$selected_groups %||% character()
      shiny::req(length(groups) == 1L)
      shiny::req(input$evidence_relation %in% evidence_relations())
      collect_candidate_visual_evidence(
        resource_source = resource_source,
        relation = input$evidence_relation,
        identifiers = c(primary_group_id = groups[[1L]]),
        max_rows = min(as.integer(max_rows), 10000L)
      )
    })
    output$evidence_table <- DT::renderDT({
      table <- evidence()
      readable_datatable(table, rownames = FALSE, filter = "top")
    })
    output$download_evidence <- shiny::downloadHandler(
      filename = function() "selected_hog_associated_evidence.tsv",
      content = function(path) {
        utils::write.table(
          evidence(), path, sep = "\t", quote = FALSE,
          row.names = FALSE, na = ""
        )
      }
    )
    output$download_evidence_excel <- shiny::downloadHandler(
      filename = function() "selected_hog_associated_evidence.xlsx",
      content = function(path) write_formatted_excel(data = evidence(), path = path)
    )

    invisible(list(groups = group_summary, members = filtered_members))
  })
}
