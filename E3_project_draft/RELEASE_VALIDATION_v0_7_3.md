# PT_E3_6 release validation: e3_end_to_end_workflow v0.7.3

Date: 24 July 2026

## Scope

This patch corrects the production stage-00 report failure caused by an incomplete presentation
mapping for controlled reuse inputs. It does not change the scientific input authorities,
prioritisation thresholds or reviewed OrthoFinder policy.

## Corrected behaviour

- `candidate_evidence` and every other current production input receive an explicit report role.
- A future validated input identifier receives a conservative human-readable role rather than
  invalidating a scientifically successful stage.
- Production-mode stage `00_inputs` completes report creation and atomic publication.

## Executed validation

- 124 Python tests passed.
- Total branch-aware coverage met the enforced 90% threshold.
- `reporting.py` achieved 95% coverage.
- `runner.py` achieved 91% coverage.
- Python compilation, PEP 8 and Google/PEP 257 docstring checks passed.
- Snakemake lint passed.
- The complete 13-stage synthetic DAG passed.
- Bounded rerun, resume and final no-op dry-run checks passed.

## Production boundary

The corrected real-data run has not yet been submitted. The current grant-aligned analysis must
continue to reuse the frozen OrthoFinder 2.5.5 `Results_Feb26.tar.gz` authority. The abandoned fresh
five-proteome validation does not supersede it.
