#' Reusable grant-facing result section with independent column controls.

#' Adjustable ranking-weight controls for one score layer.
#'
#' @param ns Shiny namespace function.
#' @param group Recorded score layer.
#' @return Shiny card containing weight sliders.
ranking_weight_group_ui <- function(ns, group) {
  defaults <- recorded_ranking_weights()[[group]]
  labels <- ranking_weight_labels()[[group]]
  controls <- lapply(names(defaults), function(component) {
    shiny::sliderInput(
      inputId = ns(paste0("ranking_weight_", group, "_", component)),
      label = labels[[component]],
      min = 0,
      max = 1,
      value = defaults[[component]],
      step = 0.05
    )
  })
  do.call(
    bslib::card,
    c(list(bslib::card_header(paste(tools::toTitleCase(group), "weights"))), controls)
  )
}

#' Verbose recorded-ranking methodology and sensitivity controls.
#'
#' @param ns Shiny namespace function.
#' @return Shiny UI.
ranking_methodology_ui <- function(ns) {
  formula_item <- function(title, formula, explanation) {
    shiny::tags$li(
      shiny::p(shiny::strong(title), " ", shiny::tags$code(formula)),
      shiny::p(explanation)
    )
  }
  shiny::tagList(
    shiny::hr(),
    shiny::h3("How the recorded computational ranking was calculated"),
    shiny::div(
      class = "alert alert-warning",
      shiny::strong("Interpretation boundary: "),
      paste(
        "this is a deterministic evidence-prioritisation, not a probability",
        "that a protein is an E3 ligase or that a PROTAC will work. Mandatory",
        "grant-aligned gates are retained separately, so a high continuous",
        "score cannot repair a failed mandatory gate."
      )
    ),
    shiny::tags$ol(
      formula_item(
        "Discovery score.",
        "D = (f_reviewed + f_ubiquitin_GO + (1 - f_exclusion)) / 3",
        paste(
          "For the lead DeepClust cluster, the three equally weighted terms",
          "are the reviewed-seed fraction, the ubiquitin-related GO-positive",
          "seed fraction and the complement of the exclusion-flag fraction."
        )
      ),
      formula_item(
        "Orthology score.",
        "O = f_target x (0.8 + 0.2 x f_mandatory)",
        paste(
          "Broad representation across the configured target plant species",
          "supplies most of the score. Representation of the six mandatory crop",
          "species supplies the remaining adjustment."
        )
      ),
      formula_item(
        "Domain and expression scores.",
        "A = n_domain_supported / n_domain_assessed; E = n_expression_supported / n_expression_assessed",
        paste(
          "A uses only species with usable domain annotation; E uses only",
          "species with a unique usable Expression Atlas mapping. When an",
          "assessed denominator was unavailable, the recorded scoring value was",
          "the neutral value 0.5, while availability and gate status remained",
          "explicit in separate fields rather than being presented as measured zero."
        )
      ),
      formula_item(
        "Pre-structure score.",
        "P = 0.10D + 0.35O + 0.20A + 0.35E",
        paste(
          "This combines discovery support, cross-species orthology, domain",
          "support and expression support before structural evidence is added."
        )
      ),
      formula_item(
        "Ligandability score.",
        "L = (d_min + p_pLDDT + m_map + p_agree) / 4",
        paste(
          "d_min is the minimum selected-pocket druggability across assessed",
          "members; p_pLDDT is mean pocket-confidence support; m_map is 1 only",
          "when every assessed member passes pocket mapping; and p_agree is the",
          "fraction supported by both pocket-prediction signals."
        )
      ),
      formula_item(
        "Pocket-conservation score.",
        "C = 0.30f_component + 0.25o_region + 0.20c_chemical + 0.15d_min + 0.10p_pLDDT",
        paste(
          "The terms are conserved-component coverage, mean aligned pocket-region",
          "overlap, biochemical-class conservation, minimum druggability and mean",
          "pocket pLDDT support. This summarises pocket-bearing sequence-region",
          "evidence; it is not experimental binding evidence or proof of an",
          "equivalent three-dimensional cavity."
        )
      ),
      formula_item(
        "Structural score and optional 3D refinement.",
        "S_base = 0.55L + 0.45C; S = (1 - w_3D)S_base + w_3D T",
        paste(
          "For assessed comparisons, T = 0.40TM_min + 0.40o_3D +",
          "0.20(1 - min(d_centroid / d_max, 1)). The production profile recorded",
          "w_3D = 0. Therefore 3D agreement acted as an explicit eligibility and",
          "support gate and was not silently reweighted into the continuous score."
        )
      ),
      formula_item(
        "Final score.",
        "F = 0.60P + 0.40S",
        paste(
          "The final continuous score retained a 60 percent contribution from",
          "the pre-structure evidence layer and a 40 percent contribution from",
          "the structural evidence layer."
        )
      ),
      formula_item(
        "Ordering, tie-breaks and evolutionary-group consolidation.",
        "gate tier (descending), F (descending), completeness (descending), stable identifier",
        paste(
          "Cluster rows were ordered first by the recorded base-gate pass tier,",
          "then final score, evidence completeness and stable cluster identifier.",
          "DeepClust rows belonging to the same primary OrthoFinder group were",
          "consolidated under a deterministic lead cluster. Final evolutionary",
          "rank followed the lead cluster's recorded final rank, with pre-structure",
          "group rank and stable group key as deterministic tie-breaks."
        )
      )
    ),
    shiny::p(
      class = "small text-muted",
      paste(
        "All displayed equations describe the recorded workflow. The explorer",
        "below recomputes only from stored completed-resource values; it does not",
        "rerun orthology, annotation, expression, pocket prediction or alignment."
      )
    ),
    bslib::accordion(
      open = FALSE,
      bslib::accordion_panel(
        "Alternative weighting sensitivity explorer",
        shiny::div(
          class = "alert alert-info",
          paste(
            "Use this as a transparent what-if analysis. Slider values within",
            "each layer are normalised to sum to one. The result is explicitly",
            "non-authoritative and never changes the recorded table, hard gates,",
            "source database or pipeline outputs."
          )
        ),
        shiny::actionButton(
          ns("ranking_reset_weights"),
          "Reset recorded ranking weights",
          class = "btn-primary"
        ),
        bslib::layout_columns(
          ranking_weight_group_ui(ns, "prestructure"),
          ranking_weight_group_ui(ns, "ligandability"),
          ranking_weight_group_ui(ns, "structural"),
          ranking_weight_group_ui(ns, "final"),
          col_widths = c(6, 6, 6, 6)
        ),
        bslib::card(
          bslib::card_header("Optional 3D refinement and ordering"),
          shiny::sliderInput(
            ns("ranking_weight_three_dimensional"),
            "3D refinement weight (recorded default: 0)",
            min = 0,
            max = 1,
            value = 0,
            step = 0.05
          ),
          shiny::checkboxInput(
            ns("ranking_preserve_gate_tier"),
            "Keep recorded hard-gate pass tier ahead of score ordering",
            value = TRUE
          ),
          bslib::layout_columns(
            shiny::numericInput(
              ns("ranking_source_rows"),
              "Rows included in recalculation",
              value = 5000,
              min = 1,
              max = 10000
            ),
            shiny::numericInput(
              ns("ranking_display_rows"),
              "Rows displayed below",
              value = 100,
              min = 1,
              max = 1000
            ),
            col_widths = c(6, 6)
          )
        ),
        shiny::uiOutput(ns("ranking_source_scope")),
        tabular_download_buttons(
          ns = ns,
          tsv_id = "ranking_download_tsv",
          excel_id = "ranking_download_excel",
          tsv_label = "Download exploratory ranking as TSV",
          excel_label = "Download exploratory ranking as Excel"
        ),
        shinycssloaders::withSpinner(DT::DTOutput(ns("ranking_result_table")))
      )
    )
  )
}

