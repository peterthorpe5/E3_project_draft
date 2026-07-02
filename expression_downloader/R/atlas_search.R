#' Normalise Expression Atlas search results.
#'
#' @param result_tbl Raw result tibble from an Atlas search.
#' @param species_column Internal species column name.
#' @param atlas_species_query Species query used for Atlas.
#' @return Normalised candidate experiment tibble.
normalise_atlas_search_results <- function(
  result_tbl,
  species_column,
  atlas_species_query
) {
  if (nrow(result_tbl) == 0L) {
    return(
      tibble::tibble(
        experiment_accession = character(),
        species_column = character(),
        atlas_species_query = character(),
        search_term = character(),
        atlas_species_reported = character(),
        atlas_experiment_type = character(),
        atlas_title = character()
      )
    )
  }

  column_names <- names(result_tbl)
  lower_names <- stringr::str_to_lower(column_names)

  accession_matches <- column_names[
    stringr::str_detect(
      string = lower_names,
      pattern = "^accession$|experiment.*accession"
    )
  ]

  if (length(accession_matches) == 0L) {
    stop(
      stringr::str_c(
        "Could not identify an accession column in Atlas search results. Columns were: ",
        stringr::str_c(column_names, collapse = ", ")
      ),
      call. = FALSE
    )
  }

  accession_column <- accession_matches[[1L]]

  species_matches <- column_names[
    stringr::str_detect(string = lower_names, pattern = "^species$|organism")
  ]
  type_matches <- column_names[
    stringr::str_detect(string = lower_names, pattern = "^type$|experiment.*type")
  ]
  title_matches <- column_names[
    stringr::str_detect(string = lower_names, pattern = "^title$|^name$")
  ]

  normalised_tbl <- result_tbl |>
    dplyr::mutate(
      experiment_accession = as.character(.data[[accession_column]]),
      species_column = species_column,
      atlas_species_query = atlas_species_query,
      atlas_species_reported = if (length(species_matches) > 0L) {
        as.character(.data[[species_matches[[1L]]]])
      } else {
        NA_character_
      },
      atlas_experiment_type = if (length(type_matches) > 0L) {
        as.character(.data[[type_matches[[1L]]]])
      } else {
        NA_character_
      },
      atlas_title = if (length(title_matches) > 0L) {
        as.character(.data[[title_matches[[1L]]]])
      } else {
        NA_character_
      }
    ) |>
    dplyr::select(
      .data$experiment_accession,
      .data$species_column,
      .data$atlas_species_query,
      dplyr::any_of("search_term"),
      .data$atlas_species_reported,
      .data$atlas_experiment_type,
      .data$atlas_title,
      dplyr::everything()
    ) |>
    dplyr::distinct(.data$experiment_accession, .keep_all = TRUE)

  if (!"search_term" %in% names(normalised_tbl)) {
    normalised_tbl <- normalised_tbl |>
      dplyr::mutate(search_term = NA_character_)
  }

  return(normalised_tbl)
}


#' Query the ArrayExpress XML API for Expression Atlas experiments.
#'
#' This avoids relying on the Bioconductor ExpressionAtlas wrapper for the
#' search step, which can be noisy and difficult to diagnose on HPC systems.
#'
#' @param atlas_species_query Scientific species name to search.
#' @param search_term Search term passed to the ArrayExpress keyword field.
#' @param timeout_seconds Request timeout in seconds.
#' @return Raw experiment tibble with accession, species, type and title.
search_atlas_species_arrayexpress_api <- function(
  atlas_species_query,
  search_term,
  timeout_seconds = 60L
) {
  request <- httr2::request(
    base_url = "https://www.ebi.ac.uk/arrayexpress/xml/v2/experiments"
  ) |>
    httr2::req_url_query(
      keywords = search_term,
      gxa = "TRUE",
      species = atlas_species_query
    ) |>
    httr2::req_timeout(seconds = timeout_seconds)

  response <- tryCatch(
    expr = httr2::req_perform(req = request),
    error = function(error) {
      warning(
        stringr::str_c(
          "Expression Atlas API search failed for '",
          atlas_species_query,
          "' with term '",
          search_term,
          "': ",
          conditionMessage(error)
        ),
        call. = FALSE
      )
      return(NULL)
    }
  )

  if (is.null(response)) {
    return(
      tibble::tibble(
        Accession = character(),
        Species = character(),
        Type = character(),
        Title = character(),
        search_term = character()
      )
    )
  }

  status_code <- httr2::resp_status(resp = response)

  if (status_code >= 400L) {
    warning(
      stringr::str_c(
        "Expression Atlas API returned HTTP ",
        status_code,
        " for '",
        atlas_species_query,
        "' with term '",
        search_term,
        "'."
      ),
      call. = FALSE
    )

    return(
      tibble::tibble(
        Accession = character(),
        Species = character(),
        Type = character(),
        Title = character(),
        search_term = character()
      )
    )
  }

  xml_text <- httr2::resp_body_string(resp = response)
  xml_doc <- xml2::read_xml(x = xml_text)
  experiment_nodes <- xml2::xml_find_all(x = xml_doc, xpath = ".//experiment")

  if (length(experiment_nodes) == 0L) {
    return(
      tibble::tibble(
        Accession = character(),
        Species = character(),
        Type = character(),
        Title = character(),
        search_term = character()
      )
    )
  }

  extract_first_text <- function(node, xpath) {
    value <- xml2::xml_text(xml2::xml_find_first(x = node, xpath = xpath))
    if (length(value) == 0L || is.na(value)) {
      return(NA_character_)
    }
    return(value)
  }

  result_tbl <- tibble::tibble(
    Accession = vapply(
      X = experiment_nodes,
      FUN = extract_first_text,
      FUN.VALUE = character(length = 1L),
      xpath = "./accession"
    ),
    Species = vapply(
      X = experiment_nodes,
      FUN = extract_first_text,
      FUN.VALUE = character(length = 1L),
      xpath = "./organism"
    ),
    Type = vapply(
      X = experiment_nodes,
      FUN = extract_first_text,
      FUN.VALUE = character(length = 1L),
      xpath = "./experimenttype"
    ),
    Title = vapply(
      X = experiment_nodes,
      FUN = extract_first_text,
      FUN.VALUE = character(length = 1L),
      xpath = "./name"
    ),
    search_term = search_term
  ) |>
    dplyr::filter(!is.na(.data$Accession)) |>
    dplyr::filter(.data$Accession != "")

  return(result_tbl)
}


