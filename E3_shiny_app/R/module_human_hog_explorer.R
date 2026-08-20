#' Human-containing HOG exploration module.

#' Build one human-HOG tab.
#'
#' @param id Module identifier.
#' @param plant_required Require at least one curated target-plant member.
#' @return Shiny UI.
human_hog_explorer_ui <- function(id, plant_required = FALSE) {
  ns <- shiny::NS(id)
  title <- if (isTRUE(plant_required)) {
    "Plant and human HOGs"
  } else {
    "Human-containing HOGs"
  }
  description <- if (isTRUE(plant_required)) {
    paste(
      "Root-level phylogenetic N0.HOG groups containing at least one",
      "Homo sapiens sequence and at least one member from the 12 curated",
      "target plant species. Co-membership is not proof that every member",
      "is an E3 ligase."
    )
  } else {
    paste(
      "Every root-level phylogenetic N0.HOG group containing at least one",
      "Homo sapiens sequence. Candidate ranking is attached where available;",
      "an unranked HOG is not interpreted as a biological failure."
    )
  }
  shiny::tagList(
    shiny::h2(title),
    shiny::p(class = "grant-question", description),
    shiny::p(
      class = "small text-muted",
      paste(
        "Every table repeats the HOG-level human, Arabidopsis, rice and barley",
        "representatives.",
        "Values prefer parsed protein accessions, then parsed entries, then raw",
        "identifiers. Multiple representatives are separated by semicolons;",
        "an absent lineage is blank."
      )
    ),
    shiny::checkboxInput(
      ns("load_view"),
      "Load this complete HOG view",
      value = FALSE
    ),
    shiny::p(
      class = "small text-muted",
      paste(
        "Large HOG relations are queried only after this box is selected.",
        "Every table and download is bounded by the selected maximum."
      )
    ),
    bslib::layout_columns(
      shiny::numericInput(
        ns("max_rows"),
        "Maximum rows per table",
        value = 10000,
        min = 100,
        max = 100000,
        step = 1000
      ),
      shiny::textInput(
        ns("filter"),
        "Filter HOGs, human identifiers, seeds or names",
        placeholder = "N0.HOG…, UniProt accession, entry, seed or name"
      ),
      col_widths = c(4, 8)
    ),
    shiny::uiOutput(ns("availability")),
    shiny::uiOutput(ns("metrics")),
    shiny::h3("HOG summary and candidate ranking"),
    tabular_download_buttons(
      ns,
      "download_summary_tsv",
      "download_summary_excel",
      "Download HOG summary as TSV",
      "Download HOG summary as Excel"
    ),
    shinycssloaders::withSpinner(DT::DTOutput(ns("summary_table"))),
    shiny::h3("Human sequence annotations"),
    tabular_download_buttons(
      ns,
      "download_human_tsv",
      "download_human_excel",
      "Download human members as TSV",
      "Download human members as Excel"
    ),
    shinycssloaders::withSpinner(DT::DTOutput(ns("human_table"))),
    shiny::h3("Every member of the qualifying HOGs"),
    shiny::p(
      class = "small text-muted",
      paste(
        "Includes human, target-plant and other named OrthoFinder inputs.",
        "Sequence fields are populated only where the integrated release",
        "published candidate-linked member sequences."
      )
    ),
    tabular_download_buttons(
      ns,
      "download_all_tsv",
      "download_all_excel",
      "Download every member as TSV",
      "Download every member as Excel"
    ),
    shiny::uiOutput(ns("fasta_download_ui")),
    shinycssloaders::withSpinner(DT::DTOutput(ns("all_table")))
  )
}

human_hog_relation_columns <- function(resource_source, relations) {
  result <- list()
  relevant <- intersect(
    c(
      "hierarchical_membership",
      "candidate_group_member_sequences",
      "candidate_identifier_aliases",
      human_hog_ranking_relations()
    ),
    relations
  )
  for (relation in relevant) {
    metadata <- collect_resource_columns(resource_source, relation)
    result[[relation]] <- as.character(metadata$column_name)
  }
  result
}

human_hog_write_tsv <- function(data, path) {
  utils::write.table(
    data,
    file = path,
    sep = "\t",
    row.names = FALSE,
    col.names = TRUE,
    quote = FALSE,
    na = ""
  )
}

