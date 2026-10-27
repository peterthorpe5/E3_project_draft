# Search and complete downloads

Use the top-level **🔎 Search & results** section. It contains **Protein & HOG
search** and **All results**; search is no longer inside Chemistry & outputs.
**All results is also available under Candidate discovery.** Both entries open
the same page, source selection and complete-download controls.
The six scientific stages and the generic Protein research workbench remain
available. Opening a page does not launch a new analysis or contact DeepClust.

## Find a protein and inspect its HOG

1. Open **Protein & HOG search**. Paste HOG/OG IDs, accessions, gene names,
   FASTA identifiers, seed or DeepClust identifiers, or protein-name fragments.
   Up to 50 terms are accepted, one per line or separated by commas,
   semicolons or tabs. Whitespace and identifier case do not affect matching.
2. Use **smart** for exact identifiers and partial descriptive names, **exact**
   for whole identifiers/list tokens, or **contains** for incomplete identifiers
   and literal substrings. Percent signs and quotes are literal text, not SQL.
3. Press **Search the complete loaded resource**. Complete HOG/OG IDs in smart
   or exact mode use a direct lookup in recorded group fields, with stored ranks
   and member metadata shown first. Surrounding whitespace is removed. Full
   dossier inventories are not calculated before the initial result. Names,
   proteins, incomplete IDs in contains mode and the explicit **Search names
   and all identifier fields as well** option use the broader recognised-field
   search. Timed spinners show when work is running. Broad match counts cover
   all source rows; repeated hits for different entered terms retain provenance.
4. Select **Inspect a HOG or group**. A protein may map to several recorded
   groups, including an OG and a root HOG. Choose the group appropriate to the
   biological question. The selector is not derived from the first preview rows.
5. Read the original rank before and after structural analysis and their source
   fields. Rank selection is performed independently for the inspected group
   and each stage using the maintained source preference. A short final
   shortlist cannot hide an earlier full-resource ranking. Missing ranks are
   unavailable; a cluster or member rank is not promoted to a group rank.
6. Press **Load complete evidence dossier**, then inspect the inventory and
   select any source to preview its records. The app shows link discovery and
   counting phases. The completed graph, inventory and bounded source previews
   are cached for this search and source, so changing download format or preview
   source does not repeat the whole operation. Use **Reload complete evidence
   dossier** to request an explicit refresh.
   It includes the available enriched HOG overview/members, all group-linked
   recorded ranks and raw source evidence linked by group, contributing-cluster
   or protein identifiers. Release metadata/provenance is included when present.
7. Select TSV archive or Excel, press **Prepare complete download**, then the
   download button. The dossier contains every matching row and field in its
   planned sources, including hidden preview fields and sequences stored there.

The **Direct matching rows and complete search downloads** expander provides
the original search hits, with entered term, source relation and matched fields.
That export retains direct matches; the selected-group dossier additionally
follows recorded identifier links. A direct match without a recorded group link
remains downloadable without an invented HOG or ranking.
For a direct HOG/OG lookup, press **Load direct matching rows** to calculate
the full per-source match counts. This scans group fields, not every descriptive
name or protein field. The wider-search option is available for references in
those other fields.

## Download all results

1. Open **All results** from **Candidate discovery** or **Search & results**.
   The published `candidate_master_results` relation is selected by default
   when available. Choose another raw relation or an enriched HOG view as needed.
2. Leave **Find within this complete result** empty to include every row in that
   view. To find an arbitrary HOG or protein beyond the first 1,000 rows, enter
   its identifier. Filtering runs before preview limiting and also searches
   recognised fields hidden from the preview.
3. Raw-result counts are cached independently of the preview. Joined HOG
   previews/counts are optional: enable **Load joined HOG preview and counts**
   to inspect them. A complete joined download is available without doing this.
4. In **Complete download**, select a format, press **Prepare all results
   download**, then **Download all results**. These
   controls export all matching rows and fields. They ignore **Rows to display**,
   **Preview fields** and the command-line `--max-rows` screen limit.
   Its manifest reports the actual exported row count, including when the joined
   preview/count was not requested.
5. Use **Screen preview** for a compact table. Its separately labelled preview
   downloads contain only the rows/fields displayed. Clearing every preview
   field does not disable the complete download.

“All results” means all rows and fields in the chosen result view, or all its
filtered matches. Different raw relations have different granularities and are
not flattened into one ambiguous table. A selected-group dossier collects the
related tables together for a specific protein/HOG investigation.

## Export contents and limits

| Format | Contents | Completeness |
| --- | --- | --- |
| TSV archive (`.zip`) | Separate UTF-8 TSVs, README, manifest and field dictionary | Every query row/field; long cells retained |
| Excel (`.xlsx`) | Separate source worksheets, Manifest, Read me and Column definitions | Every query row/field; oversized tables split across sheets |
| Preview TSV/Excel | Exactly the screen preview | Intentionally limited by preview rows and fields |

Archive/workbook manifests report actual exported row and field counts for
each source, including zero-row dossier sources. TSV cells containing tabs or
newlines are quoted. SQL nulls are empty cells. Numeric values in Excel remain
numeric where safely representable; identifiers, formula-like text and large
integers remain literal text. Dates retain ISO values. No cell is executed as
a formula and URLs are not converted into active hyperlinks.

Excel allows 1,048,576 rows per worksheet including the header, 16,384 columns
and 32,767 characters per cell. Tables split at the row limit. If a value or
field count cannot fit, the export fails clearly and directs the user to TSV;
it does not silently trim the value or return a partial workbook.

Complete queries have no display-derived or 100,000-row export ceiling. They
are read in 4,096-row batches rather than loaded into one pandas data frame.
The final download still occupies Streamlit memory, and exact counts/dossiers
can require substantial database work. Request large downloads deliberately.
Changing the source, selected group/result, applied filter or export format
invalidates its prepared payload. A source failure does not yield a silently
partial “complete” export. No source rows are written or reranked.
Selected-HOG source predicates run before membership aggregation and within-HOG
window functions; whole HOG partitions are retained, so stored and within-HOG
rank meanings are preserved. Exact group lookups do not build the complete
evidence graph automatically. Shared-key matching uses vector/list predicates
instead of a correlated loop through every target key for every source row.

## Evidence scope

The dossier follows explicit stored identifiers. Shared proteins or contributing
clusters may connect source rows carrying another group annotation; those rows
retain the original context and `_dossier_link_columns` rather than claiming a
new orthology assignment. The process does not recursively expand neighbouring
groups through shared members. Descriptive similarity alone is not a join key.

The enriched overview/member views retain their established strongest-source
join. The dossier's recorded-rank table and per-stage rank display additionally
expose ranks from other available sources; raw tables preserve all original
values. Missing membership, ranks, domains, expression or structures are not
invented or converted into biological negatives.

The scope is tabular evidence in the loaded E3 resource. External databases,
remote research jobs and model/review files in separate structural bundles are
not fetched or embedded by these exports. Use their existing pages/downloads
for those files. The same identifier-based approach supports other group
schemas without requiring an E3 seed, root HOG or a DeepClust installation.