#' Filter candidate experiments by experiment type.
#'
#' @param experiment_tbl Normalised candidate experiment tibble.
#' @param experiment_type_filter Regular expression for experiment types to keep.
#'   Use NULL, "", or "all" to disable filtering.
#' @return Filtered candidate experiment tibble.
filter_atlas_experiment_types <- function(
  experiment_tbl,
  experiment_type_filter = "rna|sequencing"
) {
  if (nrow(experiment_tbl) == 0L) {
    return(experiment_tbl)
  }

  if (
    is.null(experiment_type_filter) ||
      length(experiment_type_filter) == 0L ||
      is.na(experiment_type_filter[[1L]]) ||
      experiment_type_filter[[1L]] == "" ||
      stringr::str_to_lower(experiment_type_filter[[1L]]) == "all"
  ) {
    return(experiment_tbl)
  }

  if (!"atlas_experiment_type" %in% names(experiment_tbl)) {
    warning(
      "No atlas_experiment_type column was available, so experiment-type filtering was skipped.",
      call. = FALSE
    )
    return(experiment_tbl)
  }

  filtered_tbl <- experiment_tbl |>
    dplyr::filter(
      stringr::str_detect(
        string = stringr::str_to_lower(dplyr::coalesce(.data$atlas_experiment_type, "")),
        pattern = stringr::str_to_lower(experiment_type_filter)
      )
    )

  return(filtered_tbl)
}


#' Search Expression Atlas for RNA-seq-like experiments for one species.
#'
#' @param atlas_species_query Scientific species name to search.
#' @param species_column Internal species column name.
#' @param search_terms Character vector of search terms.
#' @param search_backend Search backend. Currently "arrayexpress_api" is the
#'   robust default. "ExpressionAtlas" can be used as a fallback.
#' @param experiment_type_filter Regular expression for experiment types to keep.
#' @return A tibble of candidate experiment records.
search_atlas_species <- function(
  atlas_species_query,
  species_column,
  search_terms = c("RNA-seq", "RNA sequencing", "transcriptome", "baseline"),
  search_backend = "arrayexpress_api",
  experiment_type_filter = "rna|sequencing"
) {
  search_backend <- stringr::str_to_lower(search_backend)

  raw_result_tbl <- purrr::map_dfr(
    .x = search_terms,
    .f = function(search_term) {
      if (search_backend %in% c("arrayexpress_api", "arrayexpress", "api")) {
        return(
          search_atlas_species_arrayexpress_api(
            atlas_species_query = atlas_species_query,
            search_term = search_term
          )
        )
      }

      if (search_backend %in% c("expressionatlas", "bioconductor")) {
        if (!requireNamespace(package = "ExpressionAtlas", quietly = TRUE)) {
          warning(
            stringr::str_c(
              "ExpressionAtlas is not installed. Returning no search results for ",
              atlas_species_query,
              "."
            ),
            call. = FALSE
          )
          return(tibble::tibble())
        }

        result <- tryCatch(
          expr = ExpressionAtlas::searchAtlasExperiments(
            properties = search_term,
            species = atlas_species_query
          ),
          error = function(error) {
            warning(
              stringr::str_c(
                "ExpressionAtlas package search failed for ",
                atlas_species_query,
                " / ",
                search_term,
                ": ",
                conditionMessage(error)
              ),
              call. = FALSE
            )
            return(NULL)
          }
        )

        if (is.null(result)) {
          return(tibble::tibble())
        }

        return(
          tibble::as_tibble(result) |>
            dplyr::mutate(search_term = search_term)
        )
      }

      stop(
        stringr::str_c("Unknown search_backend: ", search_backend),
        call. = FALSE
      )
    }
  )

  if (nrow(raw_result_tbl) == 0L) {
    return(
      tibble::tibble(
        experiment_accession = character(),
        species_column = character(),
        atlas_species_query = character(),
        search_term = character(),
        atlas_species_reported = character(),
        atlas_experiment_type = character(),
        atlas_title = character()
      )
    )
  }

  normalised_tbl <- normalise_atlas_search_results(
    result_tbl = raw_result_tbl,
    species_column = species_column,
    atlas_species_query = atlas_species_query
  )

  filtered_tbl <- filter_atlas_experiment_types(
    experiment_tbl = normalised_tbl,
    experiment_type_filter = experiment_type_filter
  )

  message(
    stringr::str_c(
      "  Found ",
      nrow(normalised_tbl),
      " candidate experiments for ",
      species_column,
      "; kept ",
      nrow(filtered_tbl),
      " after experiment-type filter."
    )
  )

  return(filtered_tbl)
}


