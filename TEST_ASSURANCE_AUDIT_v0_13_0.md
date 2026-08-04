# E3 project scientific test-assurance audit

Date: 2026-08-03
Corrective addendum: 2026-08-04
Scope: source ingestion, discovery, orthology, domains, expression,
ligandability, structural alignment, integrated prioritisation, Python app and
Shiny app.

## Conclusion

The repository now has materially stronger assurance than a count of green
tests. The review added independently specified known answers, exact threshold
boundaries, deliberately corrupted inputs, cardinality/provenance invariants
and raw-to-database tests. It also found and fixed defects that the former test
suites did not detect.

The most serious defect was the Expression Atlas cell parser: a cell such as
`3,3,3,4,5` could be concatenated to `33345`. Official Atlas source semantics
show that the five values are minimum, lower quartile, median, upper quartile
and maximum; the published expression level is the median. The corrected
importer therefore publishes `3.0`, retains all five values, and rejects the
wrong number or order of statistics.

Tests are evidence, not an absolute guarantee. The release gate is strongest
when a test's expected result is calculated independently of the production
implementation and when production outputs also pass run-level validation and
biological spot review.

## Assurance method

Every scientific package was reviewed against five complementary test types:

1. **Known answers**: small fixtures with hand-calculated expected outputs.
2. **Boundary truth tables**: values exactly below, at and above every gate.
3. **Corruption tests**: malformed, duplicated, incomplete, non-finite and
   provenance-mismatched inputs must fail closed.
4. **Cardinality and lineage checks**: joins may not multiply/drop scientific
   entities, and every published result remains bound to its raw checksum.
5. **Cross-layer tests**: an input is followed through multiple package layers
   so two components cannot silently disagree about a shared contract.

Coverage is retained as a guard against unexercised branches, but it is never
used as a substitute for semantic assertions.

## Defects found and permanent regression protection

| Severity | Finding | Correction and regression authority |
|---|---|---|
| Critical | Atlas five-number cells could be concatenated as thousands-like text. | Median semantics with all five statistics retained; malformed comma counts, non-finite, negative and unordered values rejected; raw-to-DuckDB known-answer test. |
| Critical | The clean-rebuild README passed a legacy relative-path manifest directly to the strict importers, so every source could be unresolved from the documented working directory. | A dedicated preparation command now rebases sources against an explicit raw root, computes SHA-256, acquires missing configuration XML, and atomically publishes an absolute-path strict manifest. Both importers also preflight the complete source set. |
| High | Metadata groups could be inferred from factor order rather than the experiment configuration. | Exact `gN`-to-assay mapping now comes from configuration XML; missing referenced IDs, duplicate IDs and assays reused across groups fail. Matrix and XML order are not assumed. |
| High | The v0.5.0 tests incorrectly required numerically ordered, contiguous `g1..gN` columns, although real Atlas matrices are lexicographically ordered and may contain sparse group IDs. | Matrix groups are now unique valid `gN` identifiers in source order; every matrix ID must exist in XML, XML-only IDs are permitted, and joins use the literal ID. All 387 captured previews and 897,650 cells pass the production parser. |
| High | The metadata CLI could publish SDRF-only output without a matrix or configuration XML, despite the documented strict contract. | Every metadata job now requires non-empty SDRF, expression matrix and configuration XML before any import starts; the permissive historical test was replaced with fail-closed and complete-authority tests. |
| High | Tissue metadata could remain joined to a changed expression matrix. | Expression and metadata relations must carry the same raw matrix SHA-256; stale bindings fail before publication. |
| High | TPM and FPKM could both contribute when both existed. | TPM is selected per species/experiment; FPKM is an explicit fallback only. |
| High | `NOT_MAPPED` expression could be displayed as biological zero. | Unavailable mapping fields remain blank and distinct from Atlas measured-zero codes. |
| Medium | Off-target domain rows could change a target-species denominator. | Domain assessed/supported species are intersected with the configured target cohort; a regression test adds an off-target positive row and proves the gate is unchanged. |
| Medium | A source table with identifiers but no GO evidence could inflate GO evidence counts. | GO source inclusion and aggregation require actual GO/ubiquitin/exclusion fields; seven-source known-answer integration tests cover it. |
| Medium | Empty/absent source catalogues could create placeholder relations missing downstream fields. | Typed empty relations now expose their complete published schema; absent-catalogue integration test covers the contract. |
| Test reliability | Resource-monitor tests depended on live PID visibility. | CPU/RSS aggregation and lifecycle tests now use deterministic process fixtures; external DIAMOND execution remains a separately reported integration check. |
| Low | Excel source ingestion left a workbook handle open until interpreter cleanup. | `ExcelFile` now has an explicit context-managed lifetime; the Excel fixture passes with `ResourceWarning` promoted to an error. |
| Low | Reconfiguring source-package logging detached file handlers without closing them and cleared unrelated root handlers. | Package-owned handlers are tagged, flushed, closed and removed without touching third-party handlers; the suite passes with `ResourceWarning` promoted to an error. |

## Executed Python assurance results

