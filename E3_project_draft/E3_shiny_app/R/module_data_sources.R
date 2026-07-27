#' Data-source documentation UI.
#'
#' @param id Module identifier.
#' @return Shiny UI.
data_sources_ui <- function(id) {
  ns <- shiny::NS(id)

  shiny::tagList(
    shiny::h3("Files used and provenance"),
    shiny::p(
      "This tab reads the QC catalogs written by the source-to-Parquet pipeline. ",
      "Use the report script to generate a persistent Markdown file for records."
    ),
    shiny::verbatimTextOutput(ns("paths")),
    bslib::layout_columns(
      bslib::value_box("Source files", shiny::textOutput(ns("source_file_count"))),
      bslib::value_box("Tabular tables", shiny::textOutput(ns("tabular_count"))),
      bslib::value_box("FASTA sources", shiny::textOutput(ns("fasta_count")))
    ),
    shiny::h4("Source manifest"),
    shinycssloaders::withSpinner(DT::DTOutput(ns("source_manifest"))),
    shiny::h4("Converted table catalogs"),
    bslib::accordion(
      bslib::accordion_panel("Tabular files", DT::DTOutput(ns("tabular_catalog"))),
      bslib::accordion_panel("FASTA files", DT::DTOutput(ns("fasta_catalog"))),
      bslib::accordion_panel("Text files", DT::DTOutput(ns("text_catalog"))),
      bslib::accordion_panel("Inherited Parquet", DT::DTOutput(ns("inherited_parquet_catalog")))
    )
  )
}

#' Data-source documentation server.
#'
#' @param id Module identifier.
#' @param resource_derived_dir Derived output directory.
#' @return No return value.
data_sources_server <- function(id, resource_derived_dir) {
  shiny::moduleServer(id, function(input, output, session) {
    paths <- resource_catalog_paths(resource_derived_dir)

    source_manifest <- shiny::reactive(read_optional_tsv(paths$source_manifest))
    tabular_catalog <- shiny::reactive(read_optional_tsv(paths$tabular_catalog))
    fasta_catalog <- shiny::reactive(read_optional_tsv(paths$fasta_catalog))
    text_catalog <- shiny::reactive(read_optional_tsv(paths$text_catalog))
    inherited_parquet_catalog <- shiny::reactive(read_optional_tsv(paths$inherited_parquet_catalog))

    output$paths <- shiny::renderText({
      paste(
        "Derived directory:", normalizePath(resource_derived_dir, mustWork = FALSE),
        "\nSource manifest:", paths$source_manifest,
        "\nReport command: Rscript inst/scripts/write_data_sources_report.R --derived_dir", resource_derived_dir,
        sep = ""
      )
    })

    output$source_file_count <- shiny::renderText(format_summary_count(nrow(source_manifest())))
    output$tabular_count <- shiny::renderText(format_summary_count(nrow(tabular_catalog())))
    output$fasta_count <- shiny::renderText(format_summary_count(nrow(fasta_catalog())))

    output$source_manifest <- DT::renderDT({
      DT::datatable(
        utils::head(source_manifest(), 5000L),
        rownames = FALSE,
        filter = "top",
        options = list(pageLength = 25, scrollX = TRUE, deferRender = TRUE)
      )
    })

    output$tabular_catalog <- DT::renderDT({
      DT::datatable(tabular_catalog(), rownames = FALSE, filter = "top", options = list(scrollX = TRUE))
    })

    output$fasta_catalog <- DT::renderDT({
      DT::datatable(fasta_catalog(), rownames = FALSE, filter = "top", options = list(scrollX = TRUE))
    })

    output$text_catalog <- DT::renderDT({
      DT::datatable(text_catalog(), rownames = FALSE, filter = "top", options = list(scrollX = TRUE))
    })

    output$inherited_parquet_catalog <- DT::renderDT({
      DT::datatable(inherited_parquet_catalog(), rownames = FALSE, filter = "top", options = list(scrollX = TRUE))
    })
  })
}
