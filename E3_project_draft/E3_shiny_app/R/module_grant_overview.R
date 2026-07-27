#' Grant-aligned project overview module.

#' Grant-overview UI.
#'
#' @param id Module identifier.
#' @return Shiny UI.
grant_overview_ui <- function(id) {
  ns <- shiny::NS(id)
  shiny::tagList(
    shiny::h2("Grant-aligned evidence overview"),
    shiny::p(
      "The resource moves from candidate discovery through cross-species evidence ",
      "to conserved structural and chemical starting space. Evidence gaps remain ",
      "explicit and do not become biological negatives."
    ),
    bslib::layout_columns(
      bslib::value_box(
        "Candidate groups",
        shiny::textOutput(ns("candidate_count"))
      ),
      bslib::value_box(
        "Milestone 1 passes",
        shiny::textOutput(ns("prestructure_pass_count"))
      ),
      bslib::value_box(
        "Final stringent passes",
        shiny::textOutput(ns("final_pass_count"))
      ),
      bslib::value_box(
        "3D-assessed groups",
        shiny::textOutput(ns("structural_assessed_count"))
      )
    ),
    bslib::layout_columns(
      bslib::card(
        bslib::card_header("Milestone 1: conservation and queryable resource"),
        shiny::p(
          "Candidate discovery, explicit OrthoFinder group identifiers and members, ",
          "target-species breadth, E3-domain support and Expression Atlas evidence."
        )
      ),
      bslib::card(
        bslib::card_header("Milestone 2: conserved chemical starting space"),
        shiny::p(
          "Reusable pockets, pocket-bearing region conservation, FASTA coordinates ",
          "and optional US-align/TM-align evidence for equivalent 3D pocket position."
        )
      ),
      bslib::card(
        class = "interpretation-card",
        bslib::card_header("Interpretation boundary"),
        shiny::p(
          "Computational recommendations do not establish E3 activity, compound ",
          "binding or target degradation. Biological and chemistry validation remain ",
          "required."
        )
      )
    ),
    shiny::h3("Loaded evidence relations"),
    DT::DTOutput(ns("resource_overview"))
  )
}

#' Grant-overview server.
#'
#' @param id Module identifier.
#' @param resource_source Flexible result source.
#' @return No return value.
grant_overview_server <- function(id, resource_source) {
  shiny::moduleServer(id, function(input, output, session) {
    metrics <- shiny::reactive({
      if (!resource_source_available(resource_source)) {
        return(tibble::tibble(
          candidate_count = 0,
          prestructure_pass_count = 0,
          final_pass_count = 0,
          structural_assessed_count = 0
        ))
      }
      tryCatch(
        collect_grant_overview(resource_source),
        error = function(error) {
          shiny::showNotification(
            paste("Could not calculate grant overview:", conditionMessage(error)),
            type = "error",
            duration = NULL
          )
          tibble::tibble(
            candidate_count = 0,
            prestructure_pass_count = 0,
            final_pass_count = 0,
            structural_assessed_count = 0
          )
        }
      )
    })
    render_metric <- function(column) {
      shiny::renderText({
        format_summary_count(metrics()[[column]][[1L]])
      })
    }
    output$candidate_count <- render_metric("candidate_count")
    output$prestructure_pass_count <- render_metric("prestructure_pass_count")
    output$final_pass_count <- render_metric("final_pass_count")
    output$structural_assessed_count <- render_metric("structural_assessed_count")
    output$resource_overview <- DT::renderDT({
      if (!resource_source_available(resource_source)) {
        return(DT::datatable(
          tibble::tibble(message = "No E3 result source is configured."),
          rownames = FALSE
        ))
      }
      catalog <- collect_resource_view_catalog(resource_source)
      DT::datatable(
        catalog,
        rownames = FALSE,
        filter = "top",
        options = list(pageLength = 25, scrollX = TRUE, deferRender = TRUE)
      )
    })
  })
}
