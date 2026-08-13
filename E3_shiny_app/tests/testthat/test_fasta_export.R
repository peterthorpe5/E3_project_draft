testthat::test_that("FASTA export preserves alignment gaps and wraps sequences", {
  rows <- data.frame(
    fasta_identifier = c("seq one", "seq_two"),
    species = c("Species one", "Species two"),
    sequence = c("ACD-EF", "GGGGGG"),
    stringsAsFactors = FALSE
  )
  observed <- data_frame_to_fasta(
    data = rows,
    identifier_column = "fasta_identifier",
    sequence_column = "sequence",
    description_columns = "species",
    line_width = 4L
  )
  testthat::expect_identical(
    observed,
    paste0(
      ">seq_one species=Species_one\nACD-\nEF\n",
      ">seq_two species=Species_two\nGGGG\nGG\n"
    )
  )
})

testthat::test_that("FASTA export rejects unsafe or ambiguous records", {
  testthat::expect_error(
    data_frame_to_fasta(
      data = data.frame(id = c("x", "x"), seq = c("AA", "BB")),
      identifier_column = "id",
      sequence_column = "seq"
    ),
    "duplicated"
  )
  testthat::expect_error(
    data_frame_to_fasta(
      data = data.frame(id = "x", seq = "AA1"),
      identifier_column = "id",
      sequence_column = "seq"
    ),
    "unsupported"
  )
})

testthat::test_that("selected review alignment exports the recorded MAFFT rows", {
  review_config <- list(
    sequences = data.frame(
      review_rank = 1L,
      fasta_identifier = "P1",
      species_column = "Arabidopsis_thaliana",
      candidate_accession = "P1",
      aligned_sequence = "AC-DE",
      stringsAsFactors = FALSE
    )
  )
  observed <- selected_pocket_review_alignment_fasta(
    review_config = review_config,
    review_rank = 1L
  )
  testthat::expect_match(observed, ">P1", fixed = TRUE)
  testthat::expect_match(observed, "AC-DE", fixed = TRUE)
})
