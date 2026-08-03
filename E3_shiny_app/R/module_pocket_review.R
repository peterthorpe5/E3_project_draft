#' Point-and-click views for the offline 3D pocket-review report.

#' Pocket-review UI.
#'
#' @param id Module identifier.
#' @param focus Either `structure` or `alignment`.
#' @return Shiny UI.
pocket_review_ui <- function(id, focus = c("structure", "alignment")) {
  focus <- match.arg(focus)
  ns <- shiny::NS(id)
  title <- if (focus == "structure") {
    "Selected-group 3D structures and pockets"
  } else {
    "Selected-group pocket-annotated alignment"
  }
  introduction <- if (focus == "structure") {
    paste(
      "Select an evolutionary group, then switch between available member",
      "models and pocket ranks inside the viewer. Pocket colours locate the",
      "strict rank-one and exploratory rank-two-to-five predictions."
    )
  } else {
    paste(
      "Select an evolutionary group to inspect every published MAFFT member",
      "sequence. Highlighted residues retain the exact FASTA, alignment and",
      "structure-coordinate mapping used by the structural analysis."
    )
  }
  shiny::tagList(
    shiny::h3(title),
    shiny::p(class = "grant-question", introduction),
    shiny::uiOutput(ns("availability")),
    bslib::layout_columns(
      shiny::selectizeInput(
        ns("group_page"),
        "Evolutionary group",
        choices = NULL,
        multiple = FALSE,
        options = list(
          placeholder = "Search by rank, HOG/orthogroup or accession"
        )
      ),
      shiny::uiOutput(ns("review_links")),
      col_widths = c(8, 4)
    ),
    shiny::uiOutput(ns("group_summary")),
    shiny::uiOutput(ns("review_frame")),
    shiny::div(
      class = "review-member-section",
      shiny::h4(if (focus == "structure") {
        "Displayed protein models"
      } else {
        "OrthoFinder-group member sequence identifiers"
      }),
      shiny::p(
        class = "small text-muted",
        if (focus == "structure") {
          paste(
            "The table distinguishes model availability from pocket evidence.",
            "A missing model is not evidence that a group member lacks a pocket."
          )
        } else {
          paste(
            "These are the original accession/name values retained in the",
            "authoritative group alignment, with stable exported FASTA identifiers."
          )
        }
      ),
      shiny::downloadButton(
        ns("download_members"),
        "Download selected group as TSV"
      ),
      DT::DTOutput(ns("member_table"))
    )
  )
}

#' Return the selected index row from a prepared review configuration.
#'
#' @param review_config Prepared pocket-review configuration.
#' @param group_page Selected group-page path.
#' @return One-row data frame, or an empty data frame.
selected_pocket_review_row <- function(review_config, group_page) {
  if (
    !isTRUE(review_config$available) ||
      is.null(group_page) ||
      length(group_page) != 1L ||
      is.na(group_page) ||
      !nzchar(group_page)
  ) {
    return(data.frame())
  }
  review_config$index[
    review_config$index$group_review_html == group_page,
    ,
    drop = FALSE
  ]
}

#' Return the selected group member table.
#'
#' @param review_config Prepared pocket-review configuration.
#' @param review_rank Selected review rank.
#' @param focus Either `structure` or `alignment`.
#' @return Display-ready data frame.
selected_pocket_review_members <- function(
  review_config,
  review_rank,
  focus = c("structure", "alignment")
) {
  focus <- match.arg(focus)
  if (length(review_rank) != 1L || is.na(review_rank)) {
    return(data.frame())
  }
  source <- if (focus == "structure") {
    review_config$models
  } else {
    review_config$sequences
  }
  selected <- source[source$review_rank == review_rank, , drop = FALSE]
  preferred <- if (focus == "structure") {
    c(
      "primary_group_id",
      "lead_cluster_id",
      "candidate_accession",
      "species_column",
      "is_reference",
      "model_status",
      "ca_atom_count",
      "mapped_pocket_ca_count",
      "retained_pocket_count"
    )
  } else {
    c(
      "primary_group_id",
      "lead_cluster_id",
      "fasta_identifier",
      "candidate_accession",
      "species_column",
      "is_reference",
      "has_ranked_pocket_evidence",
      "sequence_length",
      "alignment_length"
    )
  }
  selected[, preferred[preferred %in% names(selected)], drop = FALSE]
}

#' JavaScript that scrolls a loaded report page to the requested section.
#'
#' @param focus Either `structure` or `alignment`.
#' @return Fixed same-origin iframe onload script.
pocket_review_scroll_script <- function(focus = c("structure", "alignment")) {
  focus <- match.arg(focus)
  heading <- if (focus == "structure") {
    "Interactive 3D pocket location"
  } else {
    "Pocket-annotated MAFFT sequence alignment"
  }
  paste0(
    "const doc=this.contentDocument;",
    "if(doc){const headings=Array.from(doc.querySelectorAll('h2'));",
    "const target=headings.find((node)=>node.textContent.trim()==='",
    heading,
    "');if(target){target.scrollIntoView();}}"
  )
}

