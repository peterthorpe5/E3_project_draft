#' Candidate and expression visualisation helpers.
#'
#' These helpers query only bounded, read-only subsets of the integrated E3
#' resource. They keep candidate selection, expression units and unavailable
#' evidence explicit so visual exploration cannot silently change the scientific
#' interpretation.

#' Candidate visualisation metric labels.
#'
#' @return Named character vector mapping display labels to relation columns.
candidate_visual_metric_choices <- function() {
  c(
    "Final integrated score" = "final_score",
    "Pre-structure score" = "prestructure_score",
    "Best pre-structure score" = "best_prestructure_score",
    "Mean pre-structure score" = "mean_prestructure_score",
    "Structural score" = "structural_score",
    "Ligandability score" = "ligandability_score",
    "Pocket conservation score" = "pocket_conservation_score",
    "3D pocket score" = "three_dimensional_pocket_score",
    "Target-species fraction" = "target_species_fraction",
    "Mandatory-species fraction" = "mandatory_species_fraction",
    "Domain-supported assessed-species fraction" = "domain_species_fraction",
    "Domain evidence coverage" = "domain_annotation_coverage_fraction",
    "Expression-supported assessed-species fraction" =
      "expression_species_fraction",
    "Expression evidence coverage" = "expression_evidence_coverage_fraction",
    "Structurally assessed species fraction" = "structural_species_fraction",
    "Evidence completeness" = "evidence_completeness_fraction",
    "Minimum member druggability" = "minimum_druggability_score",
    "Mean member druggability" = "mean_druggability_score",
    "Mean pocket pLDDT fraction" = "mean_pocket_plddt_fraction",
    "Pocket-predictor agreement" = "predictor_agreement_fraction",
    "Mean pocket-region overlap" = "mean_pairwise_region_overlap",
    "Chemical-group conservation" = "mean_chemical_group_conservation",
    "Mean minimum TM-score" = "mean_minimum_tm_score",
    "Mean 3D pocket overlap" = "mean_pocket_overlap_fraction",
    "Structural residue-match fraction" =
      "mean_structural_residue_match_fraction",
    "Structural residue identity" =
      "mean_structural_residue_identity_fraction",
    "Structural chemical-group conservation" =
      "mean_structural_chemical_group_conservation",
    "Median pocket-centroid distance (Å)" =
      "median_centroid_distance_angstrom"
  )
}

#' Candidate visualisation relation preference.
#'
#' @return Candidate relation names in scientific-authority order.
candidate_visual_relation_preference <- function() {
  c(
    "final_evolutionary_candidate_prioritisation",
    "candidate_master_results",
    "final_candidate_prioritisation",
    "evolutionary_candidate_group_ranking",
    "prestructure_ranking",
    "candidate_evidence"
  )
}

#' Select the best candidate relation.
#'
#' @param relations Available relation names.
#' @return Preferred relation name, or `NULL`.
select_candidate_visual_relation <- function(relations) {
  selected <- candidate_visual_relation_preference()
  selected <- selected[selected %in% relations]
  if (length(selected) == 0L) {
    return(NULL)
  }
  selected[[1L]]
}

#' Select the best candidate identifier.
#'
#' @param columns Available candidate columns.
#' @return Identifier column, or `NULL`.
select_candidate_visual_identifier <- function(columns) {
  choices <- c(
    "evolutionary_group_key",
    "primary_group_id",
    "cluster_id",
    "lead_cluster_id"
  )
  choices <- choices[choices %in% columns]
  if (length(choices) == 0L) {
    return(NULL)
  }
  choices[[1L]]
}

#' Select the best candidate rank column.
#'
#' @param columns Available candidate columns.
#' @return Rank column, or `NULL`.
select_candidate_visual_rank <- function(columns) {
  choices <- c(
    "final_evolutionary_rank",
    "final_rank",
    "prestructure_evolutionary_group_rank",
    "evolutionary_group_rank",
    "computational_rank",
    "lead_computational_rank"
  )
  choices <- choices[choices %in% columns]
  if (length(choices) == 0L) {
    return(NULL)
  }
  choices[[1L]]
}

#' Select recognised candidate metrics.
#'
#' @param columns Available candidate columns.
#' @return Named metric choices limited to available columns.
candidate_visual_available_metrics <- function(columns) {
  choices <- candidate_visual_metric_choices()
  choices[choices %in% columns]
}

#' Candidate colour choices.
#'
#' @param columns Available candidate columns.
#' @return Named colour choices including statuses and numeric metrics.
candidate_visual_colour_choices <- function(columns) {
  statuses <- c(
    "Recommendation status" = "recommendation_status",
    "Grant-aligned prediction status" = "grant_aligned_prediction_status",
    "All final gates passed" = "grant_aligned_final_pass",
    "All base structural gates passed" = "grant_aligned_base_pass",
    "All pre-structure gates passed" = "grant_aligned_prestructure_pass",
    "Lead stringent gate passed" = "lead_grant_aligned_stringent_pass",
    "Pocket-region conservation status" = "conservation_status",
    "3D alignment status" = "three_dimensional_alignment_status"
  )
  statuses <- statuses[statuses %in% columns]
  c(statuses, candidate_visual_available_metrics(columns = columns))
}

#' Candidate visualisation fields.
#'
#' @param columns Available candidate columns.
#' @return De-duplicated columns required by plots and drill-downs.
candidate_visual_required_columns <- function(columns) {
  identifier <- select_candidate_visual_identifier(columns = columns)
  metrics <- unname(candidate_visual_available_metrics(columns = columns))
  if (is.null(identifier)) {
    stop("Candidate relation has no recognised stable identifier.", call. = FALSE)
  }
  if (length(metrics) < 2L) {
    stop("Candidate relation needs at least two recognised numeric metrics.", call. = FALSE)
  }
  preferred <- c(
    identifier,
    "final_evolutionary_rank",
    "final_rank",
    "prestructure_evolutionary_group_rank",
    "evolutionary_group_rank",
    "computational_rank",
    "lead_computational_rank",
    unname(candidate_visual_colour_choices(columns = columns)),
    "evolutionary_group_key",
    "primary_group_type",
    "primary_group_id",
    "cluster_id",
    "lead_cluster_id",
    "candidate_accessions",
    "lead_candidate_accessions",
    "target_species_present",
    "target_species_missing",
    "domain_supported_species",
    "domain_annotated_negative_species",
    "domain_unavailable_species",
    "expression_supported_species",
    "expression_assessed_negative_species",
    "expression_unavailable_species",
    "lead_expression_supported_species",
    "lead_expression_assessed_negative_species",
    "lead_expression_unavailable_species",
    "inclusion_reasons",
    "exclusion_reasons",
    "missing_evidence",
    "structural_exclusion_reasons",
    metrics
  )
  unique(preferred[preferred %in% columns])
}

