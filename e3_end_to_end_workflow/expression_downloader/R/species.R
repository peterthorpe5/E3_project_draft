#' Convert a species name to the internal species column format.
#'
#' @param species_name Species name with spaces or underscores.
#' @return Species name using underscores.
species_name_to_column <- function(species_name) {
  species_column <- species_name |>
    stringr::str_trim(side = "both") |>
    stringr::str_replace_all(pattern = "[[:space:]]+", replacement = "_")

  return(species_column)
}


#' Convert an internal species column to a scientific name.
#'
#' @param species_column Species name using underscores.
#' @return Species name using spaces.
species_column_to_scientific_name <- function(species_column) {
  scientific_name <- species_column |>
    stringr::str_replace_all(pattern = "_", replacement = " ") |>
    stringr::str_trim(side = "both")

  return(scientific_name)
}


#' Read a plain-text species file.
#'
#' Reads a one-species-per-line text file. Blank lines and comment lines starting
#' with `#` are ignored. Species may be written with underscores or spaces.
#'
#' @param species_file Path to a species text file.
#' @return A tibble with one row per species.
read_species_file <- function(species_file) {
  if (!file.exists(species_file)) {
    stop(
      stringr::str_c("Species file does not exist: ", species_file),
      call. = FALSE
    )
  }

  raw_lines <- readLines(con = species_file, warn = FALSE)

  species_values <- raw_lines |>
    stringr::str_remove(pattern = "#.*$") |>
    stringr::str_trim(side = "both")

  species_values <- species_values[species_values != ""]
  species_values <- unique(species_values)

  species_tbl <- tibble::tibble(
    species_column = species_name_to_column(species_name = species_values)
  ) |>
    dplyr::mutate(
      scientific_name = species_column_to_scientific_name(
        species_column = .data$species_column
      ),
      atlas_species_query = .data$scientific_name,
      include = TRUE,
      priority = dplyr::if_else(
        condition = .data$species_column %in% priority_plant_species(),
        true = "plant_priority",
        false = "other"
      ),
      notes = ""
    ) |>
    dplyr::distinct(.data$species_column, .keep_all = TRUE)

  return(species_tbl)
}


#' Return the default priority plant species.
#'
#' @return Character vector of priority species columns.
priority_plant_species <- function() {
  species <- c(
    "Arabidopsis_thaliana",
    "Brachypodium_distachyon",
    "Chlamydomonas_reinhardtii",
    "Glycine_max",
    "Hordeum_vulgare",
    "Medicago_truncatula",
    "Oryza_sativa",
    "Physcomitrella_patens",
    "Populus_trichocarpa",
    "Solanum_lycopersicum",
    "Solanum_tuberosum",
    "Sorghum_bicolor",
    "Triticum_aestivum",
    "Zea_mays"
  )

  return(species)
}


#' Apply species override metadata.
#'
#' Applies manual corrections such as alternative Atlas query names, priority
#' labels or include flags.
#'
#' @param species_tbl Species table from `read_species_file()`.
#' @param override_tsv Optional path to a species override TSV.
#' @return Updated species registry tibble.
apply_species_overrides <- function(species_tbl, override_tsv = NULL) {
  if (is.null(override_tsv) || !file.exists(override_tsv)) {
    return(species_tbl)
  }

  override_tbl <- readr::read_tsv(
    file = override_tsv,
    show_col_types = FALSE
  )

  updated_tbl <- species_tbl |>
    dplyr::left_join(
      y = override_tbl,
      by = "species_column",
      suffix = c("", ".override")
    ) |>
    dplyr::mutate(
      scientific_name = dplyr::coalesce(
        .data$scientific_name.override,
        .data$scientific_name
      ),
      atlas_species_query = dplyr::coalesce(
        .data$atlas_species_query.override,
        .data$atlas_species_query
      ),
      include = dplyr::coalesce(.data$include.override, .data$include),
      priority = dplyr::coalesce(.data$priority.override, .data$priority),
      notes = dplyr::coalesce(.data$notes.override, .data$notes)
    ) |>
    dplyr::select(
      .data$species_column,
      .data$scientific_name,
      .data$atlas_species_query,
      .data$include,
      .data$priority,
      .data$notes
    )

  return(updated_tbl)
}


#' Build a species registry from a species text file.
#'
#' @param species_file Path to a one-species-per-line species file.
#' @param override_tsv Optional path to a species override TSV.
#' @return A species registry tibble.
build_species_registry <- function(species_file, override_tsv = NULL) {
  species_tbl <- read_species_file(species_file = species_file)

  species_tbl <- apply_species_overrides(
    species_tbl = species_tbl,
    override_tsv = override_tsv
  )

  return(species_tbl)
}


#' Write the species registry as TSV.
#'
#' @param species_tbl Species registry tibble.
#' @param output_tsv Output TSV path.
#' @return Invisibly returns the output path.
write_species_registry <- function(species_tbl, output_tsv) {
  ensure_directory(directory_path = dirname(output_tsv))

  readr::write_tsv(
    x = species_tbl,
    file = output_tsv
  )

  return(invisible(output_tsv))
}
