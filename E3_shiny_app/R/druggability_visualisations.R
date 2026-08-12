#' Final-gate member druggability distribution visualisations.

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
  max_groups = 30L
) {
  if (!is.data.frame(scores) || !is.data.frame(eligible_groups)) {
    stop("Final-gate druggability inputs must be data frames.", call. = FALSE)
  }
  max_groups <- suppressWarnings(as.integer(max_groups))
  if (length(max_groups) != 1L || is.na(max_groups) || max_groups < 1L ||
      max_groups > 100L) {
    stop(
      "Maximum plotted druggability groups must be between 1 and 100.",
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
    intersect(c("primary_group_id", "primary_group_type"), names(eligible_groups))
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

#' Build horizontal final-gate druggability box plots.
#'
#' @param data Prepared member-level score rows.
#' @param threshold Inclusive selected final-gate threshold.
#' @return Built Plotly htmlwidget with a threshold reference line.
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
