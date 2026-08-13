#' Deterministic FASTA export helpers.

#' Convert a data frame of sequences into FASTA text.
#'
#' @param data Sequence-bearing data frame.
#' @param identifier_column Header identifier column.
#' @param sequence_column Raw or aligned sequence column.
#' @param description_columns Optional header-description columns.
#' @param line_width Maximum sequence characters per line.
#' @return UTF-8 FASTA text ending with a newline.
data_frame_to_fasta <- function(
  data,
  identifier_column,
  sequence_column,
  description_columns = character(),
  line_width = 80L
) {
  if (!is.data.frame(data)) {
    stop("FASTA export requires a data frame.", call. = FALSE)
  }
  columns <- c(identifier_column, sequence_column, description_columns)
  if (anyNA(columns) || any(!nzchar(columns))) {
    stop("FASTA export columns must have non-empty names.", call. = FALSE)
  }
  missing_columns <- setdiff(columns, names(data))
  if (length(missing_columns) > 0L) {
    stop(
      paste(
        "FASTA export is missing columns:",
        paste(missing_columns, collapse = ", ")
      ),
      call. = FALSE
    )
  }
  line_width <- suppressWarnings(as.integer(line_width))
  if (length(line_width) != 1L || is.na(line_width) || line_width < 1L) {
    stop("FASTA line width must be a positive integer.", call. = FALSE)
  }
  if (nrow(data) == 0L) {
    stop("FASTA export requires at least one sequence row.", call. = FALSE)
  }
  identifiers <- gsub(
    "[[:space:]]+",
    "_",
    trimws(as.character(data[[identifier_column]]))
  )
  if (anyNA(identifiers) || any(!nzchar(identifiers))) {
    stop("Every FASTA row must have an identifier.", call. = FALSE)
  }
  if (anyDuplicated(identifiers) > 0L) {
    duplicate <- identifiers[duplicated(identifiers)][[1L]]
    stop(paste0("FASTA identifier is duplicated: ", duplicate), call. = FALSE)
  }
  records <- character()
  for (row_index in seq_len(nrow(data))) {
    sequence <- toupper(gsub(
      "[[:space:]]+",
      "",
      as.character(data[[sequence_column]][[row_index]])
    ))
    if (is.na(sequence) || !nzchar(sequence)) {
      stop(
        paste0("FASTA row ", row_index, " has no sequence."),
        call. = FALSE
      )
    }
    if (grepl("[^A-Z*.?-]", sequence)) {
      stop(
        paste0(
          "FASTA row ", row_index,
          " contains unsupported sequence characters."
        ),
        call. = FALSE
      )
    }
    descriptions <- vapply(description_columns, function(column) {
      value <- data[[column]][[row_index]]
      if (is.na(value) || !nzchar(trimws(as.character(value)))) {
        return("")
      }
      paste0(
        column,
        "=",
        gsub("[[:space:]]+", "_", trimws(as.character(value)))
      )
    }, character(1L))
    descriptions <- descriptions[nzchar(descriptions)]
    header <- paste0(">", identifiers[[row_index]])
    if (length(descriptions) > 0L) {
      header <- paste(header, paste(descriptions, collapse = " "))
    }
    starts <- seq.int(1L, nchar(sequence), by = line_width)
    ends <- pmin(starts + line_width - 1L, nchar(sequence))
    records <- c(
      records,
      header,
      substring(sequence, first = starts, last = ends)
    )
  }
  paste0(paste(records, collapse = "\n"), "\n")
}

#' Export a selected pocket-review MAFFT alignment.
#'
#' @param review_config Prepared pocket-review configuration.
#' @param review_rank Selected review rank.
#' @return Alignment FASTA text.
selected_pocket_review_alignment_fasta <- function(
  review_config,
  review_rank
) {
  sequences <- review_config$sequences
  if (!"aligned_sequence" %in% names(sequences)) {
    stop(
      paste(
        "This pocket-review bundle does not contain aligned sequences.",
        "Regenerate it with the current structural-report release."
      ),
      call. = FALSE
    )
  }
  selected <- sequences[
    sequences$review_rank == as.integer(review_rank),
    ,
    drop = FALSE
  ]
  data_frame_to_fasta(
    data = selected,
    identifier_column = "fasta_identifier",
    sequence_column = "aligned_sequence",
    description_columns = c("species_column", "candidate_accession")
  )
}