#' Search Expression Atlas for all included species in a registry.
#'
#' @param species_registry_tbl Species registry tibble.
#' @param search_terms Character vector of search terms.
#' @param search_backend Search backend.
#' @param experiment_type_filter Regular expression for experiment types to keep.
#' @return Candidate experiment tibble.
search_atlas_from_species_registry <- function(
  species_registry_tbl,
  search_terms = c("RNA-seq", "RNA sequencing", "transcriptome", "baseline"),
  search_backend = "arrayexpress_api",
  experiment_type_filter = "rna|sequencing"
) {
  included_species_tbl <- species_registry_tbl |>
    dplyr::filter(.data$include)

  if (nrow(included_species_tbl) == 0L) {
    return(
      tibble::tibble(
        experiment_accession = character(),
        species_column = character(),
        atlas_species_query = character(),
        search_term = character(),
        atlas_species_reported = character(),
        atlas_experiment_type = character(),
        atlas_title = character()
      )
    )
  }

  experiment_tbl <- purrr::pmap_dfr(
    .l = list(
      atlas_species_query = included_species_tbl$atlas_species_query,
      species_column = included_species_tbl$species_column
    ),
    .f = function(atlas_species_query, species_column) {
      message(
        stringr::str_c(
          "Searching Expression Atlas for ",
          species_column,
          " using query '",
          atlas_species_query,
          "'"
        )
      )

      search_atlas_species(
        atlas_species_query = atlas_species_query,
        species_column = species_column,
        search_terms = search_terms,
        search_backend = search_backend,
        experiment_type_filter = experiment_type_filter
      )
    }
  ) |>
    dplyr::distinct(
      .data$experiment_accession,
      .data$species_column,
      .keep_all = TRUE
    )

  message(
    stringr::str_c(
      "Total candidate experiments kept across all species: ",
      nrow(experiment_tbl)
    )
  )

  return(experiment_tbl)
}


#' Read a manually curated experiment TSV.
#'
#' The TSV must contain `species_column` and `experiment_accession` columns. This
#' is useful when Expression Atlas searching is unavailable or when experiments
#' have been chosen by hand.
#'
#' @param experiment_tsv Path to manually curated experiment TSV.
#' @return Candidate experiment tibble.
read_manual_experiments <- function(experiment_tsv) {
  if (is.null(experiment_tsv) || !file.exists(experiment_tsv)) {
    return(
      tibble::tibble(
        experiment_accession = character(),
        species_column = character(),
        atlas_species_query = character(),
        search_term = character(),
        atlas_species_reported = character(),
        atlas_experiment_type = character(),
        atlas_title = character()
      )
    )
  }

  experiment_tbl <- readr::read_tsv(
    file = experiment_tsv,
    show_col_types = FALSE
  )

  required_columns <- c("species_column", "experiment_accession")
  missing_columns <- setdiff(x = required_columns, y = names(experiment_tbl))

  if (length(missing_columns) > 0L) {
    stop(
      stringr::str_c(
        "Manual experiment TSV is missing required columns: ",
        stringr::str_c(missing_columns, collapse = ", ")
      ),
      call. = FALSE
    )
  }

  if (!"atlas_species_query" %in% names(experiment_tbl)) {
    experiment_tbl <- experiment_tbl |>
      dplyr::mutate(atlas_species_query = NA_character_)
  }

  if (!"search_term" %in% names(experiment_tbl)) {
    experiment_tbl <- experiment_tbl |>
      dplyr::mutate(search_term = "manual")
  }

  if (!"atlas_species_reported" %in% names(experiment_tbl)) {
    experiment_tbl <- experiment_tbl |>
      dplyr::mutate(atlas_species_reported = NA_character_)
  }

  if (!"atlas_experiment_type" %in% names(experiment_tbl)) {
    experiment_tbl <- experiment_tbl |>
      dplyr::mutate(atlas_experiment_type = NA_character_)
  }

  if (!"atlas_title" %in% names(experiment_tbl)) {
    experiment_tbl <- experiment_tbl |>
      dplyr::mutate(atlas_title = NA_character_)
  }

  return(experiment_tbl)
}
