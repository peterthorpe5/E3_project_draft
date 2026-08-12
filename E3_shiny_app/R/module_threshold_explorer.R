#' Interactive pre-structure and structural threshold explorer.

#' Build one paired slider and manual numeric input.
#'
#' @param ns Shiny namespace function.
#' @param id Stable threshold identifier.
#' @param label User-facing label.
#' @param value Default value.
#' @return Shiny UI.
threshold_pair_ui <- function(ns, id, label, value) {
  shiny::tagList(
    bslib::layout_columns(
      shiny::sliderInput(
        inputId = ns(paste0(id, "_slider")),
        label = label,
        min = 0,
        max = 1,
        value = value,
        step = 0.01
      ),
      shiny::numericInput(
        inputId = ns(id),
        label = "Type exact value",
        value = value,
        min = 0,
        max = 1,
        step = 0.01
      ),
      col_widths = c(8, 4)
    ),
    shiny::p(
      class = "small text-muted threshold-definition",
      threshold_help_text(id)
    )
  )
}

#' Threshold-explorer UI.
#'
#' @param id Module identifier.
#' @return Shiny UI.
threshold_explorer_ui <- function(id) {
  ns <- shiny::NS(id)
  defaults <- current_threshold_defaults()
  structural_condition <- "input.mode === 'structural'"
  shiny::tagList(
    shiny::h2("Explore alternative candidate thresholds"),
    shiny::p(
      class = "grant-question",
      "The original grant-aligned result remains unchanged. This tab creates a ",
      "clearly labelled sensitivity-analysis list from values already stored in ",
      "the completed resource; it does not rerun sequence or structural analyses."
    ),
    bslib::layout_columns(
      bslib::card(
        bslib::card_header("Analysis and output"),
        shiny::radioButtons(
          inputId = ns("mode"),
          label = "Prioritisation view",
          choices = c(
            "Pre-structure prioritisation" = "prestructure",
            "Structurally informed prioritisation" = "structural"
          ),
          selected = defaults$mode
        ),
        shiny::selectInput(
          inputId = ns("result_scope"),
          label = "Rows to show",
          choices = c(
            "Passing candidates only" = "passing",
            "Passes and one-gate near-misses" = "pass_near",
            "All evaluated groups" = "all"
          ),
          selected = defaults$result_scope
        ),
        shiny::numericInput(
          inputId = ns("max_rows"),
          label = "Maximum displayed rows",
          value = 1000,
          min = 1,
          max = 10000,
          step = 100
        ),
        shiny::actionButton(
          inputId = ns("reset_defaults"),
          label = "Reset current defaults",
          class = "btn-primary"
        )
      ),
      bslib::card(
        bslib::card_header("How to interpret the list"),
        shiny::p(
          shiny::strong("PASS"),
          " meets every selected gate. ",
          shiny::strong("NEAR_MISS"),
          " fails exactly one selected gate."
        ),
        shiny::p(
          shiny::strong("NOT_STRUCTURALLY_ASSESSED"),
          " means the group was outside the 200 groups taken through the current ",
          "3D assessment. It is not a structural failure."
        ),
        shiny::p(
          class = "small text-muted",
          shiny::textOutput(ns("source_scope"), inline = TRUE)
        )
      ),
      col_widths = c(5, 7)
    ),
    bslib::accordion(
      open = c("Pre-structure thresholds"),
      bslib::accordion_panel(
        "Pre-structure thresholds",
        threshold_pair_ui(
          ns = ns,
          id = "target_species_fraction",
          label = "Minimum target-species fraction",
          value = defaults$target_species_fraction
        ),
        threshold_pair_ui(
          ns = ns,
          id = "mandatory_species_fraction",
          label = "Minimum mandatory-species fraction",
          value = defaults$mandatory_species_fraction
        ),
        threshold_pair_ui(
          ns = ns,
          id = "domain_species_fraction",
          label = "Minimum domain-supported assessed-species fraction",
          value = defaults$domain_species_fraction
        ),
        threshold_pair_ui(
          ns = ns,
          id = "expression_species_fraction",
          label = "Minimum expression-supported assessed-species fraction",
          value = defaults$expression_species_fraction
        ),
        bslib::layout_columns(
          shiny::checkboxInput(
            inputId = ns("require_domain_evidence"),
            label = "Require assessable domain evidence",
            value = defaults$require_domain_evidence
          ),
          shiny::checkboxInput(
            inputId = ns("require_expression_evidence"),
            label = "Require assessable expression evidence",
            value = defaults$require_expression_evidence
          )
        )
      ),
      bslib::accordion_panel(
        "Structural thresholds",
        shiny::conditionalPanel(
          condition = structural_condition,
          ns = ns,
          threshold_pair_ui(
            ns = ns,
            id = "structural_species_fraction",
            label = "Minimum structurally supported species fraction",
            value = defaults$structural_species_fraction
          ),
          threshold_pair_ui(
            ns = ns,
            id = "minimum_druggability_score",
            label = "Minimum member druggability score",
            value = defaults$minimum_druggability_score
          ),
          bslib::layout_columns(
            shiny::checkboxInput(
              inputId = ns("require_conserved_region"),
              label = "Require conserved pocket-bearing sequence region",
              value = defaults$require_conserved_region
            ),
            shiny::checkboxInput(
              inputId = ns("require_all_member_mapping"),
              label = "Require every assessed member to pass pocket mapping",
              value = defaults$require_all_member_mapping
            ),
            shiny::checkboxInput(
              inputId = ns("require_strict_3d"),
              label = "Require strictly conserved corresponding 3D pocket",
              value = defaults$require_strict_3d
            ),
            col_widths = c(6, 6, 6)
          ),
          shiny::checkboxInput(
            inputId = ns("include_not_assessed"),
            label = paste(
              "Also display groups not structurally assessed",
              "(never label them as structural passes)"
            ),
            value = defaults$include_not_assessed
          ),
          shiny::p(
            class = "small text-muted",
            paste(
              "Pocket mapping, pocket-region classification and strict 3D",
              "statuses use the recorded production calculations.",
              "Changing their underlying coordinate, overlap or TM-score",
              "rules would require rerunning the scientific pipeline."
            )
          )
        ),
        shiny::conditionalPanel(
          condition = "input.mode !== 'structural'",
          ns = ns,
          shiny::p(
            class = "text-muted",
            "Switch to the structurally informed view to use these controls."
          )
        )
      )
    ),
    bslib::layout_columns(
      bslib::value_box(
        "Evaluated evolutionary groups",
        shiny::textOutput(ns("evaluated_count"))
      ),
      bslib::value_box(
        "Custom passes",
        shiny::textOutput(ns("pass_count"))
      ),
      bslib::value_box(
        "One-gate near-misses",
        shiny::textOutput(ns("near_miss_count"))
      ),
      bslib::value_box(
        "Structurally assessed",
        shiny::textOutput(ns("structurally_assessed_count"))
      )
    ),
    shiny::div(
      class = "threshold-table-actions",
      tabular_download_buttons(
        ns = ns,
        tsv_id = "download_tsv",
        excel_id = "download_excel",
        tsv_label = "Download custom candidate list as TSV",
        excel_label = "Download custom candidate list as Excel"
      ),
      shiny::span(
        class = "small text-muted",
        paste(
          "Both downloads repeat the active numeric thresholds in every",
          "result row."
        )
      )
    ),
    shinycssloaders::withSpinner(DT::DTOutput(ns("candidate_table")))
  )
}