#' Build the bounded candidate visualisation query.
#'
#' @param relation Candidate relation.
#' @param columns Explicit selected columns.
#' @param max_rows Maximum candidate rows.
#' @param alias Attached resource alias.
#' @return DuckDB SQL query.
build_candidate_visual_query <- function(
  relation,
  columns,
  max_rows = 5000L,
  alias = "e3_resource"
) {
  max_rows <- suppressWarnings(as.integer(max_rows[[1L]]))
  if (is.na(max_rows) || max_rows < 1L || max_rows > 10000L) {
    stop("Candidate visual row limit must be between 1 and 10000.", call. = FALSE)
  }
  if (length(columns) == 0L) {
    stop("Select at least one candidate visual column.", call. = FALSE)
  }
  safe_columns <- paste(
    vapply(columns, quote_duckdb_identifier, character(1L)),
    collapse = ", "
  )
  rank_column <- select_candidate_visual_rank(columns = columns)
  order_sql <- if (is.null(rank_column)) {
    ""
  } else {
    paste("ORDER BY", quote_duckdb_identifier(rank_column), "NULLS LAST")
  }
  paste(
    "SELECT", safe_columns,
    "FROM", paste0(
      sanitise_duckdb_alias(alias), ".main.",
      quote_duckdb_identifier(relation)
    ),
    order_sql,
    "LIMIT", max_rows
  )
}

#' Collect candidate visualisation data.
#'
#' @param resource_source Flexible E3 result source.
#' @param relation Candidate relation.
#' @param columns Explicit selected columns.
#' @param max_rows Maximum candidate rows.
#' @return Candidate tibble.
collect_candidate_visual_data <- function(
  resource_source,
  relation,
  columns,
  max_rows = 5000L
) {
  collect_resource_query(
    duckdb_path = resource_source,
    query = build_candidate_visual_query(
      relation = relation,
      columns = columns,
      max_rows = max_rows
    )
  )
}

#' Prepare candidate visualisation data.
#'
#' @param candidate_tbl Candidate rows.
#' @param identifier_column Stable identifier column.
#' @param metric_columns Numeric metric columns.
#' @return Prepared candidate tibble with `.candidate_key`.
prepare_candidate_visual_data <- function(
  candidate_tbl,
  identifier_column,
  metric_columns
) {
  required <- unique(c(identifier_column, metric_columns))
  missing <- setdiff(required, names(candidate_tbl))
  if (length(missing) > 0L) {
    stop(
      paste("Candidate visual columns are unavailable:", paste(missing, collapse = ", ")),
      call. = FALSE
    )
  }
  prepared <- candidate_tbl |>
    dplyr::mutate(
      .candidate_key = trimws(as.character(.data[[identifier_column]]))
    ) |>
    dplyr::filter(!is.na(.data$.candidate_key), .data$.candidate_key != "") |>
    dplyr::mutate(
      dplyr::across(
        dplyr::all_of(metric_columns),
        ~ suppressWarnings(as.numeric(.x))
      )
    ) |>
    dplyr::distinct(.data$.candidate_key, .keep_all = TRUE)
  if (nrow(prepared) == 0L) {
    stop("No candidate rows have a stable identifier.", call. = FALSE)
  }
  prepared
}

#' Get a candidate metric display label.
#'
#' @param column Candidate metric column.
#' @return Human-readable metric label.
candidate_visual_metric_label <- function(column) {
  choices <- candidate_visual_metric_choices()
  matched <- names(choices)[choices == column]
  if (length(matched) == 0L) {
    return(gsub("_", " ", column, fixed = TRUE))
  }
  matched[[1L]]
}

#' Build the interactive candidate landscape.
#'
#' @param candidate_tbl Prepared candidate rows.
#' @param x_column Numeric x-axis metric.
#' @param y_column Numeric y-axis metric.
#' @param colour_column Optional colour field.
#' @param size_column Optional point-size metric.
#' @param source Plotly event source identifier.
#' @return Plotly scatter plot.
build_candidate_visual_landscape_plot <- function(
  candidate_tbl,
  x_column,
  y_column,
  colour_column = "",
  size_column = "",
  source = "candidate_landscape"
) {
  selected <- c(x_column, y_column, colour_column, size_column)
  selected <- selected[nzchar(selected)]
  missing <- setdiff(selected, names(candidate_tbl))
  if (length(missing) > 0L) {
    stop(
      paste("Candidate plot columns are unavailable:", paste(missing, collapse = ", ")),
      call. = FALSE
    )
  }
  plot_tbl <- candidate_tbl |>
    dplyr::filter(!is.na(.data[[x_column]]), !is.na(.data[[y_column]]))
  if (nrow(plot_tbl) == 0L) {
    stop("No candidates have values for both selected axes.", call. = FALSE)
  }
  hover <- paste0(
    "Candidate: ", plot_tbl$.candidate_key,
    "<br>", candidate_visual_metric_label(x_column), ": ",
    signif(plot_tbl[[x_column]], 4),
    "<br>", candidate_visual_metric_label(y_column), ": ",
    signif(plot_tbl[[y_column]], 4)
  )
  arguments <- list(
    data = plot_tbl,
    x = plot_tbl[[x_column]],
    y = plot_tbl[[y_column]],
    key = plot_tbl$.candidate_key,
    customdata = plot_tbl$.candidate_key,
    text = hover,
    hoverinfo = "text",
    type = "scatter",
    mode = "markers",
    source = source,
    marker = list(opacity = 0.78)
  )
  if (nzchar(colour_column)) {
    arguments$color <- plot_tbl[[colour_column]]
  }
  if (nzchar(size_column)) {
    arguments$size <- pmax(0, suppressWarnings(as.numeric(plot_tbl[[size_column]])))
    arguments$sizes <- c(8, 30)
  }
  plot <- do.call(plotly::plot_ly, arguments)
  plot <- plotly::layout(
    plot,
    xaxis = list(title = candidate_visual_metric_label(x_column)),
    yaxis = list(title = candidate_visual_metric_label(y_column)),
    dragmode = "select",
    margin = list(l = 60, r = 20, t = 20, b = 60)
  )
  plotly::event_register(plot, "plotly_click")
}

