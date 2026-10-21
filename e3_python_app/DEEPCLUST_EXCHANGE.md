# Selected DeepClust exports — v0.19.1

The E3 app can analyse selected DeepClust FASTA exports without installing the
global database on your laptop. The extraction step still needs access to the
database on another machine. Cloning the upstream tool provides its code, not a
remote database connection. No hosted extraction service has been configured.

The upstream source reviewed for this integration is
https://github.com/drostlab/deepclust_dataretrieval at commit
`b406fec8460d8044697c057bcb8c34f63549d98e`. Its code is not vendored into this app.

## 1. Keep the three kinds of identifier distinct

| Identifier | Example | Use |
| --- | --- | --- |
| Local E3 HOG / discovery cluster | `0.HOG0006943` | Select E3 members or recorded seed accessions. It is not a global DeepClust centroid. |
| DeepClust member sequence ID | Exact source-prefixed accession | Query `SeqIdMapClustId.parquet`, using the `SEQID` and `CLUSTERID` columns, to find its cluster. |
| DeepClust global centroid ID | `NR_UGC79169.1` | Supply to the extraction tool and to the import form. It is also a member of its cluster. |

Preserve source prefixes, case, punctuation and accession versions. For example,
`UGC79169.1` is not the same exact database key as `NR_UGC79169.1`. The app's
sequence mapping can test explicitly configured prefixes, but it never invents
a centroid ID from an E3 group or a similarity hit.

The upstream `--centroid_file` format is plain text: **one exact global centroid
ID per line, with no header and no FASTA `>` symbol**. The Discover page can
download this as `centroids.id.txt` from the entered retrieval IDs. It preserves
their spelling and removes duplicate entries.

Knowing a member accession does not itself reveal the centroid. The upstream
functional index searches centroid annotations; it is not an exhaustive
member-to-cluster lookup. Exact membership lookup requires the sequence map or
an export from a provider with access to it.

## 2. Extract on a machine that already has DeepClust

These commands are for a database holder. Do not run a global download on your
laptop to satisfy them. If no accessible machine has DeepClust, arrange a selected
export or remote access with a provider before this step. The app update does
not remove that prerequisite.

Clone the tool once outside the E3 repository:

```bash
TOOLS_DIR="$HOME/software"
mkdir -p "$TOOLS_DIR"
git clone https://github.com/drostlab/deepclust_dataretrieval.git \
    "$TOOLS_DIR/deepclust_dataretrieval"
git -C "$TOOLS_DIR/deepclust_dataretrieval" rev-parse HEAD
```

Use a Python environment with DuckDB and PyArrow; the E3 app environment includes
both. Record the actual tool commit and database release with your export.
Then replace these three absolute paths on that machine:

```bash
DB_DIR="/absolute/path/to/DeepClustParquet"
CENTROID_FILE="/absolute/path/to/centroids.id.txt"
EXPORT_DIR="/absolute/path/to/selected_deepclust_exports"
mkdir -p "$EXPORT_DIR"

python "$TOOLS_DIR/deepclust_dataretrieval/cluster_index.py" \
    --centroid_file "$CENTROID_FILE" \
    --per-clust-output 1 \
    --threads 1 \
    --verbose 1 \
    -path_to_DCD "$DB_DIR/joined_with_index_RowGroupFinal.parquet" \
    -path_to_index "$DB_DIR/clust_index_RowGroup.parquet" \
    -path_to_output "$EXPORT_DIR/"
```

The final slash on the output directory is intentional: the inspected upstream
script concatenates directory and filename strings. Use a fresh export directory
and check every requested cluster was produced; a successful upstream exit alone
does not certify that every requested ID matched. The upstream tool may create a
DuckDB file named `persistent` beside the index if one is not already present.
That location must permit it, or its operator must supply the existing index.

`--per-clust-output 1` is essential for this integration. It produces a separate
`<exact_centroid>.fa` with original sequence IDs. Upstream combined-output mode
adds a numeric prefix to sequence headers; the import deliberately rejects that
layout rather than guessing how to undo it. Single-threaded extraction also works
on macOS; upstream documents parallel extraction as Linux-only.

