#' Final-gate member druggability distribution visualisations.

ALL_FINAL_GATE_GROUPS <- "__all_final_gate_groups__"

#' Prepare ranked member-level rows for the final-gate box plot.
#'
#' @param scores Selected-pocket member scores keyed by `cluster_id`.
#' @param eligible_groups Groups passing every fixed final gate at a zero
#'   druggability threshold.
#' @param max_groups Maximum ranked groups shown.
#' @return List containing prepared data and a truncation flag.
prepare_final_gate_druggability_data <- function(
  scores,
  eligible_groups,
  max_groups = 2000L
) {
  if (!is.data.frame(scores) || !is.data.frame(eligible_groups)) {
    stop("Final-gate druggability inputs must be data frames.", call. = FALSE)
  }
  max_groups <- suppressWarnings(as.integer(max_groups))
  if (length(max_groups) != 1L || is.na(max_groups) || max_groups < 1L ||
      max_groups > 2000L) {
    stop(
      "Maximum prepared druggability groups must be between 1 and 2000.",
      call. = FALSE
    )
  }
  required_scores <- c(
    "cluster_id",
    "member_accession",
    "druggability_score"
  )
  missing_scores <- setdiff(required_scores, names(scores))
  if (length(missing_scores) > 0L) {
    stop(
      paste0(
        "Member druggability rows are missing: ",
        paste(missing_scores, collapse = ", "),
        "."
      ),
      call. = FALSE
    )
  }
  cluster_columns <- c("lead_cluster_id", "cluster_id")
  cluster_column <- cluster_columns[cluster_columns %in% names(eligible_groups)]
  if (length(cluster_column) == 0L) {
    stop("Eligible final-gate groups lack a lead cluster identifier.", call. = FALSE)
  }
  cluster_column <- cluster_column[[1L]]
  rank_columns <- c("final_evolutionary_rank", "final_rank")
  rank_column <- rank_columns[rank_columns %in% names(eligible_groups)]
  rank_column <- if (length(rank_column) == 0L) NA_character_ else rank_column[[1L]]

  metadata_columns <- unique(c(
    cluster_column,
    rank_column,
    intersect(
      c("primary_group_id", "primary_group_type", "reaches_final_gate"),
      names(eligible_groups)
    )
  ))
  metadata_columns <- metadata_columns[!is.na(metadata_columns)]
  metadata <- eligible_groups[, metadata_columns, drop = FALSE]
  metadata[[cluster_column]] <- trimws(as.character(metadata[[cluster_column]]))
  metadata <- metadata[
    !is.na(metadata[[cluster_column]]) & nzchar(metadata[[cluster_column]]),
    ,
    drop = FALSE
  ]
  metadata$plot_rank <- if (is.na(rank_column)) {
    rep(Inf, nrow(metadata))
  } else {
    suppressWarnings(as.numeric(metadata[[rank_column]]))
  }
  metadata <- metadata[
    order(metadata$plot_rank, metadata[[cluster_column]], na.last = TRUE),
    ,
    drop = FALSE
  ]
  metadata <- metadata[
    !duplicated(metadata[[cluster_column]]),
    ,
    drop = FALSE
  ]
  truncated <- nrow(metadata) > max_groups
  metadata <- utils::head(metadata, max_groups)
  names(metadata)[names(metadata) == cluster_column] <- "eligible_cluster_id"
  if (!"reaches_final_gate" %in% names(metadata)) {
    metadata$reaches_final_gate <- TRUE
  } else {
    metadata$reaches_final_gate <- !is.na(metadata$reaches_final_gate) &
      as.logical(metadata$reaches_final_gate)
  }

  prepared_scores <- scores
  prepared_scores$cluster_id <- trimws(as.character(prepared_scores$cluster_id))
  prepared_scores$druggability_score <- suppressWarnings(as.numeric(
    prepared_scores$druggability_score
  ))
  prepared_scores <- prepared_scores[
    !is.na(prepared_scores$cluster_id) & nzchar(prepared_scores$cluster_id) &
      !is.na(prepared_scores$druggability_score) &
      prepared_scores$druggability_score >= 0 &
      prepared_scores$druggability_score <= 1,
    ,
    drop = FALSE
  ]
  prepared <- dplyr::inner_join(
    metadata,
    prepared_scores,
    by = c("eligible_cluster_id" = "cluster_id")
  )
  # Retain the public member-table key as well as the selector-specific alias.
  # dplyr removes the right-hand join key when the columns have different names,
  # but downstream tables, downloads and tests use `cluster_id` as their stable
  # relation field.
  prepared$cluster_id <- prepared$eligible_cluster_id
  if (nrow(prepared) == 0L) {
    return(list(data = tibble::as_tibble(prepared), truncated = truncated))
  }
  group_ids <- if ("primary_group_id" %in% names(prepared)) {
    values <- trimws(as.character(prepared$primary_group_id))
    values[is.na(values)] <- ""
    values
  } else {
    rep("", nrow(prepared))
  }
  prepared$group_label <- ifelse(
    nzchar(group_ids),
    paste(group_ids, prepared$eligible_cluster_id, sep = " · "),
    prepared$eligible_cluster_id
  )
  prepared$member_accession <- as.character(prepared$member_accession)
  prepared$member_accession[
    is.na(prepared$member_accession) | !nzchar(prepared$member_accession)
  ] <- "Unknown member"
  if (!"species" %in% names(prepared)) {
    prepared$species <- "Unknown"
  }
  prepared$species <- as.character(prepared$species)
  prepared$species[is.na(prepared$species) | !nzchar(prepared$species)] <- "Unknown"
  list(data = tibble::as_tibble(prepared), truncated = truncated)
}

