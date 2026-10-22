# Protein research workbench — v0.20.0

## Using the workbench

Open **Start here** to choose your input. In the full E3 app, the recommended
route is **Start from E3 groups**. The standalone workbench accepts protein IDs,
known global centroids, exported clusters and unaligned protein FASTA. E3 remains
an optional adapter; the analysis engine and general guidance are project-independent.

The core workflow is **Discover → Family analysis → Alignments and trees**.
Use **Jobs** throughout to track progress and download complete files. Models
and Annotations are optional and can start directly from FASTA. Each page has
an aim, expandable instructions, native question-mark help beside its controls,
and an explicit next step. **Help & glossary** includes FASTA examples,
identifier definitions, troubleshooting and a downloadable user guide.

Start with one family. E3 preparation collects source/member IDs and linked
seeds; it does not calculate a medoid. Exact mapping finds global membership,
then retrieval collects sequences. Select mapped/ranked clusters and use the
handoff button to populate retrieval without copying IDs. From a completed
retrieval/import job, **Analyse this family** carries its FASTA into analysis.
From a completed subclustering job, choose its audited subcluster before aligning.
These handoffs select inputs; they never submit a second job automatically.

Job choices show their task, UTC time and job ID. Alignment pages lead with
protein/position counts and gaps. Raw JSON, parameters and logs are available
in technical expanders. Optional provider controls show missing setup before
submission, and external sequence submission is still explicit. Configuration
checks do not establish remote service availability or a live worker heartbeat.

This adds a generic protein-family research engine inside **e3_python_app**. It is
available in stage 3 as **Protein research workbench**, and independently through
`protein-research-workbench serve`. The generic engine has no E3 species, family,
ranking or resource assumptions. Only `research/e3_adapter.py` selects E3 HOGs,
ranked discovery clusters, original representatives and inherited seed accessions.
The existing E3 resource remains read-only; new results live in a separate workspace.

## What is implemented

| Workflow | Behaviour |
| --- | --- |
| Global discovery | Size-ranked DeepClust catalogue; exact centroid IDs; clusters containing submitted protein IDs; any/all requested taxon IDs; any reviewed species. |
| E3 linking | Top 200 (configurable) pre-structure HOGs or computationally ranked discovery clusters, or exact local IDs; member/source accessions and inherited seeds retain their E3 context. Exact matches, declared aliases, one-to-many and unmatched mappings are exported. Local E3 cluster IDs are never treated as global DeepClust centroids. |
| Complete retrieval | Reads only indexed physical Parquet row groups, including clusters spanning several groups. Filters by global centroid, rejects duplicate sequence IDs and reconciles every count with NMEMBER. Complete per-cluster FASTA, member audit, length statistics and reviewed species counts. |
| Selected export import | Imports one per-cluster FASTA from the upstream retrieval tool without a local global database. Preserves exact source IDs, checks the centroid and supplied member count, records source/sequence hashes and publishes export-scoped statistics. Large local exports use a streaming CLI snapshot. |
| Stricter families | Native DIAMOND DeepClust with exact identity/mutual coverage controls, followed by exact representative-to-member realignment. Both coverages, E-value and bitscore >20 are audited. Failed/missing assignments survive as singleton subclusters. |
| Alignments | MAFFT, per-column gaps/consensus/entropy, reference-to-member identity/overlap/raw BLOSUM62 statistics. Full family or explicit deterministic sampling with the reference retained; selections are audited. |
| Viewers | Locally bundled JBrowse MSA (alignment plus inferred tree), Alignment Viewer 2 (BLOSUM62-to-query sorting), and Nightingale (sequence/domain coordinates). Standalone downloadable alignment HTML works without a CDN. |
| Phylogeny | FastTree WAG+gamma Newick and Auspice v2 JSON, staged for a self-hosted Auspice service and embedded when configured. Branches are divergence; dates and ancestral sequences are not invented. |
| Structures | Explicit Atlas, deployed Hugging Face/custom endpoint or local ESMFold routes. Exact sequence validation, content-addressed model reuse, per-input failures, PDB and residue downloads, interactive C-alpha geometry and confidence profiles. |
| Annotation | Local InterProScan, explicit remote EMBL-EBI InterProScan, or local eggNOG-mapper with configurable scope (default Eukaryota/2759). Positional signatures appear in Nightingale. Annotation/model overlays require the same sequence SHA-256. No-hit inputs remain explicit. |
| Operations | Durable SQLite queue, transactional worker claims, queued cancellation, bounded previews, provenance/logs, SHA-256 artifact validation and portable CLI. Heavy work executes outside Streamlit. |

