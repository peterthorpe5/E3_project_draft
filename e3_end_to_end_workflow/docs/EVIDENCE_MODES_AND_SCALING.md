# Evidence modes, missing data and larger-panel scaling

## One downstream contract, two production strategies

The master workflow separates how evidence is obtained from how it is interpreted. Every stage
records one evidence mode:

| Mode | Meaning |
|---|---|
| `validate` | Checksum and validate controlled inputs without recomputing science. |
| `prepare` | Normalise and isolate supplied inputs. |
| `reuse` | Copy or query a completed reviewed authority and record its checksum provenance. |
| `download` | Retrieve a bounded public annotation resource into a persistent cache. |
| `derive` | Compute a deterministic join, score or report from completed authorities. |
| `generate` | Run the scientific component on the configured inputs. |

The current study intentionally reuses the reviewed 60-proteome OrthoFinder 2.5.5 archive, the
7,255-cluster candidate authority, downloaded Expression Atlas Parquet and existing structural
pocket results. Reuse is not a shortcut hidden from the report: the source path, checksum, manifest,
mode and command are retained in the stage and full-run HTML.

For a future expanded analysis, the same stages can prepare a larger proteome manifest and generate
new Discovery, OrthoFinder and ligandability authorities. Downstream stages consume the same
standard Parquet tables, so the scoring, DuckDB, HTML and application interfaces do not depend on
which acquisition mode was used.

## Domain evidence without local InterProScan

Stage 06 retrieves the existing InterPro protein annotation response for each parseable accession
in the selected target-species orthology groups. Pfam member-database hits are retained alongside
InterPro entries. Responses are cached atomically by accession and may be converted to a
checksum-bound offline manifest.

This strategy avoids installing and rerunning InterProScan/Pfam for the current study. It also
scales incrementally: a future panel downloads only accessions absent from the shared cache. API
errors and unparseable identifiers remain explicit. They do not become `no E3 domain` calls.

Domain status has three scientific states:

| State | Interpretation |
|---|---|
| `SUPPORTED` | At least one catalogued E3-relevant InterPro/Pfam annotation was found. |
| `ANNOTATED_NO_CATALOGUED_E3_DOMAIN` | Annotation was available but no catalogued E3 domain was found. |
| `ANNOTATION_UNAVAILABLE` | The protein could not be assessed; exclude it from the domain denominator. |

## Expression and structural absence

Expression Atlas availability is determined from the controlled manifest. Species missing from
that manifest remain unavailable. Within an available species, identifier mapping failures and
mapped proteins with limited or zero measured expression remain distinct results.

Likewise, a missing AlphaFold/pocket result is distinct from a completed model whose best pocket
fails quality thresholds. Final rankings expose both evidence scores and evidence-completeness
fractions, allowing reviewers to distinguish weak evidence from absent evidence.

## Larger proteome panels

The pipeline does not assume 12 species, 60 proteomes or a particular plant list. A larger run must:

1. add checksum-bound FASTAs to `proteomes.tsv`;
2. update the orthology species manifest and target/mandatory species lists;
3. choose a new immutable run name;
4. configure reviewed component commands and stage resource limits;
5. keep OrthoFinder at exactly 2.5.5 unless the project formally versions a different contract;
6. validate and dry-run the complete DAG before submission.

The configured fraction thresholds adapt to panel size. Raw assessed/available/missing counts are
also published so a high score cannot conceal sparse evidence. Expensive components can request up
to the cluster allocation (currently 32 CPUs and 180 GB), while lightweight reuse and integration
stages remain smaller.
