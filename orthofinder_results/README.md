# orthofinder-results

`orthofinder-results` turns a completed OrthoFinder result directory into a
versioned, queryable and portable analytical resource. It is intentionally a
generic package: no E3-ligase assumptions are built into its parsers or schema.

The package supports completed OrthoFinder 2 and OrthoFinder 3 layouts. For
OrthoFinder 3, hierarchical orthogroups (HOGs) are the primary authority and a
legacy `Orthogroups.tsv` file is optional. Every HOG level (`N*.tsv`) is kept,
so later analyses can work at the root, at an internal species-tree node, or
across several levels without rebuilding the package.

This project is independent of, and is not endorsed by, the OrthoFinder
authors. Cite OrthoFinder itself when using its results.

## What one run publishes

Each successful run creates one immutable output directory containing:

- long-form legacy orthogroup and all-level HOG memberships;
- per-group member, species, copy-number and single-copy statistics;
- species and sequence identifier mappings when OrthoFinder retained them;
- a checksum inventory of every discovered input, gene tree and resolved tree;
- a normalised species tree, and optionally every gene tree, as node/edge tables;
- optional aligned-sequence pairwise distances and per-cluster distributions;
- matching TSV and typed Parquet tables;
- a physical, portable DuckDB containing the same analytical relations;
- explicit QC checks, a complete run manifest and a persistent run log; and
- a self-contained offline HTML report with an interactive cluster network.

The HTML is the final publication stage. It embeds the JavaScript and CSS it
needs, so the report opens without internet access. The user can select a
cluster, pan, zoom, search and click members, inspect species labels, view a
distance histogram, and filter or page through cluster statistics.

Browser visualisation is deliberately bounded. Large groups are selected and
sampled deterministically for rendering, while the full TSV, Parquet and
DuckDB tables remain the analytical authorities. The report states these
limits rather than pretending that a browser can safely render millions of
nodes.

## Data contract designed for later questions

All group records use this composite identity:

```text
(run_id, group_type, hierarchy_node, group_id)
```

This prevents an identifier such as `OG0001686` or `N0.HOG0002084` from being
silently equated across independent OrthoFinder runs. Expanded runs with new
species must receive a new `run_id`. Future split, merge and overlap analyses
can then map member sets across runs without overwriting either source.

The schema preserves:

- the exact source species label and member identifier;
- HOG node, parent clade and legacy orthogroup link when supplied;
- source filename and row number;
- tree type, tree identifier, branch lengths and node relationships;
- the exact distance method and `EXACT` or sampled status; and
- checksums and OrthoFinder/package versions.

These fields support later phylogeny, cluster-size, taxonomic distribution,
cluster splitting and expanded-species comparisons without redesigning the
raw ingestion layer.

## Installation

Conda is recommended on the cluster:

```bash
cd /path/to/E3_project_draft/orthofinder_results
conda env create --file environment.yml
conda activate orthofinder_results
python -m pip install --no-deps --editable .
./run_tests.sh
```

For an existing Python 3.11+ environment:

```bash
python -m pip install --editable '.[dev]'
./run_tests.sh
```

## Inspect before running

Inspection is read-only and writes its complete output to a named persistent
file:

```bash
orthofinder-results \
  --action inspect \
  --results-dir /path/to/OrthoFinder/Results_Feb26 \
  --inspection-output "$HOME/orthofinder_results_feb26_inspection.json"
```

The inspection records the detected OrthoFinder version, chosen adapter,
primary group authority and available result capabilities.

## Run locally

All CLI controls are named. No source file beneath `--results-dir` is modified.

```bash
orthofinder-results \
  --action run \
  --results-dir /path/to/OrthoFinder/Results_Feb26 \
  --output-dir /persistent/project/orthofinder_results/results_feb26_v0_1_0 \
  --run-id results_feb26 \
  --work-dir /persistent/project/orthofinder_results/work \
  --report-max-groups 25 \
  --report-max-members 250 \
  --report-nearest-neighbours 3
```

If OrthoFinder produced `MultipleSequenceAlignments`, they are discovered. An
external aligned-FASTA directory can instead be declared:

```bash
orthofinder-results \
  --action run \
  --results-dir /path/to/OrthoFinder/Results_Feb26 \
  --output-dir /persistent/project/orthofinder_results/results_feb26_with_distances \
  --run-id results_feb26 \
  --work-dir /persistent/project/orthofinder_results/work \
  --alignment-dir /persistent/project/alignments \
  --distance-group-type HOG \
  --distance-hierarchy-node N0 \
  --distance-max-members 250
```