## 1. Install into the E3 app environment

From the repository root, after applying the patch:

```bash
python -m pip install -e 'e3_python_app[dev]'
conda install -c conda-forge -c bioconda 'diamond>=2.2.1' mafft fasttree
```

The Python package includes the built viewer assets. Node is **not** required by
the E3 app or generic UI. DIAMOND 2.2.8, MAFFT 7.526 and FastTree 2.2.0 were used
for a real small protein-family smoke run in the development environment. Provider
and annotation adapters are tested with deterministic fixtures; no real GPU model
or external sequence submission was run during patch development.

Local InterProScan and eggNOG require their separately installed executables and
matching databases. Install these in their supported environments and configure
absolute wrapper/executable paths if they are outside the app environment. The
worker invokes shell-free argv lists and records the tool versions and commands.

For optional local folding only:

```bash
python -m pip install -e 'e3_python_app[folding]'
```

The pinned Hugging Face checkpoint is downloaded on the first explicit local
folding job. Plan model storage and sufficient CPU/GPU memory; installing the app
itself does not download model weights. CUDA is used when available, otherwise CPU.

## 2. Configure the DeepClust release and a writable workspace

**For selected exports without a local global database, start with
[DEEPCLUST_EXCHANGE.md](DEEPCLUST_EXCHANGE.md).** It explains exact centroid naming,
the upstream extraction command for a database holder, rsync and the app's import
route. Cloning the upstream repository does not supply its database. The setup
below is for operators who already have or deliberately install the global files.

Copy `config/protein_research.example.toml` outside the checkout and edit it. Use
absolute paths; the TOML parser does not expand shell variables such as `$HOME`.
`~` is accepted for workspace/source paths. Command names must be executable names
on PATH or absolute paths. UI and worker must use the same profile and workspace.

The official release is a large multipart download, **not a per-cluster REST
service**. Download/reassemble it according to the official instructions, or point
to an existing shared installation. The published compressed release is about
1.9 TB and can expand to about 5 TB; this patch does not download it automatically.
Use an immutable versioned data directory and retain the official checksums.

Required files and accepted canonical schemas:

| Setting | Published/normalised columns |
| --- | --- |
| index | `CLUSTER`, `NMEMBER`, `RowStart`, `RowGroup`; aliases `cluster_id`, `member_count`, `row_start`, `row_groups` are accepted. |
| sequences | `f0` = exact sequence ID; `f1` = protein sequence; `f2` = global centroid. Normalised sequence_id/protein_sequence/cluster_id names are also supported. |
| sequence_map | Exact sequence ID to global centroid. Official `SEQID/CLUSTERID`, `f0/f1` and explicit SeqID/ClustID-style aliases are supported. |
| identifier_bridge | Optional `input_id`, `sequence_id`. Only use an audited bridge; no implicit orthology-based equivalence. |
| taxonomy | `sequence_id`, `species`, positive numeric `taxon_id`. Optional `mapping_status` is filtered to REVIEWED. If omitted, the operator declares the entire table reviewed. Conflicting sequence/taxon mappings are rejected during taxonomy-index creation and excluded from tip metadata. |
| cluster_taxonomy | Worker-produced `cluster_id`, `taxon_id`, `species`, `annotated_member_count`. |

