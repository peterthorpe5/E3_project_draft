#' PDF export helpers for application visualisations.

#' Write a ggplot as a vector PDF and validate the result.
#'
#' @param plot ggplot object.
#' @param path Destination PDF path.
#' @param width Width in inches.
#' @param height Height in inches.
#' @return Destination path, invisibly.
write_ggplot_pdf <- function(plot, path, width = 12, height = 8) {
  if (!inherits(plot, "ggplot")) {
    stop("ggplot PDF export requires a ggplot object.", call. = FALSE)
  }
  if (!is.numeric(width) || !is.numeric(height) || width <= 0 || height <= 0) {
    stop("PDF dimensions must be positive numbers.", call. = FALSE)
  }
  ggplot2::ggsave(
    filename = path,
    plot = plot,
    device = "pdf",
    width = width,
    height = height,
    units = "in"
  )
  validate_pdf_file(path = path)
}

#' Write a Plotly widget as a vector PDF through Kaleido.
#'
#' @param plot Plotly widget.
#' @param path Destination PDF path.
#' @param width Width in pixels.
#' @param height Height in pixels.
#' @param save_function Injectable Plotly image writer for unit tests.
#' @return Destination path, invisibly.
write_plotly_pdf <- function(
  plot,
  path,
  width = 1400L,
  height = 900L,
  save_function = plotly::save_image
) {
  width <- suppressWarnings(as.integer(width))
  height <- suppressWarnings(as.integer(height))
  if (
    is.na(width) || is.na(height) || width < 200L || height < 200L ||
      width > 5000L || height > 5000L
  ) {
    stop("PDF dimensions must be between 200 and 5000 pixels.", call. = FALSE)
  }
  tryCatch(
    save_function(
      p = plot,
      file = path,
      format = "pdf",
      scale = 1,
      width = width,
      height = height
    ),
    error = function(error) {
      stop(
        paste(
          "Plot PDF export requires Plotly's Kaleido renderer:",
          conditionMessage(error)
        ),
        call. = FALSE
      )
    }
  )
  validate_pdf_file(path = path)
}

#' Validate that a renderer wrote a non-empty PDF file.
#'
#' @param path Candidate PDF path.
#' @return Path, invisibly.
validate_pdf_file <- function(path) {
  if (!file.exists(path) || isTRUE(file.info(path)$size < 5L)) {
    stop("The PDF renderer did not create a valid file.", call. = FALSE)
  }
  signature <- readBin(path, what = "raw", n = 4L)
  if (!identical(rawToChar(signature), "%PDF")) {
    stop("The PDF renderer returned an invalid PDF payload.", call. = FALSE)
  }
  invisible(path)
}