#' Candidate selector labels.
#'
#' @param candidate_tbl Prepared candidate data.
#' @param rank_column Optional rank column.
#' @return Named character choices for a Shiny selector.
candidate_visual_display_choices <- function(candidate_tbl, rank_column = NULL) {
  keys <- as.character(candidate_tbl$.candidate_key)
  if (is.null(rank_column) || !rank_column %in% names(candidate_tbl)) {
    return(stats::setNames(keys, keys))
  }
  ranks <- suppressWarnings(as.integer(candidate_tbl[[rank_column]]))
  labels <- ifelse(
    is.na(ranks),
    keys,
    paste0("Rank ", format(ranks, big.mark = ","), " — ", keys)
  )
  stats::setNames(keys, labels)
}

#' Extract candidate identifiers from one row.
#'
#' @param candidate_row One-row candidate tibble/data frame.
#' @return Named character identifiers.
candidate_visual_identifiers <- function(candidate_row) {
  choices <- c(
    "evolutionary_group_key",
    "primary_group_id",
    "cluster_id",
    "lead_cluster_id"
  )
  choices <- choices[choices %in% names(candidate_row)]
  values <- vapply(
    choices,
    function(column) as.character(candidate_row[[column]][[1L]]),
    character(1L)
  )
  keep <- !is.na(values) & nzchar(trimws(values))
  values[keep]
}

#' Resolve candidate match terms for an evidence relation.
#'
#' @param columns Evidence relation columns.
#' @param identifiers Named selected-candidate identifiers.
#' @return Tibble containing exact-match column/value pairs.
candidate_visual_match_terms <- function(columns, identifiers) {
  records <- list()
  add_term <- function(column, value) {
    if (column %in% columns && !is.null(value) && nzchar(trimws(value))) {
      records[[length(records) + 1L]] <<- tibble::tibble(
        column = column,
        value = trimws(value)
      )
    }
  }
  if ("evolutionary_group_key" %in% names(identifiers)) {
    add_term("evolutionary_group_key", identifiers[["evolutionary_group_key"]])
  }
  if ("primary_group_id" %in% names(identifiers)) {
    add_term("primary_group_id", identifiers[["primary_group_id"]])
    add_term("group_id", identifiers[["primary_group_id"]])
  }
  if ("cluster_id" %in% names(identifiers)) {
    add_term("cluster_id", identifiers[["cluster_id"]])
  } else if ("lead_cluster_id" %in% names(identifiers)) {
    add_term("cluster_id", identifiers[["lead_cluster_id"]])
  }
  if ("lead_cluster_id" %in% names(identifiers)) {
    add_term("lead_cluster_id", identifiers[["lead_cluster_id"]])
  }
  if (length(records) == 0L) {
    return(tibble::tibble(column = character(), value = character()))
  }
  dplyr::distinct(dplyr::bind_rows(records), .data$column, .data$value)
}

#' Find evidence relations filterable to a selected candidate.
#'
#' @param resource_source Flexible E3 result source.
#' @param identifiers Named selected-candidate identifiers.
#' @return Relation names with a compatible exact-match field.
candidate_visual_evidence_relations <- function(resource_source, identifiers) {
  relations <- collect_resource_view_names(duckdb_path = resource_source)
  matched <- vapply(
    relations,
    function(relation) {
      columns <- collect_resource_columns(
        duckdb_path = resource_source,
        view_name = relation
      )$column_name
      nrow(candidate_visual_match_terms(
        columns = columns,
        identifiers = identifiers
      )) > 0L
    },
    logical(1L)
  )
  relations[matched]
}

#' Build a selected-candidate evidence query.
#'
#' @param relation Evidence relation.
#' @param match_terms Exact-match column/value pairs.
#' @param max_rows Maximum evidence rows.
#' @param alias Attached resource alias.
#' @return DuckDB SQL query.
build_candidate_visual_evidence_query <- function(
  relation,
  match_terms,
  max_rows = 1000L,
  alias = "e3_resource"
) {
  max_rows <- suppressWarnings(as.integer(max_rows[[1L]]))
  if (is.na(max_rows) || max_rows < 1L || max_rows > 10000L) {
    stop("Candidate evidence row limit must be between 1 and 10000.", call. = FALSE)
  }
  if (nrow(match_terms) == 0L) {
    stop("Evidence relation has no compatible candidate identifier.", call. = FALSE)
  }
  clauses <- vapply(
    seq_len(nrow(match_terms)),
    function(index) {
      paste0(
        "CAST(", quote_duckdb_identifier(match_terms$column[[index]]),
        " AS VARCHAR) = '", escape_sql_literal(match_terms$value[[index]]), "'"
      )
    },
    character(1L)
  )
  paste(
    "SELECT * FROM",
    paste0(
      sanitise_duckdb_alias(alias), ".main.",
      quote_duckdb_identifier(relation)
    ),
    "WHERE (", paste(clauses, collapse = " OR "), ")",
    "LIMIT", max_rows
  )
}

