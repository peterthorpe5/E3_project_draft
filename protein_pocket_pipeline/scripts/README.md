# Optional Slurm wrapper

A normal local/denbi server can run `protein-pockets run` directly.
For Dundee Slurm, activate the environment in the submitting shell first:

```bash
conda activate protein_pockets
sbatch scripts/run_slurm.sh \
  --models /absolute/path/to/alphafold_models \
  --output /absolute/path/to/pocket_results \
  --p2rank /absolute/path/to/p2rank_2.5.1/prank
```

The wrapper defaults to `--account=barton --partition=general`, four CPUs,
16 GiB memory and four hours. P2Rank receives the allocated CPU count. Override
scheduler defaults before the script name if your site requires different values:

```bash
sbatch --account=your_account --partition=your_partition \
  --cpus-per-task=8 --mem=32G --time=12:00:00 \
  scripts/run_slurm.sh \
  --models /absolute/path/to/models \
  --output /absolute/path/to/results \
  --p2rank /absolute/path/to/prank
```

The environment and software paths must be available on the compute node. Use
absolute input/output paths. Pass `--resume` when resubmitting an interrupted
identical run. Do not separately pass `--threads` to this wrapper: it already
uses `SLURM_CPUS_PER_TASK`. The shell contains no embedded Python code.
