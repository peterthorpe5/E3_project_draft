# ARIA E3 Python reporter v0.10.0

## New exploration views

- Adds a lazy-loaded **Human HOGs** tab containing every root-level
  `N0.HOG…` with at least one `Homo_sapiens` member.
- Adds a separate **Plant & human HOGs** tab requiring both human membership
  and membership from at least one of the 12 curated target plant species.
- Both views retain ranked and unranked HOGs, candidate ranking position and
  status where available, composition counts, human identifiers, all HOG
  co-members, aliases and candidate-linked sequence annotations.
- Both views provide complete TSV and formatted Excel downloads plus FASTA when
  the integrated release contains the corresponding protein sequences.

## Search replacement

- Replaces exact single-accession search with a batch-capable complete-resource
  search for names, HOG/OG IDs, E3 seeds, accessions, entries, gene identifiers
  and DeepClust identifiers.
- Accepts newline, comma, semicolon or tab lists, with smart, exact-token and
  literal-contains modes.
- Every hit records the original search term, source relation and matching
  fields before returning every available source column.

## Scientific boundaries

- Human/plant HOG membership is explicitly evolutionary co-membership rather
  than evidence that every member is an E3 ligase.
- HOGs absent from the candidate ranking are labelled
  `NOT_IN_CANDIDATE_RANKING`; absence is not converted into biological failure.
- DeepClust remains a separate non-phylogenetic sequence-neighbourhood view.

## Validation

- Adds focused unit and representative DuckDB tests for HOG view definitions,
  ranking enrichment, aliases, member sequences, list parsing, matching modes,
  bounds and source provenance.
- Updates headless Streamlit expectations for the two new views and replacement
  Search tab.