#' Bind a slider to its manual numeric input.
#'
#' @param input Shiny input object.
#' @param session Shiny session.
#' @param id Stable threshold identifier.
#' @return No return value.
bind_threshold_pair <- function(input, session, id) {
  slider_id <- paste0(id, "_slider")
  shiny::observeEvent(input[[slider_id]], {
    value <- input[[slider_id]]
    if (!is.null(value) && !identical(as.numeric(input[[id]]), as.numeric(value))) {
      shiny::updateNumericInput(
        session = session,
        inputId = id,
        value = value
      )
    }
  }, ignoreInit = TRUE)
  shiny::observeEvent(input[[id]], {
    value <- suppressWarnings(as.numeric(input[[id]]))
    if (
      length(value) == 1L && !is.na(value) && value >= 0 && value <= 1 &&
        !identical(as.numeric(input[[slider_id]]), value)
    ) {
      shiny::updateSliderInput(
        session = session,
        inputId = slider_id,
        value = value
      )
    }
  }, ignoreInit = TRUE)
  invisible(NULL)
}

#' Threshold-explorer server.
#'
#' @param id Module identifier.
#' @param resource_source Flexible result source.
#' @param max_rows Global display-row cap.
#' @return Reactive containing the displayed candidate list.
threshold_explorer_server <- function(
  id,
  resource_source,
  max_rows = 1000L
) {
  shiny::moduleServer(id, function(input, output, session) {
    defaults <- current_threshold_defaults()
    numeric_fields <- c(
      "target_species_fraction",
      "mandatory_species_fraction",
      "domain_species_fraction",
      "expression_species_fraction",
      "structural_species_fraction",
      "minimum_druggability_score"
    )
    logical_fields <- c(
      "require_domain_evidence",
      "require_expression_evidence",
      "require_conserved_region",
      "require_all_member_mapping",
      "require_strict_3d",
      "include_not_assessed"
    )
    for (field in numeric_fields) {
      local({
        local_field <- field
        bind_threshold_pair(
          input = input,
          session = session,
          id = local_field
        )
      })
    }

    shiny::observeEvent(input$reset_defaults, {
      for (field in numeric_fields) {
        shiny::updateSliderInput(
          session = session,
          inputId = paste0(field, "_slider"),
          value = defaults[[field]]
        )
        shiny::updateNumericInput(
          session = session,
          inputId = field,
          value = defaults[[field]]
        )
      }
      for (field in logical_fields) {
        shiny::updateCheckboxInput(
          session = session,
          inputId = field,
          value = defaults[[field]]
        )
      }
      shiny::updateSelectInput(
        session = session,
        inputId = "result_scope",
        selected = defaults$result_scope
      )
    })

    context <- shiny::reactive({
      if (!resource_source_available(resource_source = resource_source)) {
        return(list(
          relation = "",
          columns = character(),
          message = "No E3 result source is configured."
        ))
      }
      relations <- collect_resource_view_names(duckdb_path = resource_source)
      relation <- select_threshold_relation(relation_names = relations)
      if (!nzchar(relation)) {
        return(list(
          relation = "",
          columns = character(),
          message = "No supported candidate relation is available."
        ))
      }
      columns <- collect_resource_columns(
        duckdb_path = resource_source,
        view_name = relation
      )
      list(
        relation = relation,
        columns = as.character(columns$column_name),
        message = ""
      )
    })

    active_settings <- shiny::reactive({
      values <- list(
        mode = input$mode %||% defaults$mode,
        result_scope = input$result_scope %||% defaults$result_scope
      )
      for (field in numeric_fields) {
        values[[field]] <- input[[field]] %||% defaults[[field]]
      }
      for (field in logical_fields) {
        values[[field]] <- input[[field]] %||% defaults[[field]]
      }
      normalise_threshold_settings(settings = values)
    })

    query_request <- shiny::reactive({
      current_context <- context()
      settings <- active_settings()
      requested_rows <- suppressWarnings(as.integer(input$max_rows %||% max_rows))
      if (is.na(requested_rows)) {
        requested_rows <- as.integer(max_rows)
      }
      list(
        context = current_context,
        settings = settings,
        max_rows = min(max(1L, requested_rows), as.integer(max_rows), 10000L)
      )
    })
    debounced_request <- shiny::debounce(query_request, millis = 300L)

    displayed <- shiny::reactive({
      request <- debounced_request()
      if (!nzchar(request$context$relation)) {
        return(tibble::tibble(message = request$context$message))
      }
      tryCatch(
        collect_threshold_results(
          resource_source = resource_source,
          relation = request$context$relation,
          available = request$context$columns,
          settings = request$settings,
          max_rows = request$max_rows
        ),
        error = function(error) {
          shiny::showNotification(
            paste("Could not evaluate candidate thresholds:", conditionMessage(error)),
            type = "error",
            duration = NULL
          )
          tibble::tibble(error = conditionMessage(error))
        }
      )
    })

    summary_counts <- shiny::reactive({
      request <- debounced_request()
      if (!nzchar(request$context$relation)) {
        return(tibble::tibble(
          evaluated_count = 0,
          pass_count = 0,
          near_miss_count = 0,
          structurally_assessed_count = 0,
          not_structurally_assessed_count = 0
        ))
      }
      tryCatch(
        collect_threshold_summary(
          resource_source = resource_source,
          relation = request$context$relation,
          available = request$context$columns,
          settings = request$settings
        ),
        error = function(error) {
          shiny::showNotification(
            paste("Could not summarise candidate thresholds:", conditionMessage(error)),
            type = "error",
            duration = NULL
          )
          tibble::tibble(
            evaluated_count = 0,
            pass_count = 0,
            near_miss_count = 0,
            structurally_assessed_count = 0,
            not_structurally_assessed_count = 0
          )
        }
      )
    })

    render_count <- function(column) {
      shiny::renderText({
        format_summary_count(summary_counts()[[column]][[1L]])
      })
    }
    output$evaluated_count <- render_count(column = "evaluated_count")
    output$pass_count <- render_count(column = "pass_count")
    output$near_miss_count <- render_count(column = "near_miss_count")
    output$structurally_assessed_count <- render_count(
      column = "structurally_assessed_count"
    )
    output$source_scope <- shiny::renderText({
      current_context <- context()
      if (!nzchar(current_context$relation)) {
        return(current_context$message)
      }
      if (identical(
        current_context$relation,
        "final_evolutionary_candidate_prioritisation"
      )) {
        return(paste0(
          "Using `", current_context$relation,
          "`: one row per evolutionary group."
        ))
      }
      paste0(
        "Using `", current_context$relation,
        "` as a compatibility source and retaining one deterministic lead row ",
        "per evolutionary group."
      )
    })

    output$candidate_table <- DT::renderDT({
      DT::datatable(
        displayed(),
        rownames = FALSE,
        filter = "top",
        extensions = "Buttons",
        options = list(
          pageLength = 25,
          scrollX = TRUE,
          deferRender = TRUE,
          dom = "Bfrtip",
          buttons = c("colvis")
        )
      )
    })
    output$download_tsv <- shiny::downloadHandler(
      filename = function() {
        paste0(
          "aria_e3_", active_settings()$mode,
          "_custom_thresholds_", format(Sys.Date(), "%Y%m%d"), ".tsv"
        )
      },
      content = function(path) {
        utils::write.table(
          displayed(),
          file = path,
          sep = "\t",
          quote = TRUE,
          row.names = FALSE,
          na = ""
        )
      }
    )
    output$download_excel <- shiny::downloadHandler(
      filename = function() {
        paste0(
          "aria_e3_", active_settings()$mode,
          "_custom_thresholds_", format(Sys.Date(), "%Y%m%d"), ".xlsx"
        )
      },
      content = function(path) {
        write_formatted_excel(
          data = displayed(),
          path = path
        )
      }
    )
    displayed
  })
}
