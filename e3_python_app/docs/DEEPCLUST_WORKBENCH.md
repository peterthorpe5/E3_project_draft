# DeepClust workbench

From v0.23.0, open **🧬 DeepClust research → DeepClust results & FASTA**.
The same controls are available in **DeepClust workbench** and **3 · E3
orthology context → Protein research workbench**.

- **Prepare query FASTA** collects selected published HOG proteins or combines
  uploaded FASTA files. Download the FASTA and, for HOG members, the identifier
  mapping TSV to carry the source identities into Ken’s search app.
- **Import Parquet results** previews a selected external search export. If it
  contains amino-acid sequences, select the ID and sequence columns and,
  optionally, an exact cluster. Use the prepared FASTA in the workbench or
  download it. An export with hit identifiers alone can be viewed as a table.
  Request sequence FASTA separately for alignment or prediction.
- **JBrowse MSA**, **Protein feature browser** and **ESMFold & models** are direct
  E3 pages. They accept aligned FASTA and optional Newick, annotation TSV and
  its exact input FASTA, or a monomer PDB and its exact input FASTA, respectively.
  A reviewed species tree also needs the sequence-to-species TSV.
- For a different compute machine, use **Prepare files for another machine**
  with uploaded, pasted or prepared FASTA. The ZIP includes the exact input,
  parameters and commands for the installed research CLI. Open the returned
  files in the viewers. Each machine uses its own research profile.

The Parquet importer uses explicit column selection while Ken’s export and
API/CLI contract are being defined. The FASTA download is the current handoff.

## Built-in search and the Top-200 campaign

Open **Built-in DeepClust search** under **DeepClust results & FASTA** and select
**Show built-in search controls**. The original search and campaign are there.

1. Open **Top-200 cluster campaign**. The default is 200 published **primary
   evolutionary groups** in pre-structure rank order, including HOGs and
   orthogroup fallbacks. The number is editable (1–1,000).
2. Select the mounted-data worker or the operator-configured existing SSH
   connection. **Prepare complete Top-N E3 mapping inputs** reads the local E3
   resource only. Download the group and complete identifier/context inventories.
3. Queue mapping. A separate worker queries external membership in batches of
   at most 10,000 identifiers. Wait for completion in **Jobs**.
4. Review completed group statuses and global clusters ordered by published
   size. Select indexed global clusters and queue complete retrieval. The
   member estimate helps you choose a manageable first family.
5. In **Family analysis**, choose the completed retrieval and its cluster FASTA.
   Create stricter subclusters with editable identity, mutual coverage and
   E-value settings, or align a small family directly.
6. To align a subcluster, choose **Alignment and tree**, the completed
   subclustering job and its audited subcluster. Alignment is a separate job.
7. Inspect **Alignments and trees**, **Cluster comparisons** and **Protein
   features**. Complete verified downloads are under **Jobs**.

Project cluster IDs, HOG IDs and external DeepClust centroid IDs are distinct.
The audit retains exact relationships, one-to-many matches, unmatched inputs,
groups without identifiers and mapped clusters without retrieval indexes.
Mapping establishes recorded membership; it does not calculate a medoid or
establish experimental function. This route preserves the published primary-group
scope. It does not change upstream gates/ranks or select all secondary groups.

`campaign_groups.tsv` retains every requested group, including `NO_IDENTIFIERS`,
`UNMATCHED` and `PARTIAL`. `global_cluster_mapping.tsv` retains member/seed
source context. `global_clusters.tsv` is the complete size-ranked inventory.
Table previews are bounded and labelled; complete TSV downloads retain all rows.
Inputs exceeding 200,000 context rows or 50 MB per immutable snapshot fail
explicitly. Extraction never silently samples a chosen cluster.

## Configure the established denbi connection

Reuse the existing operator-managed SSH alias and non-interactive key
authentication. The app does not create accounts or store passwords. Install
**0.22.0+ on both ends** of an SSH exchange. Remote profile/executable paths
must be absolute paths on denbi; non-interactive SSH does not activate Conda.

| Deployment | Research TOML setup |
| --- | --- |
| App/worker on denbi, or using the existing read-only mount | Set `index`, `sequence_map`, `sequences` and optional reviewed `taxonomy`; select **Analysis worker with mounted data**. |
| Analysis worker retrieves selected data through SSH | Set `remote_host` to the established alias, `remote_executable` to its installed CLI's absolute path and `remote_config` to its remote TOML's absolute path; select **Existing SSH connection**. |

For the established mount under `/home/ubuntu/data/mounts/ken_deepclust`, check
the actual locations of `clust_index_RowGroup.parquet`, `SeqIdMapClustId.parquet`
and `joined_with_index_RowGroupFinal.parquet`. These databases are not included
or downloaded with the update. Use the
[example profile](../config/protein_research.example.toml), outside the repository,
and set `E3_RESEARCH_CONFIG` for the app and worker. Start the worker with the
same profile and writable workspace:

```bash
protein-research-workbench --config /absolute/path/research.toml doctor
protein-research-workbench --config /absolute/path/research.toml worker
```

The SSH route invokes the installed CLI's read-only `export-deepclust
--request-stdin` exchange. IDs travel in bounded JSON on stdin, never as shell
arguments. Binary stdout contains the selected results; logs use stderr. The
receiver verifies request hashes, inventories, byte counts and file checksums
before publishing artifacts. SSH logs remain available for diagnostics. The
default response budget is 2 GB; exceeding configured resource/extraction limits
fails explicitly. Raising limits is an operator choice. Source Parquet stays
immutable and the entire global database is never copied.

**Where analyses run.** Queued DIAMOND, MAFFT and annotation jobs run on the
research worker's machine. In JBrowse, **Run MAFFT on app machine** starts a
one-shot worker on the host running Streamlit. For large families, run the
app and worker on denbi with its mounted data, installed tools and shared
workspace. Existing deployment and tunnel instructions in
[PROTEIN_RESEARCH.md](../PROTEIN_RESEARCH.md) still apply.

## Subclusters, summaries and heatmaps

Native DIAMOND assignments are audited by exact member-to-assigned-centroid
realignment. Identity, coverage of **both** proteins, E-value and the recorded
bit-score criterion must pass; failures remain singletons. This does not require
every within-subcluster pair to pass. MAFFT retains selected IDs/amino acids.
Large MSA requests need a smaller audited subcluster or explicit deterministic
sampling; sampling is never enabled automatically.

**Cluster comparisons** shows sortable size/length/taxonomy summaries and a
size chart of the largest 50 preview rows. Species counts follow retrieval and
subclustering ancestry. The extraction worker needs reviewed taxonomy containing
`sequence_id`, `species`, positive `taxon_id` and, when present,
`mapping_status=REVIEWED`. Conflicting assignments are excluded. Missing
assignments remain `UNCLASSIFIED` and appear in classification coverage; they
never become an invented species. No billions-scale taxonomy lookup is run.

| Comparison | Definition |
| --- | --- |
| Protein identity heatmap | Identical canonical residues / aligned positions where both residues are canonical. Gaps/unknowns are excluded; no overlap remains undefined. |
| Species overlap heatmap | Intersection / union of unique reviewed taxon-ID sets. Abundance is separate. Missing reviewed taxa give undefined comparisons. |
| Two/three-set species Venn | Disjoint unique-taxon counts in explicitly selected clusters. Circle areas are illustrative, not proportional. |
| Display hierarchy | SciPy average linkage on `1 − similarity`, with optimal leaf ordering. Missing distances disable hierarchy rather than being replaced by zero. |

Comparisons allow at most 1,000 explicitly selected rows; proteins also have a
25-million-cell input bound. The first 200 MSA rows are the visible default
selection and can be changed. Complete similarity/denominator matrices,
hierarchy merges, display order, classification coverage and count TSVs are
downloadable. A heatmap hierarchy is not a species phylogeny.

## JBrowse MSA with a reviewed species tree

The real, locally bundled **react-msaview 9.8.0** engine used by the GMOD
JBrowse MSA plugin supplies the viewer. Open **JBrowse MSA** from either
**Candidate discovery** or **DeepClust research**.

1. Choose **Align a HOG** and search for a HOG ID. The app shows which
   members have unaligned protein sequences in the loaded release.
2. Use all available members or choose proteins. Download their FASTA and
   ID mapping or set the reference, sampling and tree options.
3. Choose **Run MAFFT on this Mac** when running Streamlit on a Mac with MAFFT
   installed. On Linux the button is **Run MAFFT on app machine**. You can
   also queue the job for a worker with access to the same workspace or
   download the job files for another machine.
4. Refresh the alignment status and choose **Open completed alignment**.
   FastTree is optional and requires at least three selected proteins.
5. In the **JBrowse MSA** viewer, choose **Calculate heatmap** in the panel
   beside the alignment. The app calculates pairwise identity on its host.
   The first 200 aligned rows are selected by default when they fit the
   comparison limits. Adjust the selection and download the identity and
   comparable-residue count matrices as TSV files.
6. Open **Auspice tree** to inspect the saved protein tree. If the alignment
   has no tree and contains at least three proteins, choose **Infer tree from
   this alignment**. FastTree runs on the app machine using the saved
   alignment. The tree is then available in JBrowse and as Newick and Auspice
   JSON downloads.
7. Open **Statistics** and choose **Metric definitions** beside the position
   or protein table for the calculation and denominator of each metric.

**Subcluster proteins**, **Annotate proteins** and **Predict models** open
the corresponding workbench forms with the protein input selected. From
**Align a HOG**, these buttons use the selected HOG sequences. From a
completed job, they use the exact unaligned proteins that entered MAFFT,
including any sampling applied to that job. Review the method settings in the
destination before starting work.

**Published HOG alignment** opens alignments exported with the plant pocket
review. **Try an example** opens six synthetic sequences. **Upload alignment
files** accepts a previously aligned protein FASTA and an optional tree.

Protein data is not sent to a CDN.
Choose the inferred FastTree protein tree or **Reviewed species tree**. Upload
a Newick backbone, or set `species_tree` in the research profile.

Species tips must match reviewed species labels or taxon IDs exactly.
Alignment jobs inherit per-protein taxonomy from retrieval, including SSH
retrieval. An optional reviewed mapping TSV can supply `sequence_id`, `species`,
`taxon_id`, with one row per protein. Every aligned protein needs one
unambiguous species-tip match. Unused species are pruned; multiple proteins
from one species form a zero-length display polytomy. This does not infer
paralogue relationships. Download the mapping audit and display Newick. Missing
or ambiguous mappings prevent a purported species-tree display.

## Nightingale, annotation and ESMFold

**Protein features / Protein feature browser** works in both contexts. Normal
E3 resources can show recorded `domain_hits` for an exact published accession
and group/species context. Those hits have the recorded protein length, but no
sequence checksum: Nightingale shows their original length/coordinate axis
without inventing amino acids or mapping onto a current sequence. Evidence TSV
and standalone viewer HTML are downloadable.
From the selected record, open JBrowse for its HOG or ESMFold for that
protein. ESMFold can use the exact HOG/species sequence from the release,
when available. To run a prediction elsewhere, prepare the job files and
open the returned PDB in **ESMFold & models**.

For new annotation select a completed family/FASTA, upload FASTA or choose
**Paste FASTA**. Restrict to exact IDs when needed. Shared annotation/model
forms are also available directly under **Annotations** and **Models**.

- **InterProScan:** installed local tool/databases, or EMBL-EBI REST with
  explicit sequence submission. Enter the contact email in the form or use
  the worker profile's default. Files prepared for another machine use that
  worker's configured address. Up to 25 selected remote proteins are sent
  sequentially, **one protein per service request**. Service IDs/input hashes
  are retained. Positional Nightingale tracks are verified against their exact
  submitted amino-acid sequence hashes.
- **eggNOG-mapper:** installed executable and matching database, with editable
  taxonomic scope/target. Eukaryota/2759 remains the default. Use a compatible
  tool/database installation; mapper 3/database 7 is a separate deployment
  choice. Whole-protein functional transfer does not invent positional domains.
  No undocumented public eggNOG submission API is assumed.
- **ESMFold:** existing Atlas, configured dedicated endpoint and installed local
  inference routes are shared here and under Models. Atlas is capped at 400
  residues in the app. Remote submission is explicit. Local inference needs
  optional dependencies and model weights. Per-protein failures remain visible.

The update does not automatically submit sequences, install biological databases
or start a large job. All these annotations/models are computational predictions.

## Install and validate

Install the new SciPy dependency; do not use `--no-deps` alone. Stop the app and
worker before updating, back up the code, apply the single release patch,
reinstall and restart. The package installer makes a Git-history backup and
applies the update on `main` without creating another branch. No resource DuckDB
rebuild or upstream HPC rerun is needed.

Run `./run_tests.sh` for the maintained suite. Browser checks cover all bundled
viewers, recorded-length Nightingale features, synchronized zoom and JBrowse
species-tree display. The real-tool synthetic check is reproducible:

```bash
python e3_python_app/scripts/validate_cluster_campaign.py \
  --output /new/empty/path/cluster_smoke \
  --diamond /installed/bin/diamond \
  --mafft /installed/bin/mafft \
  --fasttree /installed/bin/FastTree
```

It checks synthetic mapping/retrieval, two clustering thresholds, taxonomy
inheritance, MAFFT/FastTree, both comparisons and reviewed species display.
It does not test live denbi authentication or live prediction-service submissions.

## Primary references

- Nightingale paper: https://academic.oup.com/bioinformaticsadvances/article/3/1/vbad064/7178007
- Nightingale documentation: https://ebi-webcomponents.github.io/nightingale/?path=/story/introduction--page
- GMOD JBrowse MSA plugin: https://github.com/GMOD/jbrowse-plugin-msaview
- DIAMOND clustering: https://github.com/bbuchfink/diamond/wiki/Clustering
- EBI services: https://www.ebi.ac.uk/jdispatcher/docs/webservices/
- InterPro limits: https://interpro-documentation.readthedocs.io/en/latest/faq.html
- eggNOG-mapper: https://github.com/eggnogdb/eggnog-mapper
- ESMFold: https://github.com/facebookresearch/esm