| Package | Tests | Skipped | Branch-aware coverage | Gate status |
|---|---:|---:|---:|---|
| Source-to-Parquet seed | 96 | 0 | 91% | Pass |
| Discovery engine | 215 | 3 | 97% | Pass; optional external-tool checks skipped here |
| Orthology integration | 42 | 0 | 96% | Pass |
| Ligandability pipeline | 83 | 0 | 97% | Pass |
| Structural alignment | 61 | 0 | 93% | Pass |
| End-to-end workflow | 224 | 1 | 90.56% | Pass; Snakemake contract check skipped because Snakemake is unavailable here |
| Expression downloader/importer | 118 | 0 | 90% | Pass |
| Python application | 40 | 0 | 98% | Pass |

Total package tests executed: **879 passed, 4 skipped**. A further **15
repository-root tests passed**; they validate launchers, documentation and the
test-traceability matrix rather than scientific calculations.

The exact contract-to-test mapping is in
`docs/SCIENTIFIC_TEST_ASSURANCE_MATRIX.tsv`.

## Package conclusions

### Source ingestion

The package now exercises the complete seven-source curated build with exact
row counts and values, missing-source typed relations, GO evidence semantics,
source provenance and corruption failure. A remaining limitation is that some
historical code uses a wider formatting style; this is cosmetic and does not
alter the executed semantic gate.

### Discovery

Identity and both coverage thresholds are explicitly inclusive. Bit score and
e-value thresholds are explicitly exclusive, matching the recorded production
logic. Header parsing covers the exact DIAMOND 2.2.x formats as well as
malformed variants. Resource monitoring is now deterministic in unit tests.
The three skipped tests require a compatible external DIAMOND executable and
are not represented as having run.

### Orthology

Synthetic OrthoFinder authorities verify exact group IDs, member identities,
species mapping and sequence recovery. Ambiguous identifiers, duplicated maps,
missing species and corrupt archives fail. No production defect was found in
this package during this review.

### Domains

Domain cache/API parsing, assessed-species denominators, missing annotations
and target-cohort restriction are covered in the integrated workflow. The
review fixed the off-target denominator leak. The distinction between
"unavailable annotation" and "assessed negative" remains explicit.

### Ligandability

Tests independently assert mmCIF residue identities, pLDDT denominators,
fpocket/P2Rank joins, ambiguous residue mappings, QC and atomic publication.
No production defect was found in the standalone package during this review.

### Structural alignment

Tests assert exact TM-score selection, local pocket-residue mappings, strict
versus sensitivity decisions, top-k behaviour, checksum-bound resume and
review-page assets. External USalign/TMalign/fpocket/P2Rank programs were not
installed in this environment, so command construction and parsers were tested
with controlled fixtures rather than new real-tool runs.

### Expression

This layer received the deepest rebuild because the previous parser contract
was wrong. The supported code now requires complete raw evidence, prepares the
legacy manifest without modifying its retained sources, accepts real Atlas
lexicographic and sparse `gN` identifiers, retains tissue/development/treatment
context, validates hashes and identifier-based joins, and publishes atomically.
The unsupported R parser and legacy R-manifest downloader fail closed.

The first v0.13.0 assurance pass still relied on tidy manifest-path and `gN`
ordering fixtures. The 2026-08-04 corrective pass was triggered by the actual
cluster failure and replaced those assumptions with the captured production
grammar. This limitation and correction are recorded explicitly so the audit
does not imply that its earlier green suite was sufficient.

### Integrated prioritisation

The workflow now tests expression median semantics, inclusive `0.5`, TPM
precedence, FPKM fallback, context cardinality, tissue output, mapping states,
assessed-species denominators, domain target restriction, residue coordinates
and final reporting lineage. A new workflow run is required; corrected
expression evidence must not be substituted into an old completed run.

### Applications

The Python app has headless render, corrupt-resource, deduplicated group count,
threshold, glossary, expression-context and pocket-review tests. The Shiny app
has parallel `testthat` coverage in source, but R is unavailable in the current
execution environment; its full `testthat` suite remains a mandatory external
release step.

## Mandatory production release checks

Before treating a clean expression rebuild as authoritative:

1. run every package's configured quality gate in its declared conda
   environment;
2. run the complete Shiny and expression R `testthat` suites;
3. run external DIAMOND/USalign/TMalign/fpocket/P2Rank smoke tests where the
   real executables are installed;
4. build expression Parquet and DuckDB in a new versioned directory;
5. require zero failed import rows and equality of selected-expression and
   metadata-joined context counts;
6. generate a new checksum-bound workflow expression manifest;
7. run workflow v0.13.0 in a new run root;
8. compare old and new mapping, expression, gate and ranking counts;
9. biologically spot-check representative genes, tissues and expression
   values against the retained raw files and official Atlas pages;
10. only then rebuild the portable release used by both apps.

## Known limitations

- The uploaded snapshot contains bounded matrix previews, not every raw matrix;
  full-data validation must run on the cluster download tree.
- R was not available here, so no claim is made that `testthat` executed in this
  environment.
- External scientific executables were not available here; fixture-based
  parser/command tests do not replace a real-tool smoke run.
- Test coverage above 90% means most branches executed, not that every possible
  biological input or future upstream format is known.