#' Build searchable choices for final-gate druggability groups.
#'
#' @param data Prepared member-level druggability rows.
#' @return Named character vector mapping labels to stable cluster keys.
final_gate_druggability_group_choices <- function(data) {
  required <- c(
    "eligible_cluster_id",
    "group_label",
    "reaches_final_gate"
  )
  if (!is.data.frame(data) || !all(required %in% names(data))) {
    stop("Druggability selector rows lack required group fields.", call. = FALSE)
  }
  if (nrow(data) == 0L) {
    stop("No scored structurally assessed groups are available.", call. = FALSE)
  }
  metadata_columns <- c(
    "eligible_cluster_id",
    "group_label",
    "reaches_final_gate"
  )
  if ("plot_rank" %in% names(data)) {
    metadata_columns <- c(metadata_columns, "plot_rank")
  }
  metadata <- data[, metadata_columns, drop = FALSE]
  metadata <- metadata[
    !duplicated(as.character(metadata$eligible_cluster_id)),
    ,
    drop = FALSE
  ]
  labels <- vapply(seq_len(nrow(metadata)), function(index) {
    rank_value <- if ("plot_rank" %in% names(metadata)) {
      suppressWarnings(as.numeric(metadata$plot_rank[[index]]))
    } else {
      NA_real_
    }
    rank_label <- if (!is.na(rank_value) && is.finite(rank_value)) {
      paste0("Rank ", format(as.integer(rank_value), big.mark = ","), " — ")
    } else {
      ""
    }
    gate_label <- if (isTRUE(metadata$reaches_final_gate[[index]])) {
      "reaches final gate"
    } else {
      "structurally assessed"
    }
    paste0(rank_label, metadata$group_label[[index]], " — ", gate_label)
  }, character(1))
  stats::setNames(
    c(as.character(metadata$eligible_cluster_id), ALL_FINAL_GATE_GROUPS),
    c(labels, "All groups reaching the last gate")
  )
}