Obtain the expected `NMEMBER` count for each selected centroid from the cluster
index when possible. Request the release name and tool commit from the provider.
The published row-group index covers clusters with at least three members.

## 3. Copy only those exports to your laptop

For a data host reachable through your existing SSH account, replace the host
and remote directory below. No SSH credentials or remote service are bundled.

```bash
DB_HOST="your_user@your_database_host"
REMOTE_EXPORT_DIR="/absolute/path/to/selected_deepclust_exports"
LOCAL_EXPORT_DIR="$HOME/Downloads/deepclust_selected"
mkdir -p "$LOCAL_EXPORT_DIR"
rsync -avP "$DB_HOST:$REMOTE_EXPORT_DIR/" "$LOCAL_EXPORT_DIR/"
```

Alternatively receive just the selected `.fa` files from their provider. A very
large selected cluster may still be a large download; no complete export is
silently sampled or truncated.

## 4. Import into the E3 app

Open **stage 3 → Protein research workbench → Discover → Import extracted
cluster**. This is the initial discovery mode when no local index is available.

1. Enter the exact global centroid, for example `NR_UGC79169.1`.
2. Upload its per-cluster `.fa` file, up to 20 MB through the browser.
3. Enter the source/database release and the expected member count if available.
4. Queue the import and leave the research worker running in a separate terminal.
5. Once complete, open **Family analysis → Completed job** and choose that job's
   `cluster.fasta` for stricter clustering or alignment. Models and annotation can
   use the same completed FASTA.

With the default workspace, the worker needs no DeepClust profile:

```bash
conda activate e3_python_app
protein-research-workbench worker
```

If your app uses `--research-config`, supply the same TOML to the worker with
`protein-research-workbench --config /absolute/path/research.toml worker`.
For imports, the global `index`, `sequences` and `sequence_map` settings may be
left empty. Keep the same workspace and analysis executable settings in both
processes. Restart the worker after updating the installed app.

For files larger than 20 MB, queue a streaming local import instead of a browser
upload. There is no need to edit a parameters file or place the global database
on the laptop:

```bash
protein-research-workbench import-deepclust \
    --fasta "$HOME/Downloads/deepclust_selected/NR_UGC79169.1.fa" \
    --cluster-id "NR_UGC79169.1" \
    --source-label "DeepClust release supplied by DATABASE_PROVIDER"
```

Add `--expected-members ACTUAL_PUBLISHED_COUNT` when the count is known. For a
custom workspace, prepend `--config /absolute/path/research.toml` before the
`import-deepclust` subcommand, and use that profile for the app and worker too.
The command snapshots the local file and queues a job. The normal worker then
validates it. Allow disk space for the selected input, its SQLite staging index
and the normalised output.

## Evidence and limits

Imports require a non-empty protein FASTA, unique exact sequence IDs and the
stated centroid among those IDs. Invalid residues/internal stops and configured
sequence limits cause visible failures. Proteins are converted to upper case;
whitespace and terminal stop symbols are removed. Original uploaded bytes remain
in the job directory, and their SHA-256 is retained in the request and audit.

Jobs provides `cluster.fasta`, `members.tsv`, `clusters.tsv` and
`cluster_summary.tsv`. These record exact sequence IDs, normalised sequence
hashes, member counts, length summaries and the declared export source. A supplied
expected count must match. With no count, the audit says `COUNT_NOT_SUPPLIED`.
Matching a count does not independently prove global membership: this workflow
trusts the supplied export rather than comparing it with the global database.

Imported statistics describe **that export only**. Global size ranking, discovery
by an arbitrary member or species, and validation against global cluster
membership still need the relevant database/index or a provider offering those
queries. No remote DeepClust download API, SSH execution, global index or database
download is implied by this update.

## Validation

The new core functions and queue/CLI paths have unit tests. Regression tests use
the official `SEQID`/`CLUSTERID` schema, source-prefixed versioned IDs, malformed
and combined-mode FASTAs, duplicate IDs, missing centroids, count mismatches,
size bounds and a local input exceeding the browser limit. An AppTest exercises
the import form, and worker tests check import-to-analysis artifact integrity.