`--distance-source AUTO` is the default. It prefers aligned-sequence distances
when recognised alignments exist and otherwise uses resolved gene-tree branch
lengths. Tree-backed HOG calculations match the HOG's legacy orthogroup link
when available and restrict the tree to that HOG's members. OrthoFinder 3
layouts without a legacy link can match a tree by the HOG identifier itself.
Use `--distance-source NONE` to disable distances, or name
`ALIGNED_SEQUENCE`/`RESOLVED_GENE_TREE` to require one authority and fail when
it is unavailable.

Alignment filenames are treated as exact group identifiers. Protein distances
are amino-acid p-distances with pairwise deletion of gaps and ambiguous
residues. Unequal sequence lengths fail explicitly. Groups above the member
limit use a deterministic hash sample, recorded as
`DETERMINISTIC_MEMBER_SAMPLE`; smaller groups are recorded as `EXACT`.

For tree-backed calculations, clusters are ordered by decreasing member count
and `--distance-max-groups` applies to that deterministic order. A value of
zero requests every eligible group; choose an explicit bound for a first
cluster pilot. Missing trees or member-name mismatches produce a per-cluster
`UNAVAILABLE` summary with `failure_reason`, not a fabricated zero distance.
Pair and summary records carry the exact alignment or tree `source_file`.

Use `--parse-gene-trees` only when normalised nodes and edges for every gene
tree are required. Tree files are checksum-inventoried even when their nodes
are not expanded, so a resumed run cannot miss a changed tree.

## Resume and replacement

`--resume` reuses an output only when the completed manifest, run identifier,
package version and full source digest match. `--force` never deletes an old
result: it moves it to a timestamped `.superseded.*` path before publication.
The two options are mutually exclusive.

Staging occurs on the same filesystem as the formal output and publication is
an atomic rename. Paths under `/tmp` and `/private/tmp` are rejected. Use a
named project, scratch or home-directory path instead.

## Slurm wrapper

The submission wrapper writes both standard output and error to persistent log
files, which is suitable for `mosh` sessions:

```bash
./submit_orthofinder_results_slurm.sh \
  --slurm-log-dir "$HOME/orthofinder_results_logs" \
  -- \
  --action run \
  --results-dir /path/to/OrthoFinder/Results_Feb26 \
  --output-dir /persistent/project/orthofinder_results/results_feb26_v0_1_0 \
  --run-id results_feb26 \
  --work-dir /persistent/project/orthofinder_results/work
```

The wrapper prints the job identifier, exact output/error log paths and the
`squeue` command. The bundled job requests ordinary resources by default; it
does not select a long-duration QoS.

## Query examples

```sql
-- Largest root-level HOGs.
SELECT group_id, member_count, species_count, max_copies_per_species
FROM group_statistics
WHERE group_type = 'HOG' AND hierarchy_node = 'N0'
ORDER BY member_count DESC
LIMIT 25;

-- Distance coverage and central tendency for one group.
SELECT group_id, distance_method, computation_status,
       sampled_member_count, distance_pair_count,
       mean_distance, median_distance
FROM distance_statistics
WHERE run_id = 'results_feb26'
  AND hierarchy_node = 'N0'
  AND group_id = 'N0.HOG0002084';

-- Candidate splits: root HOGs represented by several child-level HOGs.
SELECT legacy_orthogroup_id, hierarchy_node,
       count(DISTINCT group_id) AS child_hog_count
FROM hog_memberships
WHERE legacy_orthogroup_id <> ''
GROUP BY legacy_orthogroup_id, hierarchy_node
HAVING count(DISTINCT group_id) > 1
ORDER BY child_hog_count DESC;
```

Open the database with:

```bash
duckdb /path/to/output/duckdb/orthofinder_results.duckdb
```

## Scope of version 0.1.0

Version 0.1.0 establishes loss-aware, version-aware ingestion and portable
publication. Cross-run cluster lineage (stable overlap scores, split/merge
classification and taxon-aware comparisons) belongs in a later, separately
tested comparison layer. Keeping source runs immutable is what makes that layer
possible and auditable.

## Development quality gate

```bash
./run_tests.sh
```

The gate runs unit and integration tests with branch coverage, pycodestyle,
pydocstyle, Ruff, Python compilation and shell syntax checks. Coverage must be
at least 95%.