#' Collect selected-candidate evidence rows.
#'
#' @param resource_source Flexible E3 result source.
#' @param relation Evidence relation.
#' @param identifiers Named selected-candidate identifiers.
#' @param max_rows Maximum evidence rows.
#' @return Matching evidence tibble.
collect_candidate_visual_evidence <- function(
  resource_source,
  relation,
  identifiers,
  max_rows = 1000L
) {
  columns <- collect_resource_columns(
    duckdb_path = resource_source,
    view_name = relation
  )$column_name
  terms <- candidate_visual_match_terms(
    columns = columns,
    identifiers = identifiers
  )
  collect_resource_query(
    duckdb_path = resource_source,
    query = build_candidate_visual_evidence_query(
      relation = relation,
      match_terms = terms,
      max_rows = max_rows
    )
  )
}

#' Select a candidate-expression link column.
#'
#' @param candidate_columns Candidate relation columns.
#' @param expression_columns Expression relation columns.
#' @return Shared exact identifier column, or `NULL`.
candidate_expression_link_column <- function(
  candidate_columns,
  expression_columns
) {
  choices <- c("primary_group_id", "cluster_id")
  choices <- choices[
    choices %in% candidate_columns & choices %in% expression_columns
  ]
  if (length(choices) == 0L) {
    return(NULL)
  }
  choices[[1L]]
}

#' Expression heatmap context choices.
#'
#' @param expression_columns Available expression columns.
#' @return Named context choices.
candidate_expression_context_choices <- function(expression_columns) {
  choices <- c(
    "Tissue / organism part" = "organism_part",
    "Developmental stage" = "developmental_stage",
    "Condition" = "condition",
    "Expression context" = "expression_context",
    "Experiment accession" = "experiment_accession",
    "Atlas sample / condition group" = "sample_or_condition"
  )
  choices[choices %in% expression_columns]
}

#' Build a candidate expression heatmap query.
#'
#' @param relation Expression-context relation.
#' @param candidate_column Exact candidate identifier column.
#' @param candidate_ids One to 25 selected candidates.
#' @param context_column Selected biological-context column.
#' @param expression_unit Exact expression unit.
#' @param species Exact species or empty for all.
#' @param max_cells Maximum aggregated cells.
#' @param alias Attached resource alias.
#' @return DuckDB SQL query.
build_candidate_expression_heatmap_query <- function(
  relation,
  candidate_column,
  candidate_ids,
  context_column,
  expression_unit,
  species = "",
  max_cells = 10000L,
  alias = "e3_resource"
) {
  candidate_ids <- unique(trimws(as.character(candidate_ids)))
  candidate_ids <- candidate_ids[nzchar(candidate_ids)]
  if (length(candidate_ids) < 1L || length(candidate_ids) > 25L) {
    stop("Select between 1 and 25 candidates for the heatmap.", call. = FALSE)
  }
  max_cells <- suppressWarnings(as.integer(max_cells[[1L]]))
  if (is.na(max_cells) || max_cells < 1L || max_cells > 50000L) {
    stop("Expression heatmap cell limit must be between 1 and 50000.", call. = FALSE)
  }
  if (!context_column %in% c(
    "organism_part",
    "developmental_stage",
    "condition",
    "expression_context",
    "experiment_accession",
    "sample_or_condition"
  )) {
    stop("Unsupported expression heatmap context.", call. = FALSE)
  }
  if (!nzchar(trimws(expression_unit))) {
    stop("Select one expression unit; units must not be combined.", call. = FALSE)
  }
  candidate_literals <- paste0(
    "'", escape_sql_literal(candidate_ids), "'",
    collapse = ", "
  )
  conditions <- c(
    paste0(
      "CAST(", quote_duckdb_identifier(candidate_column),
      " AS VARCHAR) IN (", candidate_literals, ")"
    ),
    "TRY_CAST(expression_value AS DOUBLE) IS NOT NULL",
    paste0(
      "CAST(expression_unit AS VARCHAR) = '",
      escape_sql_literal(expression_unit), "'"
    )
  )
  if (nzchar(trimws(species))) {
    conditions <- c(
      conditions,
      paste0(
        "CAST(species_column AS VARCHAR) = '",
        escape_sql_literal(species), "'"
      )
    )
  }
  paste(
    "SELECT",
    paste0(
      "CAST(", quote_duckdb_identifier(candidate_column),
      " AS VARCHAR) AS candidate_id,"
    ),
    paste(
      "COALESCE(NULLIF(trim(CAST(species_column AS VARCHAR)), ''),",
      "'Unknown') AS species,"
    ),
    paste0(
      "COALESCE(NULLIF(trim(CAST(", quote_duckdb_identifier(context_column),
      " AS VARCHAR)), ''), 'Unknown') AS context_label,"
    ),
    "CAST(expression_unit AS VARCHAR) AS expression_unit,",
    "median(TRY_CAST(expression_value AS DOUBLE)) AS median_expression,",
    "COUNT(*) AS context_row_count,",
    "COUNT(DISTINCT CAST(member_accession AS VARCHAR)) AS mapped_member_count,",
    paste(
      "AVG(CASE WHEN CAST(expression_positive AS BOOLEAN) THEN 1.0",
      "ELSE 0.0 END) AS positive_context_fraction"
    ),
    "FROM",
    paste0(
      sanitise_duckdb_alias(alias), ".main.",
      quote_duckdb_identifier(relation)
    ),
    "WHERE", paste(conditions, collapse = " AND "),
    "GROUP BY candidate_id, species, context_label, expression_unit",
    "ORDER BY candidate_id, species, context_label",
    "LIMIT", max_cells
  )
}

#' Collect candidate expression heatmap cells.
#'
#' @param resource_source Flexible E3 result source.
#' @param relation Expression-context relation.
#' @param candidate_column Exact candidate identifier column.
#' @param candidate_ids Selected candidates.
#' @param context_column Selected biological-context column.
#' @param expression_unit Exact expression unit.
#' @param species Exact species or empty for all.
#' @return Aggregated expression cells.
collect_candidate_expression_heatmap <- function(
  resource_source,
  relation,
  candidate_column,
  candidate_ids,
  context_column,
  expression_unit,
  species = ""
) {
  collect_resource_query(
    duckdb_path = resource_source,
    query = build_candidate_expression_heatmap_query(
      relation = relation,
      candidate_column = candidate_column,
      candidate_ids = candidate_ids,
      context_column = context_column,
      expression_unit = expression_unit,
      species = species
    )
  )
}