The official row-group catalogue contains clusters with at least three members.
Sequence-map matches outside it are reported as MAPPED_WITHOUT_ROW_GROUP_INDEX;
indexed extraction refuses them. It never manufactures missing sequences. Species
filters use exact reviewed taxon IDs, not inferred lineages or guessed accession
names. Unknown species remain unclassified. A precomputed cluster/species index is
needed for these filters: queue `taxonomy_index`, then put its output path into the
profile and restart/reload. This index join may be a large one-time HPC operation.

Sequence-map resolution over the full Parquet release may require a substantial
scan. Run it as a queued worker job close to the data; a small web preview does not
imply a small dataset. A reviewed project-specific sequence map/bridge can be used
when only a subset is installed, provided its scope is made explicit. Source file
paths, sizes and modification times are recorded; multi-terabyte sources are not
rehashed for every job. Selected output artifacts receive full content hashes.

```bash
protein-research-workbench --config /absolute/path/research.toml doctor
protein-research-workbench --config /absolute/path/research.toml worker
```

Keep the second command running in a separate terminal, service or HPC job. No
scientific work starts simply because a page is opened. `worker --once` processes
at most one task and exits; `worker --job-id ID` selects an exact queued task.
`worker --max-jobs 1` waits for one task, executes it and exits. Multiple workers
claim different jobs transactionally. Size jobs so each worker's thread/memory
settings match its scheduler allocation; memory_gb bounds DuckDB/DIAMOND working
memory, while MAFFT/model memory also depends on input dimensions and hardware.

For Slurm, export RESEARCH_ENV_PREFIX and E3_RESEARCH_CONFIG and submit
`scripts/research_worker.slurm`. Review account/partition/resources for the target
cluster; the example uses account barton and partition general. Keep SQLite on a
shared filesystem with reliable POSIX locking, or use one queue/workspace per
worker group. Temporary scientific files use cluster TMPDIR when supplied.
The web process and workers need trusted access to the same sidecar. Use private
filesystem permissions; this queue is intended for a trusted research team, not an
untrusted multi-tenant service.

## 3. Open the workbench

Add this option to the **existing E3** launch command:

```bash
e3-python-app --resource-run-dir /absolute/path/to/e3_resource \
    --research-config /absolute/path/research.toml --host 127.0.0.1 --port 8501
```

Keep your existing resource option (`--resource-duckdb`, `--resource-parquet` or
`--resource-run-dir`) and companion options. The old handover command for the
separate OrthoFinder results application does not launch this E3 workbench.
The profile may alternatively be supplied through `E3_RESEARCH_CONFIG`.

For a generic session with no E3 resource:

```bash
protein-research-workbench --config /absolute/path/research.toml serve --port 8503
```

Generic FASTA analysis works with only workspace/tool settings; DeepClust sources
are required only for global catalogue operations. Bind locally and use your
existing authenticated reverse proxy for a shared deployment.

A typical sequence of actions is:

1. Discover → E3 ranked groups → select HOGs or discovery clusters → prepare
   inputs → queue exact global mapping. Review every mapped/unmatched/multiple
   result and download the full mapping from Jobs.
2. Paste the selected **global** centroid IDs into complete cluster retrieval.
   Review Jobs → clusters/length/species summaries and the complete FASTAs.
3. Family analysis → select that FASTA → Stricter subclusters. Start with 70%
   identity, 80% mutual coverage and E≤1e-10, then choose thresholds appropriate
   to the family. These defaults are exploratory settings, not universal criteria.
4. Select the completed subcluster job FASTA, copy an audited subcluster_id into
   Alignment and tree, and select the reference. Align all selected members or
   explicitly request a deterministic sample. No oversized cluster is silently
   truncated. There is no all-pairs similarity guarantee: exact thresholds are
   audited against assigned representatives.
5. Open Alignments and trees → JBrowse MSA / Alignment Viewer 2 / Statistics;
   open Auspice once its service is configured.
6. Optionally select exact protein IDs for model/annotation jobs. Blank ID lists
   select the complete input, subject to the stated job bounds. Review failures,
   no-hit evidence and provenance before interpreting downstream results.