#' Pocket-review server.
#'
#' @param id Module identifier.
#' @param review_config Prepared and registered pocket-review configuration.
#' @param focus Either `structure` or `alignment`.
#' @return Selected group and member-table reactives, invisibly.
pocket_review_server <- function(
  id,
  review_config,
  focus = c("structure", "alignment")
) {
  focus <- match.arg(focus)
  shiny::moduleServer(id, function(input, output, session) {
    output$availability <- shiny::renderUI({
      if (isTRUE(review_config$available)) {
        shiny::div(
          class = "alert alert-success py-2",
          paste(
            nrow(review_config$index),
            "ranked group review pages are available from the portable bundle."
          )
        )
      } else {
        shiny::div(
          class = "alert alert-warning",
          shiny::strong("Pocket-review visualisations are not configured."),
          shiny::p(review_config$reason),
          shiny::code("--pocket_review_dir /path/to/pocket_review_bundle")
        )
      }
    })

    shiny::observeEvent(TRUE, {
      if (isTRUE(review_config$available)) {
        choices <- pocket_review_group_choices(review_config$index)
        shiny::updateSelectizeInput(
          session = session,
          inputId = "group_page",
          choices = choices,
          selected = unname(choices[[1L]]),
          server = TRUE
        )
      }
    }, once = TRUE)

    selected_row <- shiny::reactive({
      selected_pocket_review_row(
        review_config = review_config,
        group_page = input$group_page
      )
    })

    selected_members <- shiny::reactive({
      row <- selected_row()
      if (nrow(row) != 1L) {
        return(data.frame())
      }
      selected_pocket_review_members(
        review_config = review_config,
        review_rank = row$review_rank[[1L]],
        focus = focus
      )
    })

    output$review_links <- shiny::renderUI({
      shiny::req(isTRUE(review_config$available))
      prefix <- review_config$resource_prefix
      shiny::div(
        class = "review-link-panel",
        shiny::tags$a(
          class = "btn btn-outline-primary btn-sm",
          href = pocket_review_url(prefix, "index.html"),
          target = "_blank",
          rel = "noopener noreferrer",
          "Open ranked review index"
        ),
        shiny::tags$a(
          class = "btn btn-outline-secondary btn-sm",
          href = pocket_review_url(prefix, "evidence_matrix.html"),
          target = "_blank",
          rel = "noopener noreferrer",
          "Compare groups"
        )
      )
    })

    output$group_summary <- shiny::renderUI({
      row <- selected_row()
      shiny::req(nrow(row) == 1L)
      values <- c(
        paste0("Review rank: ", row$review_rank[[1L]]),
        paste0("Evolutionary group: ", row$primary_group_id[[1L]]),
        paste0("Lead DeepClust cluster: ", row$lead_cluster_id[[1L]]),
        paste0("Reference: ", row$reference_accession[[1L]]),
        paste0("Group sequences: ", row$alignment_sequence_count[[1L]]),
        paste0("Proteins with pocket evidence: ", row$protein_count[[1L]])
      )
      shiny::div(
        class = "review-summary-strip",
        lapply(values, function(value) shiny::span(value))
      )
    })

    output$review_frame <- shiny::renderUI({
      row <- selected_row()
      shiny::req(nrow(row) == 1L)
      src <- pocket_review_url(
        review_config$resource_prefix,
        row$group_review_html[[1L]]
      )
      shiny::tags$iframe(
        class = "pocket-review-frame",
        src = src,
        title = if (focus == "structure") {
          "Interactive protein structure and pocket viewer"
        } else {
          "Pocket-annotated protein sequence alignment"
        },
        loading = "lazy",
        onload = pocket_review_scroll_script(focus = focus)
      )
    })

    output$member_table <- DT::renderDT({
      table <- selected_members()
      shiny::validate(shiny::need(
        nrow(table) > 0L,
        "No member records available."
      ))
      DT::datatable(
        table,
        rownames = FALSE,
        filter = "top",
        options = list(
          pageLength = 25,
          scrollX = TRUE,
          autoWidth = TRUE
        )
      )
    })

    output$download_members <- shiny::downloadHandler(
      filename = function() {
        row <- selected_row()
        group_id <- if (nrow(row) == 1L) {
          gsub("[^A-Za-z0-9_.-]", "_", row$primary_group_id[[1L]])
        } else {
          "selected_group"
        }
        paste0(group_id, "_", focus, "_members.tsv")
      },
      content = function(file) {
        table <- selected_members()
        if (nrow(table) == 0L) {
          stop("No selected group members are available.", call. = FALSE)
        }
        utils::write.table(
          table,
          file = file,
          sep = "\t",
          quote = FALSE,
          row.names = FALSE,
          na = ""
        )
      }
    )

    invisible(list(
      selected_row = selected_row,
      selected_members = selected_members
    ))
  })
}