#' Prepare expression heatmap cells.
#'
#' @param expression_tbl Aggregated expression cells.
#' @param log_transform Whether to use `log2(1 + expression)`.
#' @return Prepared heatmap tibble.
prepare_candidate_expression_heatmap <- function(
  expression_tbl,
  log_transform = TRUE
) {
  required <- c(
    "candidate_id",
    "species",
    "context_label",
    "expression_unit",
    "median_expression",
    "context_row_count"
  )
  missing <- setdiff(required, names(expression_tbl))
  if (length(missing) > 0L) {
    stop(
      paste("Expression heatmap columns are unavailable:", paste(missing, collapse = ", ")),
      call. = FALSE
    )
  }
  expression_tbl |>
    dplyr::mutate(
      median_expression = suppressWarnings(as.numeric(.data$median_expression)),
      species = dplyr::coalesce(as.character(.data$species), "Unknown"),
      context_label = dplyr::coalesce(
        as.character(.data$context_label),
        "Unknown"
      ),
      display_context = paste(
        gsub("_", " ", .data$species, fixed = TRUE),
        .data$context_label,
        sep = " — "
      ),
      plot_value = if (isTRUE(log_transform)) {
        log2(1 + pmax(0, .data$median_expression))
      } else {
        .data$median_expression
      }
    ) |>
    dplyr::filter(!is.na(.data$candidate_id), !is.na(.data$median_expression))
}

#' Build the candidate expression heatmap plot.
#'
#' @param expression_tbl Aggregated expression cells.
#' @param log_transform Whether to use `log2(1 + expression)`.
#' @return ggplot heatmap.
build_candidate_expression_heatmap_plot <- function(
  expression_tbl,
  log_transform = TRUE
) {
  prepared <- prepare_candidate_expression_heatmap(
    expression_tbl = expression_tbl,
    log_transform = log_transform
  )
  if (nrow(prepared) == 0L) {
    return(make_empty_expression_plot("No mapped expression contexts are available."))
  }
  unit <- as.character(prepared$expression_unit[[1L]])
  fill_label <- if (isTRUE(log_transform)) {
    paste0("log2(1 + ", unit, ")")
  } else {
    unit
  }
  ggplot2::ggplot(
    data = prepared,
    mapping = ggplot2::aes(
      x = .data$display_context,
      y = .data$candidate_id,
      fill = .data$plot_value,
      text = paste0(
        "Candidate: ", .data$candidate_id,
        "<br>Species / context: ", .data$display_context,
        "<br>Median ", unit, ": ", signif(.data$median_expression, 4),
        "<br>Contributing rows: ", .data$context_row_count,
        "<br>Mapped members: ", .data$mapped_member_count
      )
    )
  ) +
    ggplot2::geom_tile() +
    ggplot2::scale_fill_gradient(
      low = "#ffffff",
      high = "#cb181d",
      na.value = "transparent"
    ) +
    ggplot2::labs(
      x = "Species and biological context",
      y = "Candidate group",
      fill = fill_label
    ) +
    ggplot2::theme_minimal() +
    ggplot2::theme(
      axis.text.x = ggplot2::element_text(angle = 45, hjust = 1)
    )
}

#' Build exact candidate expression profile query.
#'
#' @param relation Expression-context relation.
#' @param candidate_column Exact candidate identifier column.
#' @param candidate_id Selected candidate.
#' @param expression_unit Exact expression unit.
#' @param species Exact species or empty for all.
#' @param max_rows Maximum Atlas rows.
#' @param alias Attached resource alias.
#' @return DuckDB SQL query.
build_candidate_expression_profile_query <- function(
  relation,
  candidate_column,
  candidate_id,
  expression_unit,
  species = "",
  max_rows = 10000L,
  alias = "e3_resource"
) {
  if (!nzchar(trimws(candidate_id))) {
    stop("Select one candidate for the species/tissue profile.", call. = FALSE)
  }
  if (!nzchar(trimws(expression_unit))) {
    stop("Select one expression unit; units must not be combined.", call. = FALSE)
  }
  max_rows <- suppressWarnings(as.integer(max_rows[[1L]]))
  if (is.na(max_rows) || max_rows < 1L || max_rows > 50000L) {
    stop("Expression profile row limit must be between 1 and 50000.", call. = FALSE)
  }
  conditions <- c(
    paste0(
      "CAST(", quote_duckdb_identifier(candidate_column),
      " AS VARCHAR) = '", escape_sql_literal(candidate_id), "'"
    ),
    paste0(
      "CAST(expression_unit AS VARCHAR) = '",
      escape_sql_literal(expression_unit), "'"
    )
  )
  if (nzchar(trimws(species))) {
    conditions <- c(
      conditions,
      paste0(
        "CAST(species_column AS VARCHAR) = '",
        escape_sql_literal(species), "'"
      )
    )
  }
  paste(
    "SELECT * FROM",
    paste0(
      sanitise_duckdb_alias(alias), ".main.",
      quote_duckdb_identifier(relation)
    ),
    "WHERE", paste(conditions, collapse = " AND "),
    paste(
      "ORDER BY species_column, organism_part, gene_id,",
      "experiment_accession, sample_or_condition"
    ),
    "LIMIT", max_rows
  )
}

#' Collect exact candidate expression profile rows.
#'
#' @param resource_source Flexible E3 result source.
#' @param relation Expression-context relation.
#' @param candidate_column Exact candidate identifier column.
#' @param candidate_id Selected candidate.
#' @param expression_unit Exact expression unit.
#' @param species Exact species or empty for all.
#' @param max_rows Maximum Atlas rows.
#' @return Exact candidate expression rows.
collect_candidate_expression_profile <- function(
  resource_source,
  relation,
  candidate_column,
  candidate_id,
  expression_unit,
  species = "",
  max_rows = 10000L
) {
  collect_resource_query(
    duckdb_path = resource_source,
    query = build_candidate_expression_profile_query(
      relation = relation,
      candidate_column = candidate_column,
      candidate_id = candidate_id,
      expression_unit = expression_unit,
      species = species,
      max_rows = max_rows
    )
  )
}

