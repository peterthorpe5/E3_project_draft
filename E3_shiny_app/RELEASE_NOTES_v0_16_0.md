# ARIA plant E3 Shiny reporter v0.16.0

## Independent structural-review shortlist

The dedicated shortlist now answers the computational team's intended
question: which root-level HOGs should be considered for newly performed
structural analysis? It returns 200 HOGs by default, can expand to 500 and uses
the authoritative rank built from discovery, orthology/species, E3-domain and
expression evidence. Requiring the recorded pre-structure pass is optional.

Existing models, pockets, druggability, mapping, alignment, conservation and 3D
results are neither selected nor displayed in this table. They are preserved in
the other application tabs.

## Richer Threshold explorer

The paired pre-structure and structurally informed result tables now retain
many more available source fields and add root-HOG membership context. This
includes human and Arabidopsis representatives and identifiers, member/species
counts and lists, orthogroup and parent-clade links, review/mapping summaries,
ranks, seed evidence, domain/expression availability, inclusion/exclusion
reasons and explicit missing evidence. The same columns are retained in TSV and
formatted Excel downloads.

## E3 seed catalogue

A new tab searches one or several inherited seed identifiers, names or
annotation terms and downloads the result as TSV or formatted Excel. Exact
`known_e3_seeds` rows and provenance are preferred when the loaded release
contains that authority. Older releases use a clearly labelled
cluster-associated fallback rather than inventing per-seed annotations.

Available accession-matched protein sequences can be downloaded as FASTA. The
sequence reconciliation inspects every sequence-bearing HOG member because the
`is_input_candidate` field is not a seed flag. The catalogue has a dedicated
hard cap of 100,000 rows so a complete controlled seed set can be requested
without removing query bounds.

## Release gate

```bash
cd E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

The two `test_script_utils.R` skips remain expected when no `--file` argument is
available. Any actual failure blocks release.
