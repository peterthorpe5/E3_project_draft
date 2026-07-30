# ARIA E3 top-50 pocket-review runbook

## Purpose

The v0.3.0 report is a post-run manual-review resource. It uses the completed
v0.11.0 Stage 09, 09b and 10 authorities to create:

- a best-to-worst top-50 index;
- one offline HTML page per evolutionary group;
- rotatable member-protein C-alpha traces with strict and alternative pockets;
- the published MAFFT alignment annotated with exact pocket residues;
- strict and top-k structural evidence tables;
- a TSV worksheet for the project leads' final up-to-ten selection;
- a strict-versus-sensitivity evidence matrix;
- an exact pocket-residue coordinate audit; and
- a protein-model checksum inventory.

It does not change the immutable strict 50-group baseline, rerun pocket
prediction, recompute structural alignment or change the Stage 10 order.

## Copying the extension into GitHub on the Mac

```bash
OVERLAY_ZIP="/Users/PThorpe001/Downloads/E3_project_draft_v0_11_0_pocket_review_extension_v0_3_0.zip"
REPO="/Users/PThorpe001/github_repos/E3_project_draft"
OVERLAY_DIR="$(mktemp -d /tmp/e3_pocket_review_v0_3_0.XXXXXX)"

cd "${REPO}"
git switch main
git pull --ff-only
git status --short

unzip -q "${OVERLAY_ZIP}" -d "${OVERLAY_DIR}"

rsync -av \
    "${OVERLAY_DIR}/E3_project_draft_v0_11_0_pocket_review_extension_v0_3_0/" \
    "${REPO}/"

git diff --check
git status --short

git add e3_structural_alignment
git commit -m "Add v0.3.0 top-50 pocket review extension"
git push origin main
```

## Installation

Run on the cluster login node after copying or pulling v0.3.0:

```bash
BASE="/gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac"
REPO="${BASE}/E3_project_draft"
PACKAGE_ROOT="${REPO}/e3_structural_alignment"

cd "${REPO}"
git switch main
git pull --ff-only
git status --short

cd "${PACKAGE_ROOT}"

conda run --name e3_structural_alignment \
    python -m pip install \
    --no-deps \
    --force-reinstall \
    --editable "${PACKAGE_ROOT}"

conda run --name e3_structural_alignment \
    e3-pocket-review --version

conda run --name e3_structural_alignment \
    bash "${PACKAGE_ROOT}/run_tests.sh"
```

Expected report command version:

```text
e3-pocket-review 0.3.0
```

## Submission

Do not submit until the v0.11.0 run has completed through Stage 10.

```bash
BASE="/gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac"
REPO="${BASE}/E3_project_draft"
PACKAGE_ROOT="${REPO}/e3_structural_alignment"

RUN_ROOT="${BASE}/analysis/e3_end_to_end_runs/grant_aligned_structural_sensitivity_top100_v0_11_0_20260729"
OUTPUT_DIR="${RUN_ROOT}/pocket_review_top50_v0_3_0"

cd "${PACKAGE_ROOT}"

./scripts/submit_e3_pocket_review_slurm.sh \
    --run-root "${RUN_ROOT}" \
    --output-dir "${OUTPUT_DIR}" \
    --account barton \
    --partition barton \
    --review-limit 50 \
    --member-pocket-top-k 5 \
    --resume
```

The default Slurm request is four CPUs, 16 GB and four hours. It can be changed
with named options. The submitter rejects wall times above five days.

## Monitoring

```bash
squeue -u "${USER}" \
    --format="%.18i %.40j %.10T %.12M %R"
```

```bash
tail -F "${OUTPUT_DIR}".slurm.*.log
```

## Completion checks

```bash
test -s "${OUTPUT_DIR}/index.html"
test -s "${OUTPUT_DIR}/evidence_matrix.html"
test -s "${OUTPUT_DIR}/review_decisions_template.tsv"
test -s "${OUTPUT_DIR}/tables/pocket_residue_annotations.tsv"
test -s "${OUTPUT_DIR}/tables/protein_model_inventory.tsv"
test -s "${OUTPUT_DIR}/qc/pocket_review_validation.tsv"
test -s "${OUTPUT_DIR}/provenance/run_manifest.json"

find "${OUTPUT_DIR}/groups" \
    -maxdepth 1 \
    -type f \
    -name '*.html' \
    | wc -l
```

For the requested run, the final command should report 50 pages.

## Copying the report to the Mac

Run on the Mac:

```bash
MAC_OUTPUT="/Users/PThorpe001/Downloads/ARIA_E3_pocket_review_top50_v0_3_0"

mkdir -p "${MAC_OUTPUT}"

rsync -av --progress \
    -e ssh \
    "pthorpe001@login.compute.dundee.ac.uk:/gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/analysis/e3_end_to_end_runs/grant_aligned_structural_sensitivity_top100_v0_11_0_20260729/pocket_review_top50_v0_3_0/" \
    "${MAC_OUTPUT}/"

open "${MAC_OUTPUT}/index.html"
```

The whole output directory must be copied because the index links to the 50
group pages. Each page itself is standalone and has no network dependency.

## Manual selection

Use `review_decisions_template.tsv` to record:

- reviewer;
- decision;
- final priority;
- rationale; and
- review date.

The worksheet is already sorted by the authoritative final evolutionary rank.
Project leads may select up to ten candidates. Fewer than ten should be retained
if fewer are scientifically defensible.

## Interpretation limits

- Rank-one pockets remain the strict primary result.
- Ranks two to five are sensitivity evidence only.
- The C-alpha trace is a visual location aid, not an atomistic surface.
- Pocket prediction and structural conservation do not prove ligand binding.
- Identifying an E3 pocket addresses only the E3-recruiting half of a future
  PROTAC; target engagement, linker geometry, ternary-complex formation,
  ubiquitination and degradation remain unvalidated.