#' Build a complete species/tissue expression-summary query.
#'
#' The limit is applied only after every matching source context has been
#' aggregated. It therefore bounds plotted tissue cells without truncating the
#' source rows used to calculate medians, ranges or counts.
#'
#' @param relation Expression-context relation.
#' @param candidate_column Exact candidate identifier column.
#' @param candidate_id Selected candidate.
#' @param expression_unit Exact expression unit.
#' @param species Exact species or empty for all.
#' @param max_tissues Maximum post-aggregation species/tissue cells.
#' @param alias Attached resource alias.
#' @return DuckDB SQL query.
build_candidate_species_tissue_summary_query <- function(
  relation,
  candidate_column,
  candidate_id,
  expression_unit,
  species = "",
  max_tissues = 5000L,
  alias = "e3_resource"
) {
  if (!nzchar(trimws(candidate_id))) {
    stop("Select one candidate for the species/tissue profile.", call. = FALSE)
  }
  if (!nzchar(trimws(expression_unit))) {
    stop("Select one expression unit; units must not be combined.", call. = FALSE)
  }
  max_tissues <- suppressWarnings(as.integer(max_tissues[[1L]]))
  if (is.na(max_tissues) || max_tissues < 1L || max_tissues > 10000L) {
    stop(
      "Expression tissue-cell limit must be between 1 and 10000.",
      call. = FALSE
    )
  }
  conditions <- c(
    paste0(
      "CAST(", quote_duckdb_identifier(candidate_column),
      " AS VARCHAR) = '", escape_sql_literal(candidate_id), "'"
    ),
    paste0(
      "CAST(expression_unit AS VARCHAR) = '",
      escape_sql_literal(expression_unit), "'"
    ),
    "TRY_CAST(expression_value AS DOUBLE) IS NOT NULL"
  )
  if (nzchar(trimws(species))) {
    conditions <- c(
      conditions,
      paste0(
        "CAST(species_column AS VARCHAR) = '",
        escape_sql_literal(species), "'"
      )
    )
  }
  paste(
    "SELECT",
    paste(
      "COALESCE(NULLIF(trim(CAST(species_column AS VARCHAR)), ''),",
      "'Unknown') AS species,"
    ),
    paste(
      "COALESCE(NULLIF(trim(CAST(organism_part AS VARCHAR)), ''),",
      "NULLIF(trim(CAST(expression_context AS VARCHAR)), ''),",
      "'Unknown') AS tissue,"
    ),
    "median(TRY_CAST(expression_value AS DOUBLE)) AS median_expression,",
    "min(TRY_CAST(expression_value AS DOUBLE)) AS minimum_expression,",
    "max(TRY_CAST(expression_value AS DOUBLE)) AS maximum_expression,",
    "COUNT(*) AS context_row_count,",
    "COUNT(DISTINCT CAST(member_accession AS VARCHAR)) AS mapped_member_count,",
    paste(
      "AVG(CASE WHEN CAST(expression_positive AS BOOLEAN) THEN 1.0",
      "ELSE 0.0 END) AS positive_context_fraction"
    ),
    "FROM",
    paste0(
      sanitise_duckdb_alias(alias), ".main.",
      quote_duckdb_identifier(relation)
    ),
    "WHERE", paste(conditions, collapse = " AND "),
    "GROUP BY species, tissue",
    "ORDER BY species, tissue",
    "LIMIT", max_tissues
  )
}

#' Collect complete candidate species/tissue summaries.
#'
#' @param resource_source Flexible E3 result source.
#' @param relation Expression-context relation.
#' @param candidate_column Exact candidate identifier column.
#' @param candidate_id Selected candidate.
#' @param expression_unit Exact expression unit.
#' @param species Exact species or empty for all.
#' @param max_tissues Maximum post-aggregation species/tissue cells.
#' @return Complete species/tissue summary.
collect_candidate_species_tissue_summary <- function(
  resource_source,
  relation,
  candidate_column,
  candidate_id,
  expression_unit,
  species = "",
  max_tissues = 5000L
) {
  collect_resource_query(
    duckdb_path = resource_source,
    query = build_candidate_species_tissue_summary_query(
      relation = relation,
      candidate_column = candidate_column,
      candidate_id = candidate_id,
      expression_unit = expression_unit,
      species = species,
      max_tissues = max_tissues
    )
  )
}

#' Prepare complete species/tissue summary cells for plotting.
#'
#' @param summary_tbl Database-aggregated species/tissue summary.
#' @param log_transform Whether to use `log2(1 + expression)`.
#' @return Prepared profile summary with plot values and ranges.
prepare_candidate_species_tissue_summary <- function(
  summary_tbl,
  log_transform = TRUE
) {
  required <- c(
    "species",
    "tissue",
    "median_expression",
    "minimum_expression",
    "maximum_expression",
    "context_row_count",
    "mapped_member_count",
    "positive_context_fraction"
  )
  missing <- setdiff(required, names(summary_tbl))
  if (length(missing) > 0L) {
    stop(
      paste(
        "Species/tissue summary columns are unavailable:",
        paste(missing, collapse = ", ")
      ),
      call. = FALSE
    )
  }
  prepared <- summary_tbl |>
    dplyr::mutate(
      dplyr::across(
        dplyr::all_of(c(
          "median_expression",
          "minimum_expression",
          "maximum_expression",
          "context_row_count",
          "mapped_member_count",
          "positive_context_fraction"
        )),
        ~ suppressWarnings(as.numeric(.x))
      ),
      species = dplyr::coalesce(as.character(.data$species), "Unknown"),
      tissue = dplyr::coalesce(as.character(.data$tissue), "Unknown")
    ) |>
    dplyr::filter(!is.na(.data$median_expression))
  transform_value <- function(value) {
    if (isTRUE(log_transform)) {
      return(log2(1 + pmax(0, value)))
    }
    value
  }
  prepared |>
    dplyr::mutate(
      plot_value = transform_value(.data$median_expression),
      plot_minimum = transform_value(.data$minimum_expression),
      plot_maximum = transform_value(.data$maximum_expression),
      error_minimum = .data$plot_value - .data$plot_minimum,
      error_maximum = .data$plot_maximum - .data$plot_value
    ) |>
    dplyr::arrange(.data$species, .data$tissue)
}

