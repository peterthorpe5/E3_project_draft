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
  methodology_paragraph <- function(...) {
    shiny::p(paste(...))
  }
  methodology_bullets <- function(items) {
    shiny::tags$ul(lapply(items, shiny::tags$li))
  }
  methodology_section <- function(number, title, formula, ...) {
    shiny::div(
      class = "ranking-methodology-section",
      shiny::h4(paste0(number, ". ", title)),
      shiny::div(
        class = "ranking-formula bg-light border rounded p-2 mb-3",
        shiny::tags$code(formula)
      ),
      ...
    )
  }
  effective_weight_row <- function(component, contribution) {
    shiny::tags$tr(
      shiny::tags$td(component),
      shiny::tags$td(contribution)
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
    methodology_paragraph(
      "The authoritative candidate list is a deterministic prioritisation of",
      "the computational evidence collected by the workflow. It is not a",
      "predicted probability that a protein is an E3 ubiquitin ligase, a",
      "probability that a protein contains a genuinely ligandable pocket, or",
      "a prediction that a PROTAC directed against that protein will work",
      "experimentally."
    ),
    methodology_paragraph(
      "Its purpose is narrower and more transparent: to place candidates with",
      "the strongest combined discovery, evolutionary, domain, expression,",
      "pocket and structural evidence near the top, while retaining the",
      "individual evidence components from which that ordering was derived."
    ),
    shiny::h4("Evidence types kept separate"),
    methodology_bullets(c(
      paste(
        "Hard grant-aligned gates record whether a candidate satisfies a",
        "mandatory requirement."
      ),
      paste(
        "Continuous evidence scores distinguish stronger and weaker evidence",
        "among otherwise comparable candidates."
      ),
      paste(
        "Evidence-availability and completeness fields show whether each",
        "component could actually be assessed."
      )
    )),
    methodology_paragraph(
      "A large continuous score cannot compensate for failure of a mandatory",
      "gate. For example, unusually strong expression or orthology evidence",
      "cannot repair failure of an all-members druggability rule. Unavailable",
      "evidence is not silently treated as evidence of failure or success:",
      "missingness, assessment status and gate outcome remain explicit in the",
      "authoritative results."
    ),
    methodology_paragraph(
      "Unless otherwise stated, component scores range from zero to one.",
      "Values nearer one indicate stronger support and values nearer zero",
      "indicate weaker support. A neutral value of 0.5 may be used when a",
      "component has no assessable denominator, but this does not mean that",
      "the underlying biological criterion passed. The equations are",
      "reproducible evidence summaries, not calibrated biological probabilities."
    ),
    methodology_section(
      1,
      "Discovery score",
        "D = (f_reviewed + f_ubiquitin_GO + (1 - f_exclusion)) / 3",
      methodology_paragraph(
        "For the lead DeepClust cluster, f_reviewed is the fraction of relevant",
        "seed proteins derived from reviewed records; f_ubiquitin_GO is the",
        "fraction with ubiquitin-related Gene Ontology evidence; and",
        "f_exclusion is the fraction carrying an exclusion flag."
      ),
      methodology_paragraph(
        "The term 1 - f_exclusion converts the exclusion fraction into positive",
        "support. A cluster with no exclusion-flagged seeds receives one for",
        "this component, whereas a cluster in which every relevant seed is",
        "exclusion-flagged receives zero. The three terms contribute equally."
      ),
      methodology_paragraph(
        "The score therefore rewards support from reviewed records, relevant",
        "functional annotation and absence of evidence that the cluster belongs",
        "to an excluded or unsuitable category. It does not establish that every",
        "cluster member is an E3 ligase. Where several sequence clusters mapped",
        "to one evolutionary group, the deterministically selected lead cluster",
        "represented discovery evidence in the consolidated ranking."
      )
    ),
    methodology_section(
      2,
      "Orthology score",
        "O = f_target x (0.8 + 0.2 x f_mandatory)",
      methodology_paragraph(
        "f_target is the fraction of all target species represented in the",
        "evolutionary group, and f_mandatory is the fraction of the six mandatory",
        "crop species represented. Broad target-species representation supplies",
        "most of the score; the mandatory-species term modifies it by a factor",
        "between 0.8 and 1.0."
      ),
      methodology_bullets(c(
        "All target species and all mandatory species represented gives O = 1.",
        paste(
          "All target species represented but no mandatory-species contribution",
          "limits O to 0.8."
        ),
        paste(
          "Only half of the target species represented limits O to 0.5, even",
          "when all mandatory species are present."
        )
      )),
      methodology_paragraph(
        "This prioritises broadly conserved evolutionary groups while retaining",
        "a smaller adjustment for grant-critical crop species. It does not imply",
        "identical biochemical function or the same ligand-binding cavity in all",
        "orthologues. Mandatory-species representation remains an explicit field",
        "and gate, so a strong score cannot conceal failure of that requirement."
      )
    ),
    methodology_section(
      3,
      "Domain and expression scores",
        "A = n_domain_supported / n_domain_assessed; E = n_expression_supported / n_expression_assessed",
      shiny::h5("Domain score"),
      methodology_paragraph(
        "The numerator for A counts domain-assessed species containing at least",
        "one domain from the project's catalogue of E3-associated domains. The",
        "denominator contains only species for which domain evidence was",
        "assessable. A = 1 means that every assessed species supported a",
        "catalogued domain; A = 0.5 means half did; and A = 0 means none did."
      ),
      methodology_paragraph(
        "This is a cross-species consistency measure, not a single representative",
        "protein check. Failure to detect a catalogued domain is not necessarily",
        "proof of absent E3 function, especially for divergent, incomplete or",
        "poorly annotated proteins. Assessed counts, availability and gate status",
        "therefore remain separate."
      ),
      shiny::h5("Expression score"),
      methodology_paragraph(
        "E is restricted to species whose expression evidence could be mapped",
        "uniquely to the candidate. This prevents ambiguous assignments from",
        "being counted as if they belonged confidently to one protein or group.",
        "A high value means that broad expression support was consistent across",
        "species with uniquely mapped, assessable evidence. It does not mean that",
        "every group member had expression data or that expression was equally",
        "strong in every tissue, condition or developmental stage."
      ),
      shiny::h5("Unavailable assessed denominators"),
      methodology_paragraph(
        "When no valid assessed denominator was available for domain or expression",
        "evidence, the integrated calculation used the neutral value 0.5. This",
        "avoids awarding the maximum value for missing evidence while also avoiding",
        "treating the absence of an assessable dataset as direct biological",
        "evidence against a candidate."
      ),
      methodology_paragraph(
        "The neutral value does not erase missingness. The workflow retains the",
        "assessed count, eligible denominator, availability state, mapping status,",
        "gate outcome and overall evidence completeness. A genuine intermediate",
        "score can therefore be distinguished from a neutral unavailable value,",
        "and completeness remains available as a deterministic tie-break."
      )
    ),
    methodology_section(
      4,
      "Pre-structure score",
        "P = 0.10D + 0.35O + 0.20A + 0.35E",
      methodology_bullets(c(
        "10% discovery evidence: confidence in the original cluster signal.",
        "35% orthology evidence: breadth across the target-species panel.",
        "20% domain evidence: consistency of E3-associated domain support.",
        "35% expression evidence: breadth of uniquely mapped expression support."
      )),
      methodology_paragraph(
        "Orthology and expression receive the largest weights because the",
        "grant-aligned objective required candidates that were both broadly",
        "represented and supported by expression. Domain evidence supplies a",
        "smaller functional contribution. Discovery has the lowest weight because",
        "it describes how the candidate entered the analysis and should not",
        "dominate later evolutionary and biological evidence."
      ),
      methodology_paragraph(
        "P records evidence available before ligandability, pocket conservation",
        "and 3D analysis. It is a ranking component, not an independent pass/fail",
        "decision; the corresponding hard gates remain separate."
      )
    ),
    methodology_section(
      5,
      "Ligandability score",
        "L = (d_min + p_pLDDT + m_map + p_agree) / 4",
      methodology_paragraph(
        "The four equally weighted terms are minimum selected-pocket druggability",
        "across assessed members, mean normalised pocket-confidence support, an",
        "all-members pocket-mapping indicator, and the fraction supported by both",
        "recorded pocket-ranking signals."
      ),
      shiny::h5("Minimum druggability"),
      methodology_paragraph(
        "Using the minimum rather than the mean or maximum makes d_min",
        "deliberately conservative. It prevents a favourable average from hiding",
        "a weak member and asks whether druggability is maintained across the",
        "group. This complements, but does not replace, the hard all-members",
        "druggability rule; failure of that rule cannot be repaired by other terms."
      ),
      shiny::h5("Pocket confidence and all-members mapping"),
      methodology_paragraph(
        "p_pLDDT summarises confidence in the modelled regions contributing to",
        "the pockets. It is local structural confidence, not experimental proof",
        "of a cavity or ligand binding. m_map is one only when every assessed",
        "member passes pocket mapping and zero otherwise. A single mapping failure",
        "removes this component but does not set all of L to zero; any mandatory",
        "mapping gate is applied separately."
      ),
      shiny::h5("Agreement between pocket-ranking signals"),
      methodology_paragraph(
        "p_agree is the fraction for which the selected FPocket pocket was also",
        "supported by P2Rank rescoring. P2Rank 2.5.1 used fpocket-rescore with the",
        "rescore_2024 model. It did not define an independent cavity set; it",
        "rescored and reordered the FPocket pockets. Agreement therefore describes",
        "the original FPocket assessment and a machine-learning-based re-ranking",
        "of those same cavities, not two independent pocket-discovery experiments."
      ),
      methodology_paragraph(
        "L summarises whether the selected cavity is consistently druggable,",
        "structurally credible, successfully mapped and supported by both recorded",
        "ranking signals. It remains computational evidence, not proof that a",
        "suitable chemical ligand exists."
      )
    ),
    methodology_section(
      6,
      "Pocket-conservation score",
        "C = 0.30f_component + 0.25o_region + 0.20c_chemical + 0.15d_min + 0.10p_pLDDT",
      shiny::h5("Conserved-component coverage (30%)"),
      methodology_paragraph(
        "f_component records how completely the relevant conserved pocket",
        "component is represented across assessed members. It rewards a broadly",
        "conserved, consistently traceable component rather than a signal found",
        "in only a small subset."
      ),
      shiny::h5("Aligned pocket-region overlap (25%)"),
      methodology_paragraph(
        "o_region measures overlap of mapped pocket regions after sequence",
        "alignment. It asks whether residues associated with the selected reference",
        "pocket correspond to the same aligned sequence region in other members.",
        "It is more focused than whole-protein similarity, but does not prove an",
        "equivalent three-dimensional arrangement."
      ),
      shiny::h5("Biochemical-class conservation (20%)"),
      methodology_paragraph(
        "c_chemical asks whether the biochemical character of pocket-lining",
        "residues is conserved, allowing conservative substitutions to retain",
        "support. It is a simplified chemical similarity measure and does not",
        "model every effect of side-chain geometry, protonation, solvent exposure",
        "or conformational change."
      ),
      shiny::h5("Druggability and confidence (25% combined)"),
      methodology_paragraph(
        "Minimum druggability contributes 15% and mean pocket pLDDT contributes",
        "10%. Including them prevents a conserved sequence region associated with",
        "a weak or poorly predicted cavity from receiving an inappropriately high",
        "score. C is not experimental binding evidence or proof that every member",
        "contains an equivalent 3D cavity."
      )
    ),
    methodology_section(
      7,
      "Structural score and treatment of three-dimensional evidence",
        "S_base = 0.55L + 0.45C; S = (1 - w_3D)S_base + w_3D T",
      methodology_paragraph(
        "Ligandability contributes 55% to S_base and pocket conservation 45%.",
        "The slight preference for L reflects the importance of a consistently",
        "usable predicted cavity, while C records conservation of its associated",
        "region."
      ),
      shiny::div(
        class = "ranking-formula bg-light border rounded p-2 mb-3",
        shiny::tags$code(
          "T = 0.40TM_min + 0.40o_3D + 0.20(1 - min(d_centroid / d_max, 1))"
        )
      ),
      methodology_paragraph(
        "TM_min is conservative minimum structural-alignment support; o_3D is",
        "measured 3D pocket overlap; d_centroid is the distance between pocket",
        "centroids; and d_max is the configured distance at which the centroid",
        "contribution reaches zero. The bounded centroid term is one for coincident",
        "centroids, falls as distance increases and is zero at or beyond d_max."
      ),
      shiny::div(
        class = "alert alert-info",
        shiny::strong("Recorded production setting: "),
        "w_3D = 0, and therefore S = S_base."
      ),
      methodology_paragraph(
        "The 3D evidence was calculated and retained, but it was not silently",
        "inserted into the continuous structural score after the production",
        "weighting was defined. It remained explicit through assessment status,",
        "same-position support, strict pocket-structure conservation, aligner",
        "agreement, alternative-pocket sensitivity evidence and eligibility or",
        "support gates. It could therefore affect interpretation, eligibility and",
        "gate tier while making no direct numerical contribution to S."
      ),
      methodology_paragraph(
        "Alternative-pocket rescue remained distinct from the strict rank-one",
        "result. A lower-ranked pocket that aligned well was retained as sensitivity",
        "evidence, but it did not rewrite the selected rank-one pocket or",
        "retrospectively turn that pocket into a strict pass."
      )
    ),
    methodology_section(
      8,
      "Final integrated score",
        "F = 0.60P + 0.40S",
      methodology_paragraph(
        "Pre-structure evidence contributes 60%, and ligandability plus pocket",
        "conservation contributes 40%. Because w_3D = 0 in the recorded profile,",
        "the formula expands to:"
      ),
      shiny::div(
        class = "ranking-formula bg-light border rounded p-2 mb-3",
        shiny::tags$code(
          "F = 0.06D + 0.21O + 0.12A + 0.21E + 0.22L + 0.18C"
        )
      ),
      shiny::tags$table(
        class = "table table-sm table-striped",
        shiny::tags$thead(
          shiny::tags$tr(
            shiny::tags$th("High-level evidence component"),
            shiny::tags$th("Effective contribution to F")
          )
        ),
        shiny::tags$tbody(
          effective_weight_row("Discovery", "6%"),
          effective_weight_row("Orthology", "21%"),
          effective_weight_row("Domain support", "12%"),
          effective_weight_row("Expression", "21%"),
          effective_weight_row("Ligandability", "22%"),
          effective_weight_row("Pocket conservation", "18%"),
          effective_weight_row(
            "Direct 3D score contribution",
            "0% in the recorded production profile"
          )
        )
      ),
      methodology_paragraph(
        "No single continuous component accounts for most of the score. The",
        "ranking favours evidence across several classes rather than one exceptional",
        "property. F remains a ranking score, not a probability: F = 0.80 does not",
        "mean an 80% probability of E3 function or successful PROTAC development.",
        "F also cannot override the hard gates; it orders candidates within their",
        "recorded eligibility tier."
      )
    ),
    methodology_section(
      9,
      "Ordering, tie-breaks and evolutionary-group consolidation",
        "gate tier (descending), F (descending), completeness (descending), stable identifier",
      shiny::tags$ol(
        shiny::tags$li(
          shiny::strong("Recorded base-gate pass tier. "),
          paste(
            "Candidates satisfying grant-aligned requirements are considered",
            "before those in a lower tier. A lower-tier candidate cannot move",
            "above a higher-tier candidate merely because F is larger."
          )
        ),
        shiny::tags$li(
          shiny::strong("Final score. "),
          "Within the same gate tier, candidates are ordered by descending F."
        ),
        shiny::tags$li(
          shiny::strong("Evidence completeness. "),
          paste(
            "If tier and score are tied, the more completely assessed candidate",
            "is placed first. This prevents extensive neutral missing-data",
            "substitutions from being treated like complete observations."
          )
        ),
        shiny::tags$li(
          shiny::strong("Stable cluster identifier. "),
          paste(
            "If all preceding values are tied, this supplies a reproducible final",
            "cluster-level tie-break with no biological preference."
          )
        )
      ),
      methodology_paragraph(
        "Multiple DeepClust clusters can belong to the same primary OrthoFinder",
        "group. Listing them independently would give some evolutionary groups",
        "several opportunities to occupy high ranks. These rows were consolidated,",
        "and the best deterministically ranked DeepClust row became the lead",
        "cluster representing that evolutionary group."
      ),
      methodology_paragraph(
        "Consolidated groups were ranked by the recorded final rank of the lead",
        "cluster, followed where necessary by pre-structure group rank and the",
        "stable evolutionary-group key. The stable key provides reproducibility",
        "rather than biological weighting."
      )
    ),
    shiny::h4("How to interpret the resulting rank"),
    methodology_paragraph(
      "A highly ranked evolutionary group occupies the strongest applicable gate",
      "tier, has strong integrated discovery, orthology, domain, expression,",
      "ligandability and pocket-conservation evidence, has comparatively complete",
      "supporting data, and remains highly placed after related DeepClust clusters",
      "are consolidated."
    ),
    methodology_paragraph(
      "A high rank does not establish that every member is an experimentally",
      "confirmed E3 ligase; that every species contains an identical pocket; that",
      "the predicted cavity will bind a sufficiently potent and selective ligand;",
      "that the same ligand will bind every member; that ternary-complex formation",
      "will be favourable; that target degradation will occur; or that a resulting",
      "PROTAC will be effective in plants. Those questions require further",
      "structural, chemical and experimental work."
    ),
    methodology_paragraph(
      "The ranking is therefore a transparent and reproducible way to decide which",
      "evolutionary groups warrant the next stage of investigation. Its strength",
      "is not that it turns heterogeneous evidence into biological certainty. Its",
      "strength is that every component, gate, missing-data decision, weight and",
      "tie-break is explicit and can be reproduced, inspected and challenged."
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

#' Focused sensitivity controls for the final all-members druggability gate.
#'
#' @param ns Shiny namespace function.
#' @return Shiny card containing the slider, counts, tables and downloads.
final_druggability_sensitivity_ui <- function(ns) {
  recorded <- RECORDED_MINIMUM_DRUGGABILITY_SCORE
  bslib::card(
    class = "final-druggability-sensitivity-card",
    bslib::card_header(
      "Sensitivity analysis: final all-members druggability gate"
    ),
    shiny::div(
      class = "alert alert-warning",
      paste(
        "This control does not alter the authoritative recorded result. It",
        "changes only the final minimum-member druggability threshold in",
        "memory; every other recorded pre-structure and structural gate",
        "remains fixed."
      )
    ),
    shiny::p(
      paste(
        "The rule is inclusive: a group passes this gate when its minimum",
        "selected-pocket druggability score is greater than or equal to the",
        "selected value. The recorded production threshold is 0.50."
      )
    ),
    bslib::layout_columns(
      shiny::sliderInput(
        ns("final_druggability_threshold"),
        "Minimum member druggability required for every assessed member",
        min = 0,
        max = 1,
        value = recorded,
        step = 0.01
      ),
      shiny::div(
        class = "pt-4",
        shiny::actionButton(
          ns("final_druggability_reset"),
          "Reset to recorded 0.50",
          class = "btn-primary"
        )
      ),
      col_widths = c(8, 4)
    ),
    shiny::p(
      class = "small text-muted",
      paste(
        "Lower values are more permissive and higher values are more",
        "stringent. Equality passes because the recorded rule uses ≥."
      )
    ),
    bslib::layout_columns(
      bslib::value_box(
        "Recorded passes at 0.50",
        shiny::textOutput(ns("final_druggability_recorded_passes"))
      ),
      bslib::value_box(
        "Sensitivity passes",
        shiny::textOutput(ns("final_druggability_selected_passes"))
      ),
      bslib::value_box(
        "Difference from recorded",
        shiny::textOutput(ns("final_druggability_difference"))
      ),
      bslib::value_box(
        "Groups changing pass status",
        shiny::textOutput(ns("final_druggability_changed_count"))
      )
    ),
    shiny::uiOutput(ns("final_druggability_notice")),
    shiny::h5("Member druggability distributions by group"),
    shiny::selectizeInput(
      ns("final_druggability_group"),
      "Evolutionary group to display",
      choices = character(),
      selected = NULL,
      options = list(
        placeholder = paste(
          "Search by rank, evolutionary-group identifier or lead cluster"
        ),
        maxOptions = 2500
      )
    ),
    shiny::p(
      class = "small text-muted",
      paste(
        "Individual choices include every structurally assessed group with",
        "member-level selected-pocket scores. The comparison option displays",
        "groups reaching the final druggability gate."
      )
    ),
    shiny::uiOutput(ns("final_druggability_group_summary")),
    shiny::uiOutput(ns("final_druggability_plot_notice")),
    shinycssloaders::withSpinner(
      plotly::plotlyOutput(ns("final_druggability_boxplot"), height = "650px")
    ),
    shiny::downloadButton(
      ns("download_final_druggability_boxplot_pdf"),
      "Download druggability box plot as PDF"
    ),
    shiny::h5("Sensitivity candidate list"),
    tabular_download_buttons(
      ns = ns,
      tsv_id = "final_druggability_download_tsv",
      excel_id = "final_druggability_download_excel",
      tsv_label = "Download sensitivity candidate list as TSV",
      excel_label = "Download sensitivity candidate list as Excel"
    ),
    shinycssloaders::withSpinner(
      DT::DTOutput(ns("final_druggability_result_table"))
    ),
    shiny::h5("Groups entering or leaving relative to recorded 0.50"),
    shinycssloaders::withSpinner(
      DT::DTOutput(ns("final_druggability_changes_table"))
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
    if (identical(section, "expression")) {
      shiny::div(
        class = "expression-visual-links",
        shiny::h4("Expression visualisations"),
        shiny::p(
          class = "small text-muted",
          paste(
            "Open the linked heatmap or volcano-eligibility view without",
            "searching through the main navigation. The volcano view remains",
            "unavailable unless a real differential-expression relation contains",
            "both an effect size and a P/FDR/Q value."
          )
        ),
        shiny::actionButton(
          ns("open_expression_heatmap"),
          "Open expression heatmap"
        ),
        shiny::actionButton(
          ns("open_expression_volcano"),
          "Open volcano eligibility"
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
    if (identical(section, "structural_alignment")) {
      shiny::tagList(
        shiny::h4("Interactive 3D alignment evidence map"),
        shiny::p(
          class = "small text-muted",
          paste(
            "Hover, zoom and pan across minimum TM-score and 3D pocket overlap.",
            "Dashed lines show the recorded 0.50 thresholds. Same-position",
            "support also requires a pocket-centroid distance of at most 8 Å.",
            "Rotatable coordinate models remain in 3D structures & pockets."
          )
        ),
        shiny::uiOutput(ns("alignment_plot_notice")),
        shinycssloaders::withSpinner(
          plotly::plotlyOutput(ns("alignment_plot"), height = "680px")
        ),
        shiny::downloadButton(
          ns("download_alignment_plot_pdf"),
          "Download alignment graph as PDF"
        )
      )
    },
    shinycssloaders::withSpinner(DT::DTOutput(ns("result_table"))),
    if (identical(section, "final_recommendations")) {
      final_druggability_sensitivity_ui(ns)
    },
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
    if (identical(section, "expression")) {
      open_expression_visual <- function(selected) {
        root_session <- session$rootScope()
        bslib::nav_select(
          id = "main_navigation",
          selected = "Visual explorer",
          session = root_session
        )
        bslib::nav_select(
          id = "candidate_visualisations-visual_tabs",
          selected = selected,
          session = root_session
        )
      }
      shiny::observeEvent(input$open_expression_heatmap, {
        open_expression_visual(selected = "Expression heatmap")
      })
      shiny::observeEvent(input$open_expression_volcano, {
        open_expression_visual(selected = "Volcano eligibility")
      })
    }
    if (identical(section, "structural_alignment")) {
      alignment_plot_data <- shiny::reactive({
        columns <- structural_alignment_plot_columns(available_columns())
        if (
          length(columns) == 0L ||
            is.null(input$relation) ||
            input$relation %in% c(
              "Loading...",
              "Result source not configured",
              "No recognised result table"
            )
        ) {
          return(tibble::tibble())
        }
        row_limit <- min(
          max(1L, as.integer(input$max_rows %||% 500L)),
          as.integer(max_rows)
        )
        tryCatch(
          collect_selected_result(
            resource_source = resource_source,
            relation = input$relation,
            selected_columns = columns,
            max_rows = row_limit
          ),
          error = function(error) {
            shiny::showNotification(
              paste("Could not load alignment plot rows:", conditionMessage(error)),
              type = "error",
              duration = NULL
            )
            tibble::tibble()
          }
        )
      })
      output$alignment_plot_notice <- shiny::renderUI({
        if (nrow(alignment_plot_data()) == 0L) {
          return(shiny::div(
            class = "alert alert-info",
            paste(
              "The selected relation has no paired TM-score and pocket-overlap",
              "values. Choose structural_alignment_summary or a compatible",
              "pairwise alignment relation."
            )
          ))
        }
        shiny::p(
          class = "small text-muted",
          paste(
            format(nrow(alignment_plot_data()), big.mark = ","),
            "alignment rows are plotted."
          )
        )
      })
      alignment_plot <- shiny::reactive({
        shiny::req(nrow(alignment_plot_data()) > 0L)
        build_structural_alignment_plot(data = alignment_plot_data())
      })
      output$alignment_plot <- plotly::renderPlotly({
        alignment_plot()
      })
      output$download_alignment_plot_pdf <- shiny::downloadHandler(
        filename = function() "structural_alignment_evidence_map.pdf",
        content = function(path) {
          write_plotly_pdf(plot = alignment_plot(), path = path)
        }
      )
    }
    if (identical(section, "final_recommendations")) {
      defaults <- recorded_ranking_weights()
      shiny::observeEvent(input$final_druggability_reset, {
        shiny::updateSliderInput(
          session,
          "final_druggability_threshold",
          value = RECORDED_MINIMUM_DRUGGABILITY_SCORE
        )
      })

      final_druggability_context <- shiny::reactive({
        if (!resource_source_available(resource_source)) {
          return(list(
            relation = "",
            columns = character(),
            error = "No E3 result source is configured."
          ))
        }
        relations <- tryCatch(
          collect_resource_view_names(resource_source),
          error = function(error) character()
        )
        relation <- select_threshold_relation(relations)
        if (!nzchar(relation)) {
          return(list(
            relation = "",
            columns = character(),
            error = paste(
              "No evolutionary-group relation is available for the focused",
              "final-gate sensitivity analysis."
            )
          ))
        }
        columns <- tryCatch(
          as.character(
            collect_resource_columns(resource_source, relation)$column_name
          ),
          error = function(error) character()
        )
        missing <- final_druggability_source_missing_columns(columns)
        if (length(missing) > 0L) {
          return(list(
            relation = relation,
            columns = columns,
            error = paste0(
              relation,
              " does not retain every field required to recalculate the ",
              "complete final gate intersection. Missing: ",
              paste(missing, collapse = ", "),
              "."
            )
          ))
        }
        list(relation = relation, columns = columns, error = "")
      })

      final_druggability_results <- shiny::reactive({
        context <- final_druggability_context()
        if (nzchar(context$error)) {
          return(list(
            error = context$error,
            relation = context$relation,
            threshold = RECORDED_MINIMUM_DRUGGABILITY_SCORE,
            selected = tibble::tibble(),
            changes = tibble::tibble(),
            selected_passes = NA_integer_,
            recorded_passes = NA_integer_
          ))
        }
        selected_threshold <- suppressWarnings(as.numeric(
          input$final_druggability_threshold %||%
            RECORDED_MINIMUM_DRUGGABILITY_SCORE
        ))
        row_limit <- min(max(1L, as.integer(max_rows)), 10000L)
        tryCatch({
          selected_settings <- final_druggability_settings(
            minimum_druggability_score = selected_threshold
          )
          recorded_settings <- final_druggability_settings(
            minimum_druggability_score =
              RECORDED_MINIMUM_DRUGGABILITY_SCORE
          )
          selected <- collect_threshold_results(
            resource_source = resource_source,
            relation = context$relation,
            available = context$columns,
            settings = selected_settings,
            max_rows = row_limit
          )
          selected_summary <- collect_threshold_summary(
            resource_source = resource_source,
            relation = context$relation,
            available = context$columns,
            settings = selected_settings
          )
          if (
            isTRUE(all.equal(
              selected_threshold,
              RECORDED_MINIMUM_DRUGGABILITY_SCORE
            ))
          ) {
            recorded <- selected
            recorded_summary <- selected_summary
          } else {
            recorded <- collect_threshold_results(
              resource_source = resource_source,
              relation = context$relation,
              available = context$columns,
              settings = recorded_settings,
              max_rows = row_limit
            )
            recorded_summary <- collect_threshold_summary(
              resource_source = resource_source,
              relation = context$relation,
              available = context$columns,
              settings = recorded_settings
            )
          }
          comparison <- compare_final_druggability_passes(
            recorded = recorded,
            selected = selected
          )
          list(
            error = "",
            relation = context$relation,
            threshold = selected_threshold,
            selected = comparison$selected,
            changes = comparison$changes,
            selected_passes = as.integer(selected_summary$pass_count[[1L]]),
            recorded_passes = as.integer(recorded_summary$pass_count[[1L]])
          )
        }, error = function(error) {
          list(
            error = conditionMessage(error),
            relation = context$relation,
            threshold = selected_threshold,
            selected = tibble::tibble(),
            changes = tibble::tibble(),
            selected_passes = NA_integer_,
            recorded_passes = NA_integer_
          )
        })
      })

      final_druggability_plot_data <- shiny::reactive({
        result <- final_druggability_results()
        context <- final_druggability_context()
        empty <- list(
          error = result$error,
          relation = "",
          data = tibble::tibble(),
          truncated = FALSE,
          threshold = result$threshold
        )
        if (nzchar(result$error) || nzchar(context$error)) {
          return(empty)
        }
        row_limit <- min(max(1L, as.integer(max_rows)), 10000L)
        tryCatch({
          assessed <- collect_threshold_results(
            resource_source = resource_source,
            relation = context$relation,
            available = context$columns,
            settings = final_druggability_settings(
              minimum_druggability_score = 0,
              result_scope = "all"
            ),
            max_rows = row_limit
          )
          eligible <- collect_threshold_results(
            resource_source = resource_source,
            relation = context$relation,
            available = context$columns,
            settings = final_druggability_settings(
              minimum_druggability_score = 0
            ),
            max_rows = row_limit
          )
          cluster_columns <- c("lead_cluster_id", "cluster_id")
          cluster_column <- cluster_columns[
            cluster_columns %in% names(eligible)
          ]
          if (length(cluster_column) == 0L) {
            stop(
              "Eligible groups lack a lead cluster identifier.",
              call. = FALSE
            )
          }
          cluster_column <- cluster_column[[1L]]
          assessed_cluster_column <- cluster_columns[
            cluster_columns %in% names(assessed)
          ]
          if (length(assessed_cluster_column) == 0L) {
            stop(
              "Structurally assessed groups lack a lead cluster identifier.",
              call. = FALSE
            )
          }
          assessed_cluster_column <- assessed_cluster_column[[1L]]
          eligible_cluster_ids <- trimws(as.character(
            eligible[[cluster_column]]
          ))
          eligible_cluster_ids <- eligible_cluster_ids[
            !is.na(eligible_cluster_ids) & nzchar(eligible_cluster_ids)
          ]
          score_groups <- assessed
          score_groups$reaches_final_gate <- trimws(as.character(
            score_groups[[assessed_cluster_column]]
          )) %in% eligible_cluster_ids
          rank_columns <- c("final_evolutionary_rank", "final_rank")
          rank_column <- rank_columns[rank_columns %in% names(score_groups)]
          if (length(rank_column) > 0L) {
            plot_rank <- suppressWarnings(as.numeric(
              score_groups[[rank_column[[1L]]]]
            ))
            score_groups <- score_groups[
              order(
                plot_rank,
                score_groups[[assessed_cluster_column]],
                na.last = TRUE
              ),
              ,
              drop = FALSE
            ]
          }
          score_groups <- score_groups[
            !duplicated(score_groups[[assessed_cluster_column]]),
            ,
            drop = FALSE
          ]
          member_scores <- collect_member_druggability_scores(
            resource_source = resource_source,
            cluster_ids = score_groups[[assessed_cluster_column]],
            max_rows = 100000L
          )
          prepared <- prepare_final_gate_druggability_data(
            scores = member_scores$data,
            eligible_groups = score_groups,
            max_groups = 2000L
          )
          list(
            error = "",
            relation = member_scores$relation,
            data = prepared$data,
            truncated = prepared$truncated,
            threshold = result$threshold
          )
        }, error = function(error) {
          empty$error <- conditionMessage(error)
          empty
        })
      })

      shiny::observe({
        result <- final_druggability_plot_data()
        if (nzchar(result$error) || nrow(result$data) == 0L) {
          shiny::updateSelectizeInput(
            session = session,
            inputId = "final_druggability_group",
            choices = character(),
            selected = character(),
            server = TRUE
          )
          return()
        }
        choices <- final_gate_druggability_group_choices(data = result$data)
        default <- default_final_gate_druggability_group(data = result$data)
        selected <- input$final_druggability_group %||% default
        if (!selected %in% unname(choices)) {
          selected <- default
        }
        shiny::updateSelectizeInput(
          session = session,
          inputId = "final_druggability_group",
          choices = choices,
          selected = selected,
          server = TRUE
        )
      })

      final_druggability_selected_plot <- shiny::reactive({
        result <- final_druggability_plot_data()
        empty <- list(
          error = result$error,
          relation = result$relation,
          data = tibble::tibble(),
          overview_truncated = FALSE,
          prepared_truncated = result$truncated,
          threshold = result$threshold,
          selection = "",
          summary = list()
        )
        if (nzchar(result$error) || nrow(result$data) == 0L) {
          return(empty)
        }
        choices <- final_gate_druggability_group_choices(data = result$data)
        selection <- input$final_druggability_group %||%
          default_final_gate_druggability_group(data = result$data)
        if (!selection %in% unname(choices)) {
          selection <- default_final_gate_druggability_group(data = result$data)
        }
        tryCatch({
          filtered <- filter_final_gate_druggability_data(
            data = result$data,
            selection = selection,
            max_all_groups = 30L
          )
          summary <- summarise_final_gate_druggability_selection(
            data = filtered$data,
            threshold = result$threshold
          )
          list(
            error = "",
            relation = result$relation,
            data = filtered$data,
            overview_truncated = filtered$truncated,
            prepared_truncated = result$truncated,
            threshold = result$threshold,
            selection = selection,
            summary = summary
          )
        }, error = function(error) {
          empty$error <- conditionMessage(error)
          empty
        })
      })

      final_druggability_count <- function(field) {
        value <- final_druggability_results()[[field]]
        if (length(value) != 1L || is.na(value)) {
          return("—")
        }
        format(value, big.mark = ",")
      }
      output$final_druggability_recorded_passes <- shiny::renderText({
        final_druggability_count("recorded_passes")
      })
      output$final_druggability_selected_passes <- shiny::renderText({
        result <- final_druggability_results()
        if (is.na(result$selected_passes)) {
          return("—")
        }
        paste0(
          format(result$selected_passes, big.mark = ","),
          " at ",
          formatC(result$threshold, format = "f", digits = 2L)
        )
      })
      output$final_druggability_difference <- shiny::renderText({
        result <- final_druggability_results()
        if (is.na(result$selected_passes) || is.na(result$recorded_passes)) {
          return("—")
        }
        sprintf("%+d", result$selected_passes - result$recorded_passes)
      })
      output$final_druggability_changed_count <- shiny::renderText({
        result <- final_druggability_results()
        if (nzchar(result$error)) {
          return("—")
        }
        format(nrow(result$changes), big.mark = ",")
      })
      output$final_druggability_notice <- shiny::renderUI({
        result <- final_druggability_results()
        if (nzchar(result$error)) {
          return(shiny::div(class = "alert alert-info", result$error))
        }
        shiny::div(
          class = "alert alert-secondary",
          paste0(
            "Sensitivity source: ", result$relation, ". The list contains ",
            "groups passing every fixed recorded gate when minimum member ",
            "druggability is required to be ≥ ",
            formatC(result$threshold, format = "f", digits = 2L),
            "."
          )
        )
      })
      output$final_druggability_plot_notice <- shiny::renderUI({
        result <- final_druggability_selected_plot()
        if (nzchar(result$error)) {
          return(shiny::div(
            class = "alert alert-info",
            paste0("The member-level box plot is unavailable: ", result$error)
          ))
        }
        notes <- paste0(
          "Each point is one assessed member's retained selected-pocket score. ",
          "Individual choices show any scored structurally assessed group; ",
          "the comparison option shows groups passing every other fixed final ",
          "gate. The dashed line is the selected threshold. Score source: ",
          result$relation,
          "."
        )
        if (isTRUE(result$overview_truncated)) {
          notes <- paste(
            notes,
            paste(
              "The all-groups comparison is limited to the first 30 groups",
              "reaching the last gate by final rank; every scored",
              "structurally assessed group remains individually selectable."
            )
          )
        }
        if (isTRUE(result$prepared_truncated)) {
          notes <- paste(
            notes,
            paste(
              "The selector reached its defensive limit of 2,000",
              "structurally assessed groups."
            )
          )
        }
        shiny::p(class = "small text-muted", notes)
      })
      output$final_druggability_group_summary <- shiny::renderUI({
        result <- final_druggability_selected_plot()
        if (nzchar(result$error) || length(result$summary) == 0L) {
          return(NULL)
        }
        summary <- result$summary
        heading <- if (identical(result$selection, ALL_FINAL_GATE_GROUPS)) {
          shiny::strong("Comparison view: all groups reaching the last gate")
        } else {
          shiny::tagList(
            shiny::strong("Selected evolutionary group: "),
            summary$primary_group_id,
            shiny::span(" | "),
            shiny::strong("Lead cluster: "),
            summary$cluster_id
          )
        }
        shiny::tagList(
          shiny::p(heading),
          bslib::layout_columns(
            bslib::value_box(
              "Groups displayed",
              format(summary$group_count, big.mark = ",")
            ),
            bslib::value_box(
              "Assessed members",
              format(summary$member_count, big.mark = ",")
            ),
            bslib::value_box(
              "Minimum member score",
              formatC(summary$minimum_score, format = "f", digits = 3L)
            ),
            bslib::value_box(
              paste0(
                "Status at ",
                formatC(result$threshold, format = "f", digits = 2L)
              ),
              summary$status
            )
          )
        )
      })
      final_druggability_boxplot <- shiny::reactive({
        result <- final_druggability_selected_plot()
        if (nzchar(result$error) || nrow(result$data) == 0L) {
          return(NULL)
        }
        build_final_gate_druggability_plot(
          data = result$data,
          threshold = result$threshold
        )
      })
      output$final_druggability_boxplot <- plotly::renderPlotly({
        final_druggability_boxplot()
      })
      output$download_final_druggability_boxplot_pdf <-
        shiny::downloadHandler(
          filename = function() {
            threshold <- final_druggability_selected_plot()$threshold
            value <- gsub(
              "\\.",
              "p",
              formatC(threshold, format = "f", digits = 2L)
            )
            paste0("final_gate_member_druggability_", value, ".pdf")
          },
          content = function(path) {
            plot <- final_druggability_boxplot()
            if (is.null(plot)) {
              stop("No druggability distribution is available.", call. = FALSE)
            }
            write_plotly_pdf(plot = plot, path = path)
          }
        )
      output$final_druggability_result_table <- DT::renderDT({
        result <- final_druggability_results()
        data <- result$selected
        if (nrow(data) == 0L) {
          message <- if (nzchar(result$error)) {
            result$error
          } else {
            paste(
              "No evolutionary group passes the complete selected gate",
              "intersection."
            )
          }
          data <- tibble::tibble(message = message)
        }
        readable_datatable(
          data,
          rownames = FALSE,
          filter = "top",
          options = list(
            pageLength = 25,
            scrollX = TRUE,
            deferRender = TRUE,
            dom = "tip"
          )
        )
      })
      output$final_druggability_changes_table <- DT::renderDT({
        result <- final_druggability_results()
        changes <- result$changes
        if (nrow(changes) == 0L) {
          message <- if (nzchar(result$error)) {
            result$error
          } else {
            "No group changes pass status at the selected threshold."
          }
          changes <- tibble::tibble(message = message)
        }
        readable_datatable(
          changes,
          rownames = FALSE,
          filter = "top",
          options = list(pageLength = 15, scrollX = TRUE, dom = "tip")
        )
      })
      output$final_druggability_download_tsv <- shiny::downloadHandler(
        filename = function() {
          threshold <- formatC(
            final_druggability_results()$threshold,
            format = "f",
            digits = 2L
          )
          paste0(
            "final_druggability_sensitivity_threshold_",
            sub(".", "p", threshold, fixed = TRUE),
            ".tsv"
          )
        },
        content = function(path) {
          utils::write.table(
            final_druggability_results()$selected,
            file = path,
            sep = "\t",
            quote = TRUE,
            row.names = FALSE,
            na = ""
          )
        }
      )
      output$final_druggability_download_excel <- shiny::downloadHandler(
        filename = function() {
          threshold <- formatC(
            final_druggability_results()$threshold,
            format = "f",
            digits = 2L
          )
          paste0(
            "final_druggability_sensitivity_threshold_",
            sub(".", "p", threshold, fixed = TRUE),
            ".xlsx"
          )
        },
        content = function(path) {
          write_formatted_excel(
            data = final_druggability_results()$selected,
            path = path
          )
        }
      )

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