#' Select the default final-gate druggability group.
#'
#' @param data Prepared member-level druggability rows.
#' @return Stable cluster key for the highest-ranked group reaching the gate.
default_final_gate_druggability_group <- function(data) {
  choices <- final_gate_druggability_group_choices(data = data)
  reaching <- data[
    !is.na(data$reaches_final_gate) & as.logical(data$reaches_final_gate),
    ,
    drop = FALSE
  ]
  if (nrow(reaching) > 0L) {
    return(as.character(reaching$eligible_cluster_id[[1L]]))
  }
  individual <- unname(choices[choices != ALL_FINAL_GATE_GROUPS])
  if (length(individual) == 0L) {
    stop("No individual druggability group is available.", call. = FALSE)
  }
  individual[[1L]]
}

#' Filter druggability rows to one group or the final-gate comparison.
#'
#' @param data Prepared member-level druggability rows.
#' @param selection Stable cluster key or `ALL_FINAL_GATE_GROUPS`.
#' @param max_all_groups Maximum ranked groups in the comparison view.
#' @return List containing filtered data and a truncation flag.
filter_final_gate_druggability_data <- function(
  data,
  selection,
  max_all_groups = 30L
) {
  choices <- final_gate_druggability_group_choices(data = data)
  if (length(selection) != 1L || is.na(selection)) {
    stop("Selected druggability group is unavailable.", call. = FALSE)
  }
  selection <- as.character(selection[[1L]])
  if (!selection %in% unname(choices)) {
    stop("Selected druggability group is unavailable.", call. = FALSE)
  }
  max_all_groups <- suppressWarnings(as.integer(max_all_groups))
  if (length(max_all_groups) != 1L || is.na(max_all_groups) ||
      max_all_groups < 1L || max_all_groups > 100L) {
    stop(
      "Maximum overview groups must be an integer from 1 to 100.",
      call. = FALSE
    )
  }
  if (!identical(selection, ALL_FINAL_GATE_GROUPS)) {
    selected <- data[
      as.character(data$eligible_cluster_id) == selection,
      ,
      drop = FALSE
    ]
    return(list(data = tibble::as_tibble(selected), truncated = FALSE))
  }
  reaching <- data[
    !is.na(data$reaches_final_gate) & as.logical(data$reaches_final_gate),
    ,
    drop = FALSE
  ]
  ordered_groups <- unique(as.character(reaching$eligible_cluster_id))
  truncated <- length(ordered_groups) > max_all_groups
  retained <- utils::head(ordered_groups, max_all_groups)
  reaching <- reaching[
    as.character(reaching$eligible_cluster_id) %in% retained,
    ,
    drop = FALSE
  ]
  list(data = tibble::as_tibble(reaching), truncated = truncated)
}

#' Summarise the displayed final-gate druggability distribution.
#'
#' @param data Filtered member-level score rows.
#' @param threshold Inclusive selected druggability threshold.
#' @return Named list of group, member, score and status values.
summarise_final_gate_druggability_selection <- function(data, threshold) {
  threshold <- suppressWarnings(as.numeric(threshold))
  if (length(threshold) != 1L || is.na(threshold) || threshold < 0 ||
      threshold > 1) {
    stop(
      "Druggability summary threshold must be a number from 0 to 1.",
      call. = FALSE
    )
  }
  required <- c(
    "eligible_cluster_id",
    "group_label",
    "member_accession",
    "druggability_score",
    "reaches_final_gate"
  )
  if (!is.data.frame(data) || !all(required %in% names(data))) {
    stop("Druggability summary rows lack required fields.", call. = FALSE)
  }
  if (nrow(data) == 0L) {
    stop(
      "No member-level druggability scores are available to summarise.",
      call. = FALSE
    )
  }
  scores <- suppressWarnings(as.numeric(data$druggability_score))
  scores <- scores[!is.na(scores)]
  if (length(scores) == 0L) {
    stop("No valid druggability scores are available to summarise.", call. = FALSE)
  }
  cluster_ids <- unique(as.character(data$eligible_cluster_id))
  group_count <- length(cluster_ids)
  minimum_score <- min(scores)
  reaches_final_gate <- all(
    !is.na(data$reaches_final_gate) & as.logical(data$reaches_final_gate)
  )
  druggability_pass <- minimum_score >= threshold
  if (group_count == 1L) {
    primary_group_id <- if (
      "primary_group_id" %in% names(data) &&
        !is.na(data$primary_group_id[[1L]]) &&
        nzchar(trimws(as.character(data$primary_group_id[[1L]])))
    ) {
      as.character(data$primary_group_id[[1L]])
    } else {
      "Not available"
    }
    cluster_id <- cluster_ids[[1L]]
    status <- if (reaches_final_gate && druggability_pass) {
      "PASS"
    } else if (reaches_final_gate) {
      "FAILS DRUGGABILITY"
    } else {
      "FAILS ANOTHER FIXED GATE"
    }
  } else {
    primary_group_id <- "Multiple groups"
    cluster_id <- paste(format(group_count, big.mark = ","), "lead clusters")
    status <- if (druggability_pass) "ALL PASS" else "MIXED AT THRESHOLD"
  }
  list(
    primary_group_id = primary_group_id,
    cluster_id = cluster_id,
    group_count = group_count,
    member_count = nrow(data),
    minimum_score = minimum_score,
    reaches_final_gate = reaches_final_gate,
    druggability_pass = druggability_pass,
    status = status
  )
}

