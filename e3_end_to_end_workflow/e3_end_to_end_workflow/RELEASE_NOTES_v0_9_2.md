# e3_end_to_end_workflow v0.9.2

Release date: 2026-07-27

## Slurm controller source-path repair

Version 0.9.1 submitted the controller body as a batch script and correctly requested the workflow
source directory through `sbatch --chdir`. Slurm nevertheless executes a temporary copy of a batch
script from its spool directory. The controller body derived its source tree from
`${BASH_SOURCE[0]}` and therefore searched for `run_e3_end_to_end.sh` under
`/var/spool/slurmd` before Snakemake could start.

Version 0.9.2 passes the already validated absolute workflow source root from
`submit_e3_controller_slurm.sh` to the internal controller job through a required named option.
The job canonicalises that path, verifies the runner and repeats the existing source-to-install
provenance check before launching Snakemake.

A regression test executes a copy of the controller body from a simulated Slurm spool directory
and verifies that it invokes the runner from the explicitly supplied source tree.

## Safe continuation

Controller job `62079` failed before launching Snakemake or any scientific child job. It did not
alter the existing run state. Resume the same immutable configuration and run name after installing
or applying v0.9.2. Keep every checksum-valid completed stage; do not delete the run root and do
not force Stage 05.
