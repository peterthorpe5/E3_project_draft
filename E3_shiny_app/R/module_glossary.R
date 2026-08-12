#' Scientific glossary Shiny module.

#' Build the glossary user interface.
#'
#' @param id Module identifier.
#' @return Shiny UI.
glossary_ui <- function(id) {
  ns <- shiny::NS(id)
  sections <- unique(scientific_glossary()$Section)
  shiny::tagList(
    shiny::h2("Glossary and computational rules"),
    shiny::p(
      class = "grant-question",
      paste(
        "These definitions describe the completed top-200 analysis.",
        "Threshold-explorer changes create sensitivity lists and do not",
        "rewrite the recorded primary result."
      )
    ),
    shiny::selectInput(
      inputId = ns("section"),
      label = "Glossary section",
      choices = sections,
      selected = sections[[1L]]
    ),
    tabular_download_buttons(
      ns = ns,
      tsv_id = "download_tsv",
      excel_id = "download_excel",
      tsv_label = "Download complete glossary as TSV",
      excel_label = "Download complete glossary as Excel"
    ),
    shiny::hr(),
    DT::DTOutput(ns("table"))
  )
}

#' Serve the scientific glossary.
#'
#' @param id Module identifier.
#' @return No return value.
glossary_server <- function(id) {
  shiny::moduleServer(id, function(input, output, session) {
    glossary <- scientific_glossary()
    displayed <- shiny::reactive({
      shiny::req(input$section)
      dplyr::filter(glossary, .data$Section == input$section) |>
        dplyr::select(-.data$Section)
    })
    output$table <- DT::renderDT({
      DT::datatable(
        displayed(),
        rownames = FALSE,
        options = list(pageLength = 25, scrollX = TRUE)
      )
    })
    output$download_tsv <- shiny::downloadHandler(
      filename = function() "aria_e3_scientific_glossary.tsv",
      content = function(path) {
        utils::write.table(
          glossary,
          file = path,
          sep = "\t",
          quote = TRUE,
          row.names = FALSE,
          na = ""
        )
      }
    )
    output$download_excel <- shiny::downloadHandler(
      filename = function() "aria_e3_scientific_glossary.xlsx",
      content = function(path) {
        write_formatted_excel(
          data = glossary,
          path = path
        )
      }
    )
  })
}