#' Prepare linked species/tissue expression profiles.
#'
#' @param expression_tbl Exact candidate expression rows.
#' @param log_transform Whether to use `log2(1 + expression)`.
#' @return Species/tissue summary tibble.
prepare_candidate_species_tissue_profile <- function(
  expression_tbl,
  log_transform = TRUE
) {
  required <- c("species_column", "organism_part", "expression_value")
  missing <- setdiff(required, names(expression_tbl))
  if (length(missing) > 0L) {
    stop(
      paste("Species/tissue profile columns are unavailable:", paste(missing, collapse = ", ")),
      call. = FALSE
    )
  }
  if (!"expression_context" %in% names(expression_tbl)) {
    expression_tbl$expression_context <- NA_character_
  }
  prepared <- expression_tbl |>
    dplyr::mutate(
      expression_value = suppressWarnings(as.numeric(.data$expression_value)),
      species = dplyr::coalesce(as.character(.data$species_column), "Unknown"),
      tissue = trimws(dplyr::coalesce(as.character(.data$organism_part), "")),
      tissue = dplyr::if_else(
        .data$tissue == "" & "expression_context" %in% names(expression_tbl),
        dplyr::coalesce(as.character(.data$expression_context), "Unknown"),
        .data$tissue
      ),
      tissue = dplyr::if_else(.data$tissue == "", "Unknown", .data$tissue)
    ) |>
    dplyr::filter(!is.na(.data$expression_value))
  summary <- prepared |>
    dplyr::group_by(.data$species, .data$tissue) |>
    dplyr::summarise(
      median_expression = stats::median(.data$expression_value),
      minimum_expression = min(.data$expression_value),
      maximum_expression = max(.data$expression_value),
      context_row_count = dplyr::n(),
      mapped_member_count = if ("member_accession" %in% names(prepared)) {
        dplyr::n_distinct(.data$member_accession)
      } else {
        0L
      },
      positive_context_fraction = if (
        "expression_positive" %in% names(prepared)
      ) {
        mean(as.logical(.data$expression_positive), na.rm = TRUE)
      } else {
        NA_real_
      },
      .groups = "drop"
    )
  transform_value <- function(value) {
    if (isTRUE(log_transform)) {
      return(log2(1 + pmax(0, value)))
    }
    value
  }
  summary |>
    dplyr::mutate(
      plot_value = transform_value(.data$median_expression),
      plot_minimum = transform_value(.data$minimum_expression),
      plot_maximum = transform_value(.data$maximum_expression),
      error_minimum = .data$plot_value - .data$plot_minimum,
      error_maximum = .data$plot_maximum - .data$plot_value
    ) |>
    dplyr::arrange(.data$species, .data$tissue)
}

#' Build linked species/tissue expression plot.
#'
#' @param profile_tbl Species/tissue profile summary.
#' @param expression_unit Exact expression unit.
#' @param log_transform Whether values use `log2(1 + expression)`.
#' @return Faceted ggplot profile.
build_candidate_species_tissue_plot <- function(
  profile_tbl,
  expression_unit,
  log_transform = TRUE
) {
  if (nrow(profile_tbl) == 0L) {
    return(make_empty_expression_plot("No tissue-annotated expression rows are available."))
  }
  y_label <- if (isTRUE(log_transform)) {
    paste0("log2(1 + median ", expression_unit, ")")
  } else {
    paste0("Median ", expression_unit)
  }
  ggplot2::ggplot(
    data = profile_tbl,
    mapping = ggplot2::aes(
      x = .data$tissue,
      y = .data$plot_value,
      size = .data$context_row_count,
      text = paste0(
        "Species: ", gsub("_", " ", .data$species, fixed = TRUE),
        "<br>Tissue: ", .data$tissue,
        "<br>Median ", expression_unit, ": ",
        signif(.data$median_expression, 4),
        "<br>Range: ", signif(.data$minimum_expression, 4), "–",
        signif(.data$maximum_expression, 4),
        "<br>Context rows: ", .data$context_row_count,
        "<br>Mapped members: ", .data$mapped_member_count
      )
    )
  ) +
    ggplot2::geom_errorbar(
      ggplot2::aes(
        ymin = .data$plot_minimum,
        ymax = .data$plot_maximum
      ),
      width = 0.15
    ) +
    ggplot2::geom_point(alpha = 0.8) +
    ggplot2::facet_wrap(~species, scales = "free_x", ncol = 3L) +
    ggplot2::labs(
      x = "Tissue / organism part",
      y = y_label,
      size = "Context rows"
    ) +
    ggplot2::theme_minimal() +
    ggplot2::theme(
      axis.text.x = ggplot2::element_text(angle = 45, hjust = 1)
    )
}