Generic CLI submission uses the same contracts. Scientific controls are a JSON
object in a file, avoiding shell interpolation of protein data:

```bash
protein-research-workbench --config /absolute/path/research.toml submit \
    --operation subcluster --fasta /absolute/path/family.fasta \
    --parameters /absolute/path/subcluster-controls.json
protein-research-workbench --config /absolute/path/research.toml jobs
protein-research-workbench --config /absolute/path/research.toml cancel --job-id QUEUED_ID
```

Example controls: `{"identity":70,"mutual_coverage":80,"evalue":1e-10}`. For input
from a completed job, use `{"source_job":"ID","source_artifact":"NAME.fasta"}`
with the other analysis controls instead of uploading. Resolve uses an identifiers
array; retrieval uses a cluster_ids array. A batch model/annotation request accepts
sequence_ids; alignment accepts subcluster_id/reference_id, optional sample_size
with allow_sampling=true, and infer_tree. Jobs are independent: the next stage
starts only when its source artifacts have completed and passed checksum checks.

## 4. Auspice service

Auspice is a separate web application. The patch writes real v2 datasets and
embeds your configured service; it does not substitute a static tree drawing.
For the currently supported Auspice 3.1.0 service, use Node 24 or 26 on its host:

```bash
npm install --prefix /absolute/path/auspice-service auspice@3.1.0
/absolute/path/auspice-service/node_modules/.bin/auspice view \
    --datasetDir /absolute/path/protein_research/datasets \
    --host 127.0.0.1 --port 4000
```

Set `auspice_url="http://127.0.0.1:4000"` for a local browser, or the browser-visible
reverse-proxy URL for a server deployment. Dataset names are job IDs. HTTPS app
pages need an HTTPS Auspice URL; the proxy must allow the intended iframe embedding.
The service supplies Auspice interactions, including its supported focus/layout
controls; it does not derive ancestral states or dates from these protein trees.
Download auspice.json and tree.nwk from Jobs for other tools. The root is a layout
root and does not assert an ancestral protein.

## 5. ESMFold and annotation routes

**ESM Atlas:** explicit remote submission to the documented foldSequence PDB
endpoint. This adapter conservatively caps that route at 400 residues; 400 is not
an intrinsic ESMFold model limit. The service may be unavailable or rate-limited;
failed attempts remain visible, and no sequence is truncated to make it fit.

**Hugging Face/custom endpoint:** configure a deployed HTTPS endpoint that accepts
`{"inputs":"PROTEIN_SEQUENCE"}` and returns raw PDB text or `{"pdb":"..."}`.
Put a bearer token in the configured environment variable on the **worker**. Tokens
are never form fields or job parameters. Redirects are rejected before forwarding
credentials. The Hugging Face facebook/esmfold_v1 model page currently has no public
Inference Provider; this adapter does not assume that a generic serverless API
will execute it. Pin the endpoint's model version operationally; remote responses
do not prove which weights a third-party endpoint ran.

**Local:** runs the pinned Transformers ESMFold checkpoint, without submitting the
protein to a prediction service. The first model download contacts Hugging Face.
Transformers 4.x fractional lDDT is converted to 0–100 B-factors before export.
Model results are keyed by sequence/provider/revision/endpoint. Locks prevent
concurrent duplicate inference. A stale lock after a killed worker needs an
operator to confirm that worker has stopped before removing that exact lock.
Reported confidence is predictive evidence; the app displays a C-alpha trace and
per-residue confidence, and downloads the full predicted PDB for atomic inspection.
It does not automatically feed predictions into the existing authoritative E3
pocket/ligandability rankings.

**InterProScan:** local installation or explicit EMBL-EBI submission (email in
profile, at most 25 proteins remotely). Service IDs are retained for manual polling
recovery. TSV input MD5, protein lengths and domain coordinates are validated.