human_hog_table_downloads <- function(output, prefix, data, stem) {
  output[[paste0("download_", prefix, "_tsv")]] <- shiny::downloadHandler(
    filename = function() paste0(stem, ".tsv"),
    content = function(file) human_hog_write_tsv(data(), file)
  )
  output[[paste0("download_", prefix, "_excel")]] <- shiny::downloadHandler(
    filename = function() paste0(stem, ".xlsx"),
    content = function(file) {
      write_formatted_excel(data(), file, sheet_name = "HOG selection")
    }
  )
}

human_hog_fasta_data <- function(data) {
  if (!"protein_sequence" %in% names(data)) return(data.frame())
  keep <- !is.na(data$protein_sequence) & nzchar(trimws(data$protein_sequence))
  result <- data[keep, , drop = FALSE]
  if (nrow(result) == 0L) return(result)
  accession <- ifelse(
    is.na(result$parsed_accession) | !nzchar(result$parsed_accession),
    result$raw_identifier,
    result$parsed_accession
  )
  result$fasta_identifier <- paste(
    result$hog_id,
    result$species,
    accession,
    seq_len(nrow(result)),
    sep = "|"
  )
  result
}

#' Serve a human-containing HOG tab.
#'
#' @param id Module identifier.
#' @param resource_source Flexible E3 result source.
#' @param max_rows Global display limit.
#' @param plant_required Require a curated plant member.
#' @return Selected result reactives, invisibly.
human_hog_explorer_server <- function(
  id,
  resource_source,
  max_rows = 1000L,
  plant_required = FALSE
) {
  shiny::moduleServer(id, function(input, output, session) {
    view <- if (isTRUE(plant_required)) "plant_and_human" else "human"
    stem <- if (isTRUE(plant_required)) {
      "plant_and_human_hogs"
    } else {
      "human_hogs"
    }
    metadata <- shiny::reactiveVal(NULL)

    shiny::observeEvent(input$load_view, {
      if (!isTRUE(input$load_view) || !is.null(metadata())) return()
      relations <- collect_resource_view_names(resource_source)
      columns <- human_hog_relation_columns(resource_source, relations)
      ranking <- select_human_hog_ranking_relation(columns)
      membership_required <- c("group_id", "species", "raw_identifier")
      membership_columns <- columns$hierarchical_membership
      missing_membership <- if (is.null(membership_columns)) {
        membership_required
      } else {
        setdiff(membership_required, membership_columns)
      }
      metadata(list(
        relations = relations,
        columns = columns,
        ranking_relation = ranking,
        missing_membership = missing_membership
      ))
      message("Loaded human-HOG relation metadata for view: ", view)
    }, ignoreInit = TRUE)

    raw_results <- shiny::reactive({
      shiny::req(isTRUE(input$load_view))
      info <- metadata()
      shiny::req(!is.null(info))
      if (
        !"hierarchical_membership" %in% info$relations ||
          length(info$missing_membership) > 0L
      ) {
        return(NULL)
      }
      membership_columns <- info$columns$hierarchical_membership
      ranking_columns <- if (is.null(info$ranking_relation)) {
        character()
      } else {
        info$columns[[info$ranking_relation]]
      }
      sequence_available <- "candidate_group_member_sequences" %in% info$relations
      sequence_columns <- if (sequence_available) {
        info$columns$candidate_group_member_sequences
      } else {
        character()
      }
      alias_available <- "candidate_identifier_aliases" %in% info$relations
      alias_columns <- if (alias_available) {
        info$columns$candidate_identifier_aliases
      } else {
        character()
      }
      limit <- max(100L, min(100000L, as.integer(input$max_rows)))
      summary <- collect_resource_query(
        resource_source,
        build_human_hog_summary_query(
          view,
          membership_columns,
          info$ranking_relation,
          ranking_columns,
          limit
        )
      )
      human <- collect_resource_query(
        resource_source,
        build_human_hog_member_query(
          view,
          "human",
          membership_columns,
          info$ranking_relation,
          ranking_columns,
          sequence_available,
          sequence_columns,
          alias_available,
          alias_columns,
          limit
        )
      )
      all <- collect_resource_query(
        resource_source,
        build_human_hog_member_query(
          view,
          "all",
          membership_columns,
          info$ranking_relation,
          ranking_columns,
          sequence_available,
          sequence_columns,
          alias_available,
          alias_columns,
          limit
        )
      )
      message(
        "Collected ", nrow(summary), " HOG summaries and ", nrow(all),
        " member rows for view: ", view
      )
      list(summary = summary, human_members = human, all_members = all)
    })

    selected <- shiny::reactive({
      results <- raw_results()
      shiny::req(!is.null(results))
      filter_human_hog_results(
        results$summary,
        results$human_members,
        results$all_members,
        input$filter
      )
    })

    output$availability <- shiny::renderUI({
      if (!isTRUE(input$load_view)) {
        return(shiny::div(
          class = "alert alert-info",
          "Select ‘Load this complete HOG view’ to run its bounded queries."
        ))
      }
      info <- metadata()
      if (
        is.null(info) ||
          !"hierarchical_membership" %in% info$relations ||
          length(info$missing_membership) > 0L
      ) {
        missing <- if (is.null(info)) {
          c("group_id", "species", "raw_identifier")
        } else {
          info$missing_membership
        }
        return(shiny::div(
          class = "alert alert-warning",
          paste(
            "Complete hierarchical_membership is unavailable.",
            "Unavailable data are never treated as biological absence.",
            "Missing fields:",
            paste(missing, collapse = ", ")
          )
        ))
      }
      source <- if (is.null(info$ranking_relation)) {
        "No HOG-linked candidate ranking is present in this source."
      } else {
        paste0("Candidate-ranking source: ", info$ranking_relation, ".")
      }
      shiny::div(class = "alert alert-secondary", source)
    })

    output$metrics <- shiny::renderUI({
      tables <- selected()
      ranked <- if ("ranking_availability" %in% names(tables$summary)) {
        sum(tables$summary$ranking_availability == "RANKED", na.rm = TRUE)
      } else {
        0L
      }
      plants <- if ("member_class" %in% names(tables$all_members)) {
        sum(tables$all_members$member_class == "TARGET_PLANT", na.rm = TRUE)
      } else {
        0L
      }
      species <- length(unique(stats::na.omit(tables$all_members$species)))
      box <- function(title, value) {
        bslib::value_box(
          title = title,
          value = format(value, big.mark = ",", scientific = FALSE)
        )
      }
      bslib::layout_columns(
        box("HOGs", nrow(tables$summary)),
        box("Human members", nrow(tables$human_members)),
        box("Target-plant members", plants),
        box("HOGs in candidate ranking", ranked),
        box("Species represented", species),
        col_widths = c(2, 2, 2, 3, 3)
      )
    })

    output$summary_table <- DT::renderDT({
      readable_datatable(selected()$summary, rownames = FALSE, filter = "top")
    })
    output$human_table <- DT::renderDT({
      readable_datatable(
        selected()$human_members,
        rownames = FALSE,
        filter = "top"
      )
    })
    output$all_table <- DT::renderDT({
      readable_datatable(
        selected()$all_members,
        rownames = FALSE,
        filter = "top"
      )
    })

    human_hog_table_downloads(
      output,
      "summary",
      shiny::reactive(selected()$summary),
      paste0(stem, "_summary")
    )
    human_hog_table_downloads(
      output,
      "human",
      shiny::reactive(selected()$human_members),
      paste0(stem, "_human_members")
    )
    human_hog_table_downloads(
      output,
      "all",
      shiny::reactive(selected()$all_members),
      paste0(stem, "_all_members")
    )

    fasta <- shiny::reactive(human_hog_fasta_data(selected()$all_members))
    output$fasta_download_ui <- shiny::renderUI({
      if (nrow(fasta()) == 0L) {
        return(shiny::p(
          class = "small text-muted",
          "No published member sequences are available for this selection."
        ))
      }
      shiny::downloadButton(
        session$ns("download_fasta"),
        "Download available member protein sequences as FASTA"
      )
    })
    output$download_fasta <- shiny::downloadHandler(
      filename = function() paste0(stem, "_available_member_sequences.fasta"),
      content = function(file) {
        data <- fasta()
        text <- data_frame_to_fasta(
          data,
          "fasta_identifier",
          "protein_sequence",
          c("species", "raw_identifier")
        )
        writeLines(text, file, useBytes = TRUE)
      }
    )

    invisible(selected)
  })
}
