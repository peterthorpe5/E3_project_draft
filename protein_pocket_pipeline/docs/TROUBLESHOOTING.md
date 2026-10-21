# Troubleshooting

## Check the report and exit status

A partial run still writes Excel, HTML, TSV and DuckDB. Start with **Model_checks**
and **Method_runs**, then inspect the indicated stdout/stderr logs. Setup/input
errors before analysis return 1 and may not create a report. A run with any
failed/partial model returns 2. A valid no-pocket result returns 0.

## Common messages

| Message / symptom | Action |
| --- | --- |
| Executable not found | Activate the correct environment; supply explicit `--fpocket`/`--p2rank` paths |
| P2Rank version check failed | Run `prank -v`; use the documented 2.5.1 release and Java 17 |
| Multiple protein chains | Select the target using `--chain` or manifest `chain`; use `all` only for deliberate complex analysis |
| FASTA identifier missing | Use the exact first FASTA header token in manifest `sequence_id` |
| Structure sequence does not exactly match FASTA | Check the sequence, target chain, missing residues and model version; use `--allow-fragments` only for a unique exact domain fragment |
| pLDDT outside 0–100 | Confirm B fields contain AlphaFold confidence; otherwise use `--confidence none` in a new output directory |
| Constant pLDDT | Check whether a conversion step replaced confidence with a constant |
| No complete N/CA/C backbone | Supply an all-atom protein model rather than a CA-only trace |
| fpocket/P2Rank succeeds but output is absent | Inspect stderr and stdout. The parser intentionally treats missing/malformed outputs as failure |
| Rescoring failed | fpocket-only ranking is labelled as a fallback; independent P2Rank may still be available |
| No pockets | Check model suitability and native logs. This is distinct from tool failure and is not proof that a protein cannot bind a molecule |
| Timeout | Review logs, increase `--timeout` in a new output directory, or reduce the model set |
| Java memory error | Ask the administrator to review P2Rank's launcher heap setting; use a new output after changing tool identity |

## Resume safely

Use the original command plus `--resume`. The run fingerprint must still match:
input structure bytes, optional FASTA/metadata, options, pipeline source, tool
executables and selected P2Rank assets. A changed machine CPU report alone does
not invalidate identical software. A moved model path or changed analysis choice
does require a new directory.

Successful models are reused only if their checkpoint data digest and retained
file checksums match. Failed/partial models are retried in their own directories.
All aggregate exports are rebuilt, so rows are not appended or duplicated. Do not
edit result files you want to preserve inside an active resumable run.

## Stale lock

`.run.lock` prevents two processes writing the same run. Interruptions handled by
the pipeline remove it, but a forcibly killed job can leave it behind. Confirm
that the original process/Slurm job is no longer running, then remove **only that
run's** `.run.lock` and resume the identical command. Never remove a lock belonging
to a live process. Logs and per-model checkpoints are retained after interruption.

## Recoverable export failure

If Excel/HTML export fails, the manifest says `interrupted_or_export_failed`.
Resolve the storage/permission problem and use `--resume`. Intact per-model
analysis can be reused; it need not be rerun just to regenerate the reports.

## Sharing results

Copy/archive the complete result directory. The HTML's tables work on their own,
but links to Excel, prepared structures and TSV require the adjacent files. The
DuckDB database is materialised and can be copied independently. These outputs
contain structure/sequence data and local provenance paths from the run.
