# LoL-align in the E3 structural workflow

LoL-align is available through Foldseek as alignment type 3. It uses local structural
correspondence and a different score from TM-align. This integration supports a controlled
comparison with the existing methods, and an explicit replacement mode. Existing configurations
retain US-align and TM-align; enabling LoL-align requires a new configuration.

Primary method references:

- [Max Planck announcement and linked publication](https://www.mpinat.mpg.de/5343581/rn_2606)
- [Official Foldseek documentation: alignment modes and output fields](https://github.com/steineggerlab/foldseek#alignment-mode)
- [Tested Foldseek source revision](https://github.com/steineggerlab/foldseek/tree/463739e0014a1549a527de589102cde98f802f37)

## Update the three component installations

From the updated repository root on Dundee:

```bash
conda run --no-capture-output --name e3_ligandability \
    python -m pip install --no-deps --no-build-isolation --editable ./e3_ligandability_pipeline
conda run --no-capture-output --name e3_structural_alignment \
    python -m pip install --no-deps --no-build-isolation --editable ./e3_structural_alignment
conda run --no-capture-output --name e3_end_to_end_workflow \
    python -m pip install --no-deps --no-build-isolation --editable ./e3_end_to_end_workflow
```

Versions are ligandability 0.1.2, structural alignment 0.7.0 and orchestration 0.17.0.
The ligandability patch requires exact-accession F1 API selection by default and records an
unresolved reason before any download if that requirement cannot be established. An explicit
local input model is still supported by the existing local-input configuration.

## Install the tested Foldseek build

The optional installer targets Dundee's Linux x86_64 AVX2 nodes. It validates archive SHA-256,
source revision and LoL capability before publishing a new installation. It accepts a local
archive with `--archive` and never overwrites an installation.

```bash
bash e3_structural_alignment/scripts/install_foldseek_lolalign.sh \
    --prefix /cluster/gjb_lab/pthorpe001/2026_E3_protac/software/foldseek_lolalign_463739e
```

The tested revision is `463739e0014a1549a527de589102cde98f802f37`; the archive SHA-256 is
`f886374e29ebbf03849cd9c4c8929be00904856dd271627d8c3043607e2af95a`.
The official download URL is a rolling build: a later archive with different bytes is rejected.
An existing independently installed Foldseek can also be used by supplying its executable;
every LoL run checks its actual LoL capability and records its reported version.

## Prepare a comparison from the configuration of the intended source run

Use the actual source run's complete configuration to retain its inputs, evidence strategy,
group limit, gates and thresholds. Write the new YAML beside the source YAML so relative
resource paths retain their meaning. The preparer requires a different run name and refuses
to overwrite either YAML.

```bash
e3-workflow-prepare-lolalign \
    --source-config /absolute/path/to/current_run.cluster.yaml \
    --output-config /absolute/path/to/current_run_lolalign.cluster.yaml \
    --run-name current_run_lolalign_comparison \
    --mode alongside \
    --foldseek-executable /cluster/gjb_lab/pthorpe001/2026_E3_protac/software/foldseek_lolalign_463739e/bin/foldseek
```

The optional `--structure-group-limit 1972` sets the structural breadth explicitly. Without
it, the original limit is retained. Prepare the configuration first, review it, and then use
the ordinary workflow/controller submission route. Preparing the YAML submits no jobs.

| Preparation mode | US-align | TM-align | LoL-align |
|---|---|---|---|
| `alongside` | Enabled | Enabled | Enabled |
| `replace-tmalign` | Enabled | Disabled | Enabled |
| `lolalign-only` | Disabled | Disabled | Enabled |

The checked-in `grant_aligned_corrected_expression_all1972_lolalign_v0_17_0_20261027.cluster.yaml`
is a complete new campaign example derived from the retained corrected-expression v0.14.0
configuration. Its 1,972-group limit represents the full ranked candidate set, including
non-structural failures and missing evidence. It does not assert that 1,972 groups passed the
non-structural gates or reproduce the exact September v0.16.0 campaign configuration.

This is a full workflow configuration: its original upstream generation/reuse choices remain
explicit. For a completed campaign, inspect that campaign's actual configuration and reuse
strategy before submitting another full run. Existing pocket evidence is not invalidated by
the model-selection safeguard.

## Native workflow settings and direct component CLI

Both plant-only Stage 09b and human/plant extension tasks honour:

```yaml
analysis:
  structural_alignment:
    run_usalign: true
    run_tmalign: true
    run_lolalign: true
    foldseek_executable: /absolute/path/to/foldseek
    lolalign_multidomain: true
```

These are fields within a complete workflow YAML, not a standalone workflow configuration.
For the standalone human/plant extension, place the same method fields beneath
`human_plant_extension.structural_alignment` in a copied extension YAML and choose a new
extension `output_root`. Its `parent_workflow_config` remains the original immutable parent.
The extension records effective method settings in the task identity, so a change of method
cannot silently reuse an alignment cached under another method configuration.

The direct component exposes `--run-lolalign`, `--foldseek-executable` and
`--lolalign-single-domain`; existing `--skip-usalign` and `--skip-tmalign` options allow
replacement or LoL-only execution. At least one method must be enabled.

## Score and coordinate interpretation

- `alignment_scope`: `local` for LoL-align, `global` for the existing aligners, and
  `reference` for the explicitly synthetic self-reference rows.
- `lol_normalised_score`: Foldseek's LoL normalised score, read from its `evalue` output slot.
  This is not a statistical E-value.
- `lol_homology_probability`: Foldseek's estimated homology probability from `prob`.
- `tm_score_mobile_normalised` and `tm_score_reference_normalised`: geometric TM metrics
  computed by Foldseek from the LoL residue correspondence. These are not LoL scores and do
  not imply that the correspondence was obtained by the TM-align alignment algorithm.
- The global rigid transform is Foldseek's TM-score superposition for that correspondence.
  Foldseek moves target onto query, so this implementation supplies reference as query and
  mobile as target. A real-tool test checks a known rotation and translation in that direction.

Per-pair raw alignment TSV, command logs, transform and tool revision are retained with the
existing model checksums. Temporary Foldseek databases are removed. Each pair uses one Foldseek
thread; the component's existing `threads` setting limits concurrent pairs.
A successful local search returning no correspondence is recorded as `NO_ALIGNMENT_FOUND`;
its unmeasured scores remain null and it cannot supply a consensus pass. Executable failures,
ambiguous multi-hit output and malformed transforms remain errors. `aligned_accession_count`
counts the reference plus members assessed by every enabled method.

## Pocket decisions and comparison policy

The existing global-TM, pocket-overlap, centroid, residue-conservation and group-support
thresholds remain explicit and unchanged. No new arbitrary LoL-score cutoff is introduced.
When three methods are enabled, the existing strict consensus requires agreement from all
three. This can be more stringent than the previous two-method consensus. Per-method results
remain available in `structural_alignments` and `pocket_comparisons`, and in the labelled 3D
viewers, so disagreements can be inspected independently of the consensus.

For a fair method comparison, hold models, reference selection, pockets, residue mappings
and thresholds fixed. Compare per-method coverage, pocket support and disagreement cases
before deciding whether LoL-align should become the primary method. A local whole-protein
match alone does not establish conservation of the selected pocket.

## Validation

The tests cover strict selection, explicit legacy override, rejection before download, parser
and score semantics, missing/ambiguous results, non-finite values, improper transforms, tool
failure, configuration isolation, all-three-method consensus and pinned offline installation.

For the optional real-tool test, supply a supported single-chain reference model with at least
30 C-alpha atoms. The test generates a rotated/translated copy and also runs the LoL-only
structural pipeline; no network lookup is needed:

```bash
FOLDSEEK_EXE=/absolute/path/to/foldseek \
FOLDSEEK_REFERENCE_MODEL=/absolute/path/to/reference.pdb \
python -m pytest --quiet e3_structural_alignment/tests/test_lolalign.py
```

These checks establish software execution and coordinate handling. They do not constitute an
E3 biological benchmark or a completed LoL-align analysis of the 1,972-group campaign.
