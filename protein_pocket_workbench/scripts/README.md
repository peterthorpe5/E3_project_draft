# Slurm helper

**New quality rerun:** `run_maddy_quality_pockets.slurm.sh` runs confidence/PAE
preparation, fpocket, P2Rank, both aligners, sequence analysis and export in a
separate results folder. It uses account barton and partition barton, matching
the user's earlier prediction queue. See the top-level README and
`docs/QUALITY_RERUN.md` for install, full run, prepare-only and resume commands.
Use `run_quality_pockets.slurm.sh` for generic named inputs (E3 partition
general preset). Neither shell embeds Python.

**Existing-result builds:** `build_project.slurm.sh` and
`submit_maddy_brca1.sh` reuse prior pocket evidence. Their original general
partition settings remain available independently.

`run_comparisons_slurm.sh` runs the named-option `pocket-workbench compare`
command inside the `pocket_workbench` Conda environment. Defaults: account
`barton`, partition `general`, one CPU, 16 GiB RAM and 24 hours. Structural pairs
are processed sequentially. Pass normal comparison options after the script
name. Scheduler overrides belong before it.

The script uses exported `CONDA_EXE` or `conda` on PATH. Submit after activating
the environment, or export the full Conda executable path. Its output/error logs
are written in the submission directory.
