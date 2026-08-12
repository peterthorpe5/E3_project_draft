#' Scientific glossary Shiny module.

#' Build the glossary user interface.
#'
#' @param id Module identifier.
#' @return Shiny UI.
glossary_ui <- function(id) {
  ns <- shiny::NS(id)
  sections <- unique(scientific_glossary()$Section)
  section_choices <- c("All sections", sections)
  shiny::tagList(
    shiny::h2("Glossary and computational rules"),
    shiny::p(
      class = "grant-question",
      paste(
        "This expanded glossary combines project-wide technical terminology,",
        "the complete 218-field final-candidate data dictionary and the recorded",
        "top-200 computational rules. Threshold-explorer changes create",
        "sensitivity lists and do not rewrite the recorded primary result.",
        "Every glossary row is available in the browser below; downloading is optional."
      )
    ),
    shiny::selectInput(
      inputId = ns("section"),
      label = "Glossary section",
      choices = section_choices,
      selected = "All sections"
    ),
    shiny::textOutput(ns("row_count")),
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
      if (identical(input$section, "All sections")) {
        return(glossary)
      }
      dplyr::filter(glossary, .data$Section == input$section)
    })
    output$row_count <- shiny::renderText({
      paste(
        format(nrow(displayed()), big.mark = ","),
        "glossary rows are available in this browser table."
      )
    })
    output$table <- DT::renderDT({
      readable_datatable(
        displayed(),
        rownames = FALSE,
        options = list(
          pageLength = nrow(glossary),
          lengthMenu = c(25, 50, 100, nrow(glossary)),
          scrollX = TRUE,
          scrollY = "68vh"
        )
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