#' Result-section UI.
#'
#' @param id Module identifier.
#' @param section Stable result-section identifier.
#' @return Shiny UI.
result_section_ui <- function(id, section) {
  if (!section %in% names(result_section_specs)) {
    stop(paste0("Unknown result section: ", section), call. = FALSE)
  }
  ns <- shiny::NS(id)
  specification <- result_section_specs[[section]]
  shiny::tagList(
    shiny::h3(specification$title),
    shiny::p(class = "grant-question", specification$question),
    if (identical(section, "final_recommendations")) {
      shiny::div(
        class = "alert alert-info",
        paste(
          "See the complete ranking formulas, recorded default weights,",
          "tie-break rules and adjustable sensitivity explorer below the table."
        )
      )
    },
    if (identical(section, "expression")) {
      shiny::div(
        class = "alert alert-info",
        paste(
          "NOT_MAPPED means that no unique Atlas gene mapping was found.",
          "Zero count fields in a legacy relation are not measured zero",
          "expression. Corrected records use the median of Atlas's five-number",
          "summary and classify TPM values at least 0.5 as context-positive.",
          "Tissue choices appear when the selected relation contains",
          "organism_part metadata."
        )
      )
    },
    bslib::layout_columns(
      shiny::selectInput(
        ns("relation"),
        "Result table",
        choices = "Loading..."
      ),
      shiny::numericInput(
        ns("max_rows"),
        "Rows to display",
        value = 500,
        min = 1,
        max = 10000
      ),
      shiny::actionButton(
        ns("preview"),
        "Refresh results",
        class = "btn-primary"
      ),
      col_widths = c(5, 3, 4)
    ),
    if (identical(section, "expression")) {
      shiny::tagList(
        bslib::layout_columns(
          shiny::selectInput(
            ns("expression_species"),
            "Species",
            choices = "All species"
          ),
          shiny::selectInput(
            ns("expression_tissue"),
            "Tissue / organism part",
            choices = "All tissues"
          ),
          shiny::textInput(
            ns("expression_search"),
            "Candidate group, accession or gene",
            value = ""
          ),
          col_widths = c(3, 3, 6)
        ),
        bslib::layout_columns(
          shiny::selectInput(
            ns("expression_metadata_status"),
            "Tissue metadata status",
            choices = "All metadata states"
          ),
          shiny::selectInput(
            ns("expression_positive"),
            "Median TPM threshold",
            choices = c(
              "All values" = "",
              "At least 0.5 TPM" = "true",
              "Below 0.5 TPM" = "false"
            )
          ),
          col_widths = c(6, 6)
        )
      )
    },
    shiny::div(
      class = "column-selector-panel",
      shiny::h4("Columns to display"),
      shiny::p(
        class = "small text-muted",
        "Each section keeps its own selection. All source columns remain available."
      ),
      shiny::div(
        class = "column-selector-actions",
        shiny::actionButton(ns("select_defaults"), "Grant defaults"),
        shiny::actionButton(ns("select_all"), "Select all"),
        shiny::actionButton(ns("select_none"), "Clear")
      ),
      shiny::checkboxGroupInput(
        ns("selected_columns"),
        label = NULL,
        choices = character(),
        selected = character(),
        inline = TRUE
      )
    ),
    tabular_download_buttons(
      ns = ns,
      tsv_id = "download_tsv",
      excel_id = "download_excel",
      tsv_label = "Download displayed rows as TSV",
      excel_label = "Download displayed rows as Excel"
    ),
    shinycssloaders::withSpinner(DT::DTOutput(ns("result_table"))),
    if (identical(section, "final_recommendations")) {
      ranking_methodology_ui(ns)
    }
  )
}

