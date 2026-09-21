# Frozen benchmark protocol

## Question and primary endpoint

The primary endpoint is the paired percentage change in wall time for
`pairwise_pipeline` (clustering plus representative/member realignment) versus
the DIAMOND 2.2.3 exact DeepClust baseline:

`100 × (baseline seconds - candidate seconds) / baseline seconds`.

The success target is a mean paired speed-up of at least 10%, subject to the
scientific guardrails below. Report the 95% paired bootstrap interval, but do
not replace the predeclared mean-based rule after seeing the result.

## Fixed inputs and controls

- Use the same checksum-verified prepared FASTA for every case.
- Require 25,821,204 sequences and 7,341,469,958 residues for the supplied
  full-1KP-plus production template.
- Use 32 threads and a 220G DIAMOND memory limit in one 256G Slurm allocation.
- Run cases sequentially and use an isolated temporary directory for every
  case/repeat.
- Run three repeats per case. Repeat number is the pairing unit.
- Keep identity, coverage, e-value, masking and composition-statistics values
  fixed unless that parameter defines the named comparison.
- Reject executable version drift during preflight.
- Do not reuse a database, membership output or DIAMOND temporary state across
  timed repeats.

The matrix order is fixed in the YAML. If filesystem caching is a concern,
perform a separate, predeclared order-sensitivity experiment; do not reorder
or delete inconvenient production observations after inspecting them.

## Timed stages

| Stage | Definition |
|---|---|
| `makedb` | fresh database construction from the prepared FASTA |
| `cluster` | `deepclust` or `linclust` membership generation |
| `realign` | exact representative/member realignment when enabled |
| `pairwise_pipeline` | `cluster + realign` |
| `total_pipeline` | `makedb + cluster + realign` |

Wall time is primary. CPU seconds, mean CPU equivalents, peak process-tree RSS,
read/write bytes and maximum observed processes diagnose why a case differs.

## Scientific guardrails

Memberships are joined by member identifier. A case is invalid when a member
is duplicated, missing or added relative to the baseline.

Global concordance is measured with pairwise precision, recall, F1 and adjusted
Rand index. Pairwise F1 must be at least 0.99. This tests whether pairs of
proteins remain together, independent of representative names.

When a controlled `sequence_id` sentinel TSV is configured, the union of all
members in sentinel-containing clusters is compared with the baseline.
Sentinel-neighbourhood recall must be at least 0.99; Jaccard is reported as a
secondary measure. A run without sentinels may answer the global clustering
question, but it has weaker E3-specific assurance and must be labelled so.

## Interpretation

- `overall_pass=true` means the speed target and configured guardrails passed.
- Select the lowest mean primary-stage wall time among passing candidates.
- A faster candidate with failed concordance is not a replacement.
- The comparison does not establish equivalence for downstream biological
  rankings. The winning method should be rerun through the existing discovery
  engine and its release checks before production adoption.
- Do not compare the new results directly with historical runs that used
  different inputs, versions, thresholds or hardware.
