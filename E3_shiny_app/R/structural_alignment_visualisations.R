#' Interactive three-dimensional alignment evidence visualisations.

#' Resolve semantic plotting roles to available alignment columns.
#'
#' @param available Character vector of relation columns.
#' @return Named character vector. Missing optional roles contain `NA`.
resolve_structural_alignment_columns <- function(available) {
  if (!is.character(available) || any(is.na(available))) {
    stop("Alignment columns must be a non-missing character vector.", call. = FALSE)
  }
  aliases <- list(
    tm_score = c("mean_minimum_tm_score", "minimum_tm_score"),
    pocket_overlap = c(
      "mean_pocket_overlap_fraction",
      "pocket_overlap_fraction"
    ),
    centroid_distance = c(
      "median_centroid_distance_angstrom",
      "centroid_distance_angstrom"
    ),
    status = c(
      "alignment_status",
      "three_dimensional_alignment_status",
      "position_alignment_status"
    ),
    identifier = c(
      "primary_group_id",
      "cluster_id",
      "mobile_accession",
      "reference_accession"
    )
  )
  resolved <- vapply(aliases, function(candidates) {
    matches <- candidates[candidates %in% available]
    if (length(matches) == 0L) NA_character_ else matches[[1L]]
  }, character(1))
  resolved
}

#' Return columns required for a bounded alignment visualisation query.
#'
#' @param available Character vector of relation columns.
#' @return Ordered character vector, or empty when either axis is unavailable.
structural_alignment_plot_columns <- function(available) {
  resolved <- resolve_structural_alignment_columns(available = available)
  if (any(is.na(resolved[c("tm_score", "pocket_overlap")]))) {
    return(character())
  }
  detail_columns <- c(
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "reference_accession",
    "mobile_accession",
    "alignment_tool",
    "position_alignment_status",
    "alignment_status",
    "mean_structural_residue_match_fraction",
    "mean_structural_chemical_group_conservation"
  )
  unique(c(
    unname(resolved[!is.na(resolved)]),
    detail_columns[detail_columns %in% available]
  ))
}

#' Standardise summary or pairwise structural-alignment rows for plotting.
#'
#' @param data Bounded structural-alignment data frame.
#' @return Data frame containing standardised plot columns.
prepare_structural_alignment_plot_data <- function(data) {
  if (!is.data.frame(data)) {
    stop("Alignment visualisation requires a data frame.", call. = FALSE)
  }
  resolved <- resolve_structural_alignment_columns(available = names(data))
  if (any(is.na(resolved[c("tm_score", "pocket_overlap")]))) {
    stop(
      "Alignment visualisation requires paired TM-score and pocket-overlap columns.",
      call. = FALSE
    )
  }
  prepared <- data
  prepared$plot_tm_score <- suppressWarnings(as.numeric(
    prepared[[resolved[["tm_score"]]]]
  ))
  prepared$plot_pocket_overlap <- suppressWarnings(as.numeric(
    prepared[[resolved[["pocket_overlap"]]]]
  ))
  prepared$plot_centroid_distance <- if (
    is.na(resolved[["centroid_distance"]])
  ) {
    rep(NA_real_, nrow(prepared))
  } else {
    suppressWarnings(as.numeric(prepared[[resolved[["centroid_distance"]]]]))
  }
  prepared$plot_alignment_status <- if (is.na(resolved[["status"]])) {
    rep("UNCLASSIFIED", nrow(prepared))
  } else {
    values <- as.character(prepared[[resolved[["status"]]]])
    values[is.na(values) | !nzchar(trimws(values))] <- "UNCLASSIFIED"
    values
  }
  prepared$plot_alignment_identifier <- if (is.na(resolved[["identifier"]])) {
    paste("Alignment row", seq_len(nrow(prepared)))
  } else {
    values <- as.character(prepared[[resolved[["identifier"]]]])
    values[is.na(values) | !nzchar(trimws(values))] <- "Unidentified row"
    values
  }
  prepared <- prepared[
    !is.na(prepared$plot_tm_score) &
      !is.na(prepared$plot_pocket_overlap),
    ,
    drop = FALSE
  ]
  if (nrow(prepared) == 0L) {
    stop("No paired 3D alignment values are available to plot.", call. = FALSE)
  }
  rownames(prepared) <- NULL
  prepared
}

#' Build an interactive TM-score and pocket-overlap evidence map.
#'
#' @param data Bounded structural-alignment data frame.
#' @return Plotly htmlwidget with recorded threshold reference lines.
build_structural_alignment_plot <- function(data) {
  prepared <- prepare_structural_alignment_plot_data(data = data)
  hover_text <- paste0(
    "<b>", prepared$plot_alignment_identifier, "</b>",
    "<br>TM-score: ", format(round(prepared$plot_tm_score, 3), nsmall = 3),
    "<br>Pocket overlap: ",
    format(round(prepared$plot_pocket_overlap, 3), nsmall = 3),
    "<br>Centroid distance (Å): ",
    ifelse(
      is.na(prepared$plot_centroid_distance),
      "not available",
      format(round(prepared$plot_centroid_distance, 3), nsmall = 3)
    ),
    "<br>Status: ", prepared$plot_alignment_status
  )
  plot <- plotly::plot_ly(
    data = prepared,
    x = ~plot_tm_score,
    y = ~plot_pocket_overlap,
    color = ~plot_alignment_status,
    text = hover_text,
    hoverinfo = "text",
    type = "scatter",
    mode = "markers",
    marker = list(size = 9, opacity = 0.8)
  )
  plot <- plotly::layout(
    plot,
    xaxis = list(
      title = "Minimum TM-score",
      range = c(0, 1),
      fixedrange = FALSE
    ),
    yaxis = list(
      title = "3D pocket-overlap fraction",
      range = c(0, 1),
      fixedrange = FALSE
    ),
    legend = list(title = list(text = "Alignment status")),
    shapes = list(
      list(
        type = "line",
        x0 = 0.5,
        x1 = 0.5,
        y0 = 0,
        y1 = 1,
        line = list(dash = "dash", width = 1)
      ),
      list(
        type = "line",
        x0 = 0,
        x1 = 1,
        y0 = 0.5,
        y1 = 0.5,
        line = list(dash = "dash", width = 1)
      )
    )
  )
  plotly::plotly_build(plot)
}