#' Detect valid differential-expression relations.
#'
#' @param resource_source Flexible E3 result source.
#' @return Capability tibble. Empty output means volcano plotting is invalid.
detect_candidate_differential_relations <- function(resource_source) {
  effects <- c(
    "log2_fold_change",
    "log2fc",
    "log2_foldchange",
    "log_fold_change"
  )
  significance <- c(
    "adjusted_p_value",
    "adjusted_pvalue",
    "padj",
    "fdr",
    "q_value",
    "p_value",
    "pvalue"
  )
  labels <- c(
    "gene_name",
    "gene_id",
    "primary_group_id",
    "member_accession",
    "cluster_id"
  )
  relations <- collect_resource_view_names(duckdb_path = resource_source)
  relation_labels <- tolower(relations)
  relations <- relations[
    grepl("expression|differential|transcript|(^|_)de(_|$)", relation_labels)
  ]
  records <- lapply(relations, function(relation) {
    columns <- collect_resource_columns(
      duckdb_path = resource_source,
      view_name = relation
    )$column_name
    effect <- effects[effects %in% columns]
    p_column <- significance[significance %in% columns]
    label <- labels[labels %in% columns]
    if (length(effect) == 0L || length(p_column) == 0L) {
      return(NULL)
    }
    tibble::tibble(
      relation = relation,
      effect_column = effect[[1L]],
      significance_column = p_column[[1L]],
      label_column = if (length(label) == 0L) effect[[1L]] else label[[1L]]
    )
  })
  records <- Filter(Negate(is.null), records)
  if (length(records) == 0L) {
    return(tibble::tibble(
      relation = character(),
      effect_column = character(),
      significance_column = character(),
      label_column = character()
    ))
  }
  dplyr::bind_rows(records)
}

#' Build a differential-expression query.
#'
#' @param capability One-row capability record.
#' @param max_rows Maximum result rows.
#' @param alias Attached resource alias.
#' @return DuckDB SQL query.
build_candidate_volcano_query <- function(
  capability,
  max_rows = 10000L,
  alias = "e3_resource"
) {
  max_rows <- suppressWarnings(as.integer(max_rows[[1L]]))
  if (is.na(max_rows) || max_rows < 1L || max_rows > 50000L) {
    stop("Differential-expression row limit must be between 1 and 50000.", call. = FALSE)
  }
  relation <- as.character(capability$relation[[1L]])
  effect <- quote_duckdb_identifier(as.character(capability$effect_column[[1L]]))
  significance <- quote_duckdb_identifier(
    as.character(capability$significance_column[[1L]])
  )
  label <- quote_duckdb_identifier(as.character(capability$label_column[[1L]]))
  paste(
    "SELECT",
    paste0("CAST(", label, " AS VARCHAR) AS label,"),
    paste0("TRY_CAST(", effect, " AS DOUBLE) AS effect_size,"),
    paste0(
      "TRY_CAST(", significance,
      " AS DOUBLE) AS significance_value"
    ),
    "FROM",
    paste0(
      sanitise_duckdb_alias(alias), ".main.",
      quote_duckdb_identifier(relation)
    ),
    paste0("WHERE TRY_CAST(", effect, " AS DOUBLE) IS NOT NULL"),
    paste0("AND TRY_CAST(", significance, " AS DOUBLE) > 0.0"),
    paste0("AND TRY_CAST(", significance, " AS DOUBLE) <= 1.0"),
    paste0("ORDER BY TRY_CAST(", significance, " AS DOUBLE) ASC"),
    "LIMIT", max_rows
  )
}

#' Prepare and classify volcano rows.
#'
#' @param differential_tbl Standardised differential-expression rows.
#' @param effect_threshold Absolute log2 fold-change threshold.
#' @param significance_threshold P/FDR/Q-value threshold.
#' @return Classified volcano tibble.
prepare_candidate_volcano_data <- function(
  differential_tbl,
  effect_threshold = 1.0,
  significance_threshold = 0.05
) {
  if (effect_threshold < 0) {
    stop("Volcano effect threshold must be non-negative.", call. = FALSE)
  }
  if (significance_threshold <= 0 || significance_threshold > 1) {
    stop("Volcano significance threshold must be within (0, 1].", call. = FALSE)
  }
  required <- c("label", "effect_size", "significance_value")
  missing <- setdiff(required, names(differential_tbl))
  if (length(missing) > 0L) {
    stop(
      paste("Volcano columns are unavailable:", paste(missing, collapse = ", ")),
      call. = FALSE
    )
  }
  differential_tbl |>
    dplyr::mutate(
      effect_size = suppressWarnings(as.numeric(.data$effect_size)),
      significance_value = suppressWarnings(as.numeric(.data$significance_value))
    ) |>
    dplyr::filter(
      !is.na(.data$effect_size),
      .data$significance_value > 0,
      .data$significance_value <= 1
    ) |>
    dplyr::mutate(
      minus_log10_significance = -log10(.data$significance_value),
      direction = dplyr::case_when(
        .data$significance_value <= significance_threshold &
          .data$effect_size >= effect_threshold ~ "Higher",
        .data$significance_value <= significance_threshold &
          .data$effect_size <= -effect_threshold ~ "Lower",
        TRUE ~ "Not significant"
      )
    )
}

#' Build the volcano plot.
#'
#' @param differential_tbl Standardised differential-expression rows.
#' @param effect_threshold Absolute log2 fold-change threshold.
#' @param significance_threshold P/FDR/Q-value threshold.
#' @param significance_label Source significance column name.
#' @return ggplot volcano plot.
build_candidate_volcano_plot <- function(
  differential_tbl,
  effect_threshold = 1.0,
  significance_threshold = 0.05,
  significance_label = "adjusted P value"
) {
  prepared <- prepare_candidate_volcano_data(
    differential_tbl = differential_tbl,
    effect_threshold = effect_threshold,
    significance_threshold = significance_threshold
  )
  ggplot2::ggplot(
    data = prepared,
    mapping = ggplot2::aes(
      x = .data$effect_size,
      y = .data$minus_log10_significance,
      colour = .data$direction,
      text = paste0(
        "Label: ", .data$label,
        "<br>log2 fold change: ", signif(.data$effect_size, 4),
        "<br>", significance_label, ": ",
        signif(.data$significance_value, 4)
      )
    )
  ) +
    ggplot2::geom_point(alpha = 0.7) +
    ggplot2::geom_vline(
      xintercept = c(-effect_threshold, effect_threshold),
      linetype = "dashed"
    ) +
    ggplot2::geom_hline(
      yintercept = -log10(significance_threshold),
      linetype = "dashed"
    ) +
    ggplot2::labs(
      x = "log2 fold change",
      y = paste0("-log10(", significance_label, ")"),
      colour = "Direction"
    ) +
    ggplot2::theme_minimal()
}