#' Result-section server.
#'
#' @param id Module identifier.
#' @param section Stable result-section identifier.
#' @param resource_source Flexible result source.
#' @param max_rows Global row cap.
#' @return Reactive containing the displayed result.
result_section_server <- function(
  id,
  section,
  resource_source,
  max_rows = 1000L
) {
  shiny::moduleServer(id, function(input, output, session) {
    available_relations <- shiny::reactiveVal(character())
    available_columns <- shiny::reactiveVal(character())

    load_relations <- function() {
      if (!resource_source_available(resource_source)) {
        shiny::updateSelectInput(
          session,
          "relation",
          choices = "Result source not configured"
        )
        return(invisible(character()))
      }
      relations <- tryCatch(
        collect_resource_view_names(resource_source),
        error = function(error) {
          shiny::showNotification(
            paste("Could not list result tables:", conditionMessage(error)),
            type = "error",
            duration = NULL
          )
          character()
        }
      )
      selected <- relations_for_result_section(relations, section)
      if (length(selected) == 0L) {
        selected <- "No recognised result table"
      }
      available_relations(selected)
      shiny::updateSelectInput(
        session,
        "relation",
        choices = selected,
        selected = selected[[1L]]
      )
      invisible(selected)
    }

    load_columns <- function(relation) {
      if (
        is.null(relation) ||
          relation %in% c(
            "Loading...",
            "Result source not configured",
            "No recognised result table"
          )
      ) {
        available_columns(character())
        shiny::updateCheckboxGroupInput(
          session,
          "selected_columns",
          choices = character(),
          selected = character()
        )
        return(invisible(character()))
      }
      columns <- tryCatch(
        collect_resource_columns(resource_source, relation),
        error = function(error) {
          shiny::showNotification(
            paste("Could not inspect result columns:", conditionMessage(error)),
            type = "error",
            duration = NULL
          )
          tibble::tibble(column_name = character())
        }
      )
      names <- as.character(columns$column_name)
      selected <- default_result_columns(section, names)
      available_columns(names)
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = names,
        selected = selected
      )
      if (identical(section, "expression")) {
        expression_filter_choices <- function(column, all_label) {
          if (!column %in% names) {
            return(stats::setNames("", all_label))
          }
          values <- tryCatch(
            collect_distinct_result_values(
              resource_source = resource_source,
              relation = relation,
              column = column
            ),
            error = function(error) {
              character()
            }
          )
          c(stats::setNames("", all_label), values)
        }
        shiny::updateSelectInput(
          session,
          "expression_species",
          choices = expression_filter_choices(
            "species_column",
            "All species"
          ),
          selected = ""
        )
        shiny::updateSelectInput(
          session,
          "expression_tissue",
          choices = expression_filter_choices(
            "organism_part",
            "All tissues"
          ),
          selected = ""
        )
        shiny::updateSelectInput(
          session,
          "expression_metadata_status",
          choices = expression_filter_choices(
            "metadata_status",
            "All metadata states"
          ),
          selected = ""
        )
      }
      invisible(names)
    }

    shiny::observeEvent(TRUE, load_relations(), once = TRUE)
    shiny::observeEvent(input$relation, load_columns(input$relation))
    shiny::observeEvent(input$select_defaults, {
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = available_columns(),
        selected = default_result_columns(section, available_columns())
      )
    })
    shiny::observeEvent(input$select_all, {
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = available_columns(),
        selected = available_columns()
      )
    })
    shiny::observeEvent(input$select_none, {
      shiny::updateCheckboxGroupInput(
        session,
        "selected_columns",
        choices = available_columns(),
        selected = character()
      )
    })

    displayed <- shiny::eventReactive(
      list(
        input$preview,
        input$relation,
        input$selected_columns,
        input$max_rows,
        input$expression_species,
        input$expression_tissue,
        input$expression_metadata_status,
        input$expression_positive,
        input$expression_search
      ),
      {
        if (
          is.null(input$relation) ||
            input$relation %in% c(
              "Loading...",
              "Result source not configured",
              "No recognised result table"
            )
        ) {
          return(tibble::tibble(
            message = "No recognised result table is available for this section."
          ))
        }
        if (length(input$selected_columns) == 0L) {
          return(tibble::tibble(message = "Select at least one result column."))
        }
        row_limit <- min(
          max(1L, as.integer(input$max_rows)),
          as.integer(max_rows)
        )
        tryCatch(
          if (identical(section, "expression")) {
            collect_filtered_expression_result(
              resource_source = resource_source,
              relation = input$relation,
              selected_columns = input$selected_columns,
              available_columns = available_columns(),
              species = input$expression_species %||% "",
              tissue = input$expression_tissue %||% "",
              metadata_status = input$expression_metadata_status %||% "",
              expression_positive = input$expression_positive %||% "",
              search = input$expression_search %||% "",
              max_rows = row_limit
            )
          } else {
            collect_selected_result(
              resource_source = resource_source,
              relation = input$relation,
              selected_columns = input$selected_columns,
              max_rows = row_limit
            )
          },
          error = function(error) {
            shiny::showNotification(
              paste("Could not query result table:", conditionMessage(error)),
              type = "error",
              duration = NULL
            )
            tibble::tibble(error = conditionMessage(error))
          }
        )
      },
      ignoreNULL = FALSE
    )

    output$result_table <- DT::renderDT({
      readable_datatable(
        displayed(),
        rownames = FALSE,
        filter = "top",
        extensions = "Buttons",
        options = list(
          pageLength = 25,
          scrollX = TRUE,
          deferRender = TRUE,
          dom = "tip"
        )
      )
    })
    output$download_tsv <- shiny::downloadHandler(
      filename = function() {
        paste0(section, "_", input$relation %||% "results", ".tsv")
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
        paste0(section, "_", input$relation %||% "results", ".xlsx")
      },
      content = function(path) {
        write_formatted_excel(
          data = displayed(),
          path = path
        )
      }
    )
    if (identical(section, "final_recommendations")) {
      defaults <- recorded_ranking_weights()
      shiny::observeEvent(input$ranking_reset_weights, {
        for (group in names(defaults)) {
          for (component in names(defaults[[group]])) {
            shiny::updateSliderInput(
              session,
              paste0("ranking_weight_", group, "_", component),
              value = defaults[[group]][[component]]
            )
          }
        }
        shiny::updateSliderInput(
          session,
          "ranking_weight_three_dimensional",
          value = 0
        )
        shiny::updateCheckboxInput(
          session,
          "ranking_preserve_gate_tier",
          value = TRUE
        )
      })

      ranking_relation <- shiny::reactive({
        select_ranking_relation(available_relations())
      })

      ranking_columns <- shiny::reactive({
        relation <- ranking_relation()
        if (!nzchar(relation)) {
          return(character())
        }
        tryCatch(
          as.character(
            collect_resource_columns(resource_source, relation)$column_name
          ),
          error = function(error) character()
        )
      })

      ranking_source <- shiny::reactive({
        relation <- ranking_relation()
        columns <- ranking_columns()
        if (!nzchar(relation) || !ranking_source_is_complete(columns)) {
          return(tibble::tibble())
        }
        source_limit <- min(
          max(1L, as.integer(input$ranking_source_rows %||% 5000L)),
          as.integer(max_rows),
          10000L
        )
        tryCatch(
          collect_selected_result(
            resource_source = resource_source,
            relation = relation,
            selected_columns = ranking_source_columns(columns),
            max_rows = source_limit
          ),
          error = function(error) {
            shiny::showNotification(
              paste("Could not load ranking components:", conditionMessage(error)),
              type = "error",
              duration = NULL
            )
            tibble::tibble()
          }
        )
      })

      ranking_weights <- shiny::reactive({
        result <- defaults
        for (group in names(defaults)) {
          result[[group]] <- stats::setNames(
            vapply(names(defaults[[group]]), function(component) {
              input[[paste0("ranking_weight_", group, "_", component)]] %||%
                defaults[[group]][[component]]
            }, numeric(1)),
            names(defaults[[group]])
          )
        }
        result
      })

      exploratory_ranking <- shiny::reactive({
        data <- ranking_source()
        if (nrow(data) == 0L) {
          return(tibble::tibble())
        }
        tryCatch(
          tibble::as_tibble(recompute_exploratory_ranking(
            data = data,
            weights = ranking_weights(),
            three_dimensional_weight =
              input$ranking_weight_three_dimensional %||% 0,
            preserve_gate_tier = isTRUE(input$ranking_preserve_gate_tier)
          )),
          error = function(error) {
            shiny::showNotification(
              paste("Could not recompute sensitivity ranking:", conditionMessage(error)),
              type = "error",
              duration = NULL
            )
            tibble::tibble(error = conditionMessage(error))
          }
        )
      })

      output$ranking_source_scope <- shiny::renderUI({
        relation <- ranking_relation()
        columns <- ranking_columns()
        if (!nzchar(relation)) {
          return(shiny::div(
            class = "alert alert-warning",
            "No recognised ranking relation is available for sensitivity analysis."
          ))
        }
        if (!ranking_source_is_complete(columns)) {
          return(shiny::div(
            class = "alert alert-warning",
            paste(
              relation,
              "does not retain every score component required for reweighting.",
              "The formula explanation above remains authoritative."
            )
          ))
        }
        total <- tryCatch(
          collect_resource_row_count(resource_source, relation),
          error = function(error) NA_real_
        )
        used <- nrow(ranking_source())
        message <- paste(
          "Sensitivity source:", relation, "-", used,
          "stored evolutionary-group rows recalculated."
        )
        if (!is.na(total) && used < total) {
          message <- paste(
            message,
            "The source contains", format(total, big.mark = ","),
            "rows; increase the recalculation limit to include more."
          )
        }
        shiny::div(class = "alert alert-secondary", message)
      })

      output$ranking_result_table <- DT::renderDT({
        ranked <- exploratory_ranking()
        if (nrow(ranked) == 0L) {
          ranked <- tibble::tibble(
            message = "No complete stored ranking rows are available."
          )
        }
        display_limit <- min(
          max(1L, as.integer(input$ranking_display_rows %||% 100L)),
          1000L
        )
        readable_datatable(
          utils::head(ranked, display_limit),
          rownames = FALSE,
          filter = "top",
          options = list(pageLength = 25, dom = "tip")
        )
      })
      output$ranking_download_tsv <- shiny::downloadHandler(
        filename = function() "exploratory_weight_sensitivity_ranking.tsv",
        content = function(path) {
          utils::write.table(
            exploratory_ranking(),
            file = path,
            sep = "\t",
            quote = TRUE,
            row.names = FALSE,
            na = ""
          )
        }
      )
      output$ranking_download_excel <- shiny::downloadHandler(
        filename = function() "exploratory_weight_sensitivity_ranking.xlsx",
        content = function(path) {
          write_formatted_excel(
            data = exploratory_ranking(),
            path = path
          )
        }
      )
    }
    displayed
  })
}