#' Build horizontal final-gate druggability box plots.
#'
#' @param data Prepared member-level score rows.
#' @param threshold Inclusive selected final-gate threshold.
#' @return Plotly htmlwidget with a materialised threshold reference line.
build_final_gate_druggability_plot <- function(data, threshold) {
  threshold <- suppressWarnings(as.numeric(threshold))
  if (length(threshold) != 1L || is.na(threshold) || threshold < 0 ||
      threshold > 1) {
    stop("Druggability plot threshold must be from 0 to 1.", call. = FALSE)
  }
  required <- c("group_label", "member_accession", "druggability_score")
  if (!is.data.frame(data) || !all(required %in% names(data))) {
    stop("Druggability distribution rows lack required plot fields.", call. = FALSE)
  }
  if (nrow(data) == 0L) {
    stop("No member-level druggability scores are available to plot.", call. = FALSE)
  }
  group_order <- unique(as.character(data$group_label))
  pocket_text <- if ("pocket_number" %in% names(data)) {
    ifelse(is.na(data$pocket_number), "not available", data$pocket_number)
  } else {
    rep("not available", nrow(data))
  }
  hover_text <- paste0(
    "<b>", htmltools::htmlEscape(data$member_accession), "</b>",
    "<br>Group: ", htmltools::htmlEscape(data$group_label),
    "<br>Species: ", htmltools::htmlEscape(data$species),
    "<br>Pocket: ", htmltools::htmlEscape(pocket_text),
    "<br>Druggability: ",
    format(round(data$druggability_score, 3), nsmall = 3)
  )
  plot <- plotly::plot_ly(
    data = data,
    x = ~druggability_score,
    y = ~group_label,
    type = "box",
    orientation = "h",
    boxpoints = "all",
    jitter = 0.32,
    pointpos = 0,
    text = hover_text,
    hoverinfo = "text",
    marker = list(size = 7, opacity = 0.72)
  )
  plot <- plotly::layout(
    plot,
    xaxis = list(
      title = "Selected-pocket druggability score",
      range = c(0, 1)
    ),
    yaxis = list(
      title = "Lead cluster / evolutionary group",
      categoryorder = "array",
      categoryarray = rev(group_order)
    ),
    showlegend = FALSE,
    margin = list(l = 20, r = 20, t = 45, b = 20),
    shapes = list(list(
      type = "line",
      x0 = threshold,
      x1 = threshold,
      y0 = 0,
      y1 = 1,
      yref = "paper",
      line = list(dash = "dash", width = 1.5)
    )),
    annotations = list(list(
      x = threshold,
      y = 1,
      yref = "paper",
      text = paste0("Selected threshold = ", formatC(
        threshold,
        format = "f",
        digits = 2L
      )),
      showarrow = FALSE,
      xanchor = "left",
      yanchor = "bottom"
    ))
  )
  plotly::plotly_build(plot)
}
