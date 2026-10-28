#!/usr/bin/env bash
# Submit the complete batch build; no analysis runs on the login node.
set -Eeuo pipefail
workbench_script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workbench_project="${MADDY_PROJECT:-$HOME/data/2026_E3_protac/2026_oct_Maddy_BRCA1_pockets}"
workbench_resource="${WORKBENCH_RESOURCE:-$workbench_project/results/brca1_workbench_v1_1}"
workbench_review="${WORKBENCH_REVIEW:-$workbench_project/results/brca1_review_v1_1}"

if [[ ! -d "$workbench_project/results/pockets_all_models_v1" ]]; then
    printf 'ERROR: completed pocket run missing: %s\n' "$workbench_project/results/pockets_all_models_v1" >&2
    exit 1
fi
if [[ ! -f "$workbench_project/BRCA1_all_reps.fasta" ]]; then
    printf 'ERROR: FASTA missing: %s\n' "$workbench_project/BRCA1_all_reps.fasta" >&2
    exit 1
fi
if [[ -e "$workbench_resource" || -e "$workbench_review" || -e "$workbench_review.zip" ]]; then
    printf '%s\n' 'ERROR: output exists. Use a new WORKBENCH_RESOURCE/WORKBENCH_REVIEW, or the documented --resource resume command.' >&2
    exit 1
fi
command -v sbatch >/dev/null 2>&1 || {
    printf '%s\n' 'ERROR: run this submit script on the Dundee HPC.' >&2
    exit 1
}
printf 'Reusing: %s\nResource: %s\nShareable review: %s.zip\n' \
    "$workbench_project/results/pockets_all_models_v1" "$workbench_resource" "$workbench_review"
sbatch "$workbench_script_dir/build_project.slurm.sh" \
    --input "$workbench_project/results/pockets_all_models_v1" \
    --input "$workbench_project/alpha_fold_models" \
    --fasta "$workbench_project/BRCA1_all_reps.fasta" \
    --output "$workbench_resource" \
    --review-output "$workbench_review" \
    --title "BRCA1 pocket workbench" \
    --comparison-mode all_pairs \
    --aligner usalign --aligner tmalign \
    --fit-scope global --min-plddt 0 \
    --top-pockets 5 --workers 4 --threads 8 \
    --bootstrap 100 --seed 42 "$@"