**eggNOG:** local installation/database. The default scope Eukaryota and target
2759 are visible and configurable. Use a database/version supporting the requested
scope. Its annotations are orthology-based transfer; InterPro signatures and
ESMFold predictions are also computational evidence. These routes are not claims
of experimentally established, genuinely de novo protein function. No-hit inputs
are not assigned fabricated labels. Whole-protein eggNOG annotations are shown in
tables; only positional signature evidence is placed on Nightingale tracks.

## Outputs, recovery and limits

Completed jobs contain a manifest with SHA-256 and byte sizes for every published
artifact, scientific controls, runtime versions and source file fingerprints.
Command argv and tool stderr/version logs are retained and published where present.
Inputs/selection audits preserve exact IDs; terminal FASTA stops are normalised
and DeepClust retrieval records their removal. Unknown residues are excluded from
canonical identity/entropy denominators. BLOSUM62 statistics are raw sums over
comparable aligned residues, without gap penalties or search-significance claims.
Column and reference protein coordinates are one-based; gaps have no reference
coordinate. Species summaries report unclassified members explicitly.

Web downloads are limited to 25 MB per artifact; larger files remain complete in
the worker workspace and can be copied with rsync. Preview tables show at most
10,000 rows; the full checksummed TSV/Parquet is the authoritative output. The
recent-job selector lists at most 200 jobs; older jobs remain on disk and are
available by exact ID through the queue/artifact APIs. Job inputs are never deleted
automatically, and failure diagnostics/partial outputs remain on disk.

Queued jobs can be cancelled. Ctrl-C marks an executing job failed, kills its
active scientific process group and stops the worker. A hard OS/Slurm kill can
leave RUNNING state/partial files; inspect the worker and scheduler before making
a new job. This release deliberately does not automatically retry costly or
remote sequence submissions. To recover a remote InterPro result, poll the
retained service job ID; do not assume that a timeout means the service did not
accept the submission. Protect input/output workspaces according to the sensitivity
of the sequences used.

## Development and validation

```bash
cd e3_python_app
python -m pytest tests -q
coverage run -m pytest tests -q
coverage report
pycodestyle --max-line-length 100 src tests
pydocstyle --convention google src/e3app
```

The project uses Google-style function docstrings and its existing 100-character
PEP8 line limit. Core and adapter functions have unit tests, including provider
mocks, schema/count mismatch tests, concurrency and integrity tests. Imperative
Streamlit entry/UI modules follow the existing UI coverage exclusion and have
separate AppTest navigation/submission/result integration tests.

To rebuild bundled viewers (not needed to run the app):

```bash
cd frontend
npm ci --legacy-peer-deps --ignore-scripts
npm test
npm run build
```

The lockfile pins dependencies, the JBrowse prebuilt bundle is SHA-256 checked,
and checksums/third-party notices ship with the Python package. Browsers receive
local bundles and the selected protein data; the viewers need no CDN script.
For browser smoke tests, generate documents and run the provided frontend browser
smoke script with Playwright/Chromium installed. Test data must be public/synthetic.

## Primary references

- DeepClust release and retrieval: https://objectstore.hpccloud.mpcdf.mpg.de/deepclust/index.html
  and https://github.com/drostlab/deepclust_dataretrieval
- DIAMOND clustering and realignment: https://github.com/bbuchfink/diamond/wiki/Clustering
- Nightingale: https://github.com/ebi-webcomponents/nightingale and
  https://academic.oup.com/bioinformaticsadvances/article/3/1/vbad064/7178007
- JBrowse MSA: https://github.com/GMOD/react-msaview and https://gmod.org/JBrowseMSA/
- Alignment Viewer 2: https://github.com/sanderlab/AlignmentViewer2.0
- Auspice: https://github.com/nextstrain/auspice and
  https://nextstrain.org/blog/2026-03-12-auspice-updates
- ESMFold/Atlas: https://github.com/facebookresearch/esm,
  https://esmatlas.com/resources?action=fold and https://huggingface.co/facebook/esmfold_v1
- InterProScan: https://www.ebi.ac.uk/Tools/services/rest/iprscan5
- eggNOG-mapper: https://github.com/eggnogdb/eggnog-mapper
