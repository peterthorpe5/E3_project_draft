#!/usr/bin/env bash
#SBATCH --job-name=maddy_brca1_pockets
#SBATCH --account=barton
#SBATCH --partition=general
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=1-00:00:00
#SBATCH --output=maddy_brca1_pockets-%j.out
#SBATCH --error=maddy_brca1_pockets-%j.err

# AlphaFold Server CIF discovery and one combined protein-pockets run.
# Bash only: no embedded Python; original model folders are read without changes.
set -Eeuo pipefail
export LC_ALL=C

usage() {
    cat <<'USAGE'
Usage: bash run_maddy_brca1_pockets.slurm.sh [named options]
       sbatch run_maddy_brca1_pockets.slurm.sh [named options]

Defaults are tailored to Maddy's BRCA1 project. Every model in each immediate
fold_* folder is included, using <folder-name>_model_<integer>.cif filenames.
One manifest feeds one pipeline run, producing combined and per-model reports.

Options:
  --project-dir PATH     Default: ~/data/2026_E3_protac/2026_oct_Maddy_BRCA1_pockets
  --models-dir PATH      Default: <project-dir>/alpha_fold_models
  --output-dir PATH      Default: <project-dir>/results/pockets_all_models_v1
                        With --model-index N: results/pockets_model_N_v1 instead.
  --model-index all|N    All prediction indices (default), or one explicit index.
                        An index is a filename suffix, not a quality ranking.
  --p2rank PATH         Default: <project-dir>/software/p2rank_2.5.1/prank
  --fpocket PATH        Default: fpocket (resolved inside the Conda environment)
  --conda-env NAME      Default: protein_pockets
  --conda-exe PATH      Default: CONDA_EXE, or conda on PATH
  --no-conda            Use protein-pockets and tools from the current environment.
  --threads N           Default: SLURM_CPUS_PER_TASK, or 8 outside Slurm
  --timeout-seconds N   Per external command; default: 3600
  --chain ID            Optional explicit author chain, or all for a complex.
  --resume              Reuse a compatible run; retry failed/incomplete models.
  --dry-run             Write/inspect the manifest without loading/running tools.
  --help                Show this help.

The manifest is <output-dir>.manifest.tsv, beside the results directory.
This wrapper expects protein-pocket-pipeline 1.0.0, fpocket 4.2.2 and P2Rank 2.5.1.
USAGE
}

log() {
    printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

die() {
    log "ERROR: $*" >&2
    exit 1
}

require_value() {
    if [[ -z "${2-}" || "${2-}" == --* ]]; then
        die "Option $1 needs a value. Use --help for usage."
    fi
}

validate_tsv_text() {
    if [[ "$2" == *$'\t'* || "$2" == *$'\n'* || "$2" == *$'\r'* ]]; then
        die "$1 contains a tab or newline and cannot be written to the manifest."
    fi
}

manifest_tmp=''
cleanup() {
    if [[ -n "$manifest_tmp" ]]; then
        rm -f -- "$manifest_tmp"
    fi
}
trap cleanup EXIT

project_dir="${HOME}/data/2026_E3_protac/2026_oct_Maddy_BRCA1_pockets"
models_dir=''
output_dir=''
p2rank=''
fpocket='fpocket'
conda_env='protein_pockets'
conda_exe="${CONDA_EXE:-conda}"
use_conda=true
model_index='all'
threads="${SLURM_CPUS_PER_TASK:-8}"
timeout_seconds=3600
chain=''
resume=false
dry_run=false

while (( $# > 0 )); do
    case "$1" in
        --project-dir|--models-dir|--output-dir|--p2rank|--fpocket|--conda-env|--conda-exe|--model-index|--threads|--timeout-seconds|--chain)
            require_value "$1" "${2-}"
            case "$1" in
                --project-dir) project_dir=$2 ;;
                --models-dir) models_dir=$2 ;;
                --output-dir) output_dir=$2 ;;
                --p2rank) p2rank=$2 ;;
                --fpocket) fpocket=$2 ;;
                --conda-env) conda_env=$2 ;;
                --conda-exe) conda_exe=$2 ;;
                --model-index) model_index=$2 ;;
                --threads) threads=$2 ;;
                --timeout-seconds) timeout_seconds=$2 ;;
                --chain) chain=$2 ;;
            esac
            shift 2
            ;;
        --no-conda) use_conda=false; shift ;;
        --resume) resume=true; shift ;;
        --dry-run) dry_run=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "Unknown argument: $1. Use named options; see --help." ;;
    esac
done

(( BASH_VERSINFO[0] >= 4 )) || die 'Bash 4 or later is required.'
[[ "$model_index" == all || "$model_index" =~ ^(0|[1-9][0-9]*)$ ]] || \
    die '--model-index must be all or a non-negative integer without leading zeros.'
[[ "$threads" =~ ^[1-9][0-9]{0,5}$ ]] || die '--threads must be a positive integer (at most 6 digits).'
[[ "$timeout_seconds" =~ ^[1-9][0-9]{0,8}$ ]] || die '--timeout-seconds must be a positive integer (at most 9 digits).'
if [[ -n "${SLURM_CPUS_PER_TASK:-}" ]]; then
    [[ "$SLURM_CPUS_PER_TASK" =~ ^[1-9][0-9]{0,5}$ ]] || die 'Invalid SLURM_CPUS_PER_TASK.'
    (( threads <= SLURM_CPUS_PER_TASK )) || die '--threads exceeds SLURM_CPUS_PER_TASK.'
fi

project_dir=$(realpath --canonicalize-missing -- "$project_dir")
models_dir="${models_dir:-${project_dir}/alpha_fold_models}"
if [[ "$model_index" == all ]]; then
    output_dir="${output_dir:-${project_dir}/results/pockets_all_models_v1}"
else
    output_dir="${output_dir:-${project_dir}/results/pockets_model_${model_index}_v1}"
fi
p2rank="${p2rank:-${project_dir}/software/p2rank_2.5.1/prank}"
[[ -d "$models_dir" ]] || die "Model directory does not exist: $models_dir"
models_dir=$(cd -- "$models_dir" && pwd -P)
output_dir=$(realpath --canonicalize-missing -- "$output_dir")
validate_tsv_text 'Model directory' "$models_dir"
validate_tsv_text 'Output directory' "$output_dir"
[[ "$output_dir" != / ]] || die 'The output directory must not be the filesystem root.'
[[ ! -e "$output_dir" || -d "$output_dir" ]] || die "Output path is not a directory: $output_dir"
manifest_path="${output_dir}.manifest.tsv"
mkdir -p -- "$(dirname -- "$manifest_path")"
manifest_tmp=$(mktemp -- "${manifest_path}.tmp.XXXXXXXX")
printf 'sample_id\tmodel_path\tcluster\n' > "$manifest_tmp"

shopt -s nullglob
declare -A seen_ids=()
folder_count=0
model_count=0
for folder in "$models_dir"/fold_*; do
    [[ -d "$folder" ]] || continue
    label=${folder##*/}
    validate_tsv_text 'Folder name' "$label"
    folder_model_count=0
    for model in "$folder"/"${label}"_model_*.cif; do
        [[ -f "$model" ]] || continue
        sample_id=${model##*/}
        sample_id=${sample_id%.cif}
        index=${sample_id##*_model_}
        [[ "$index" =~ ^(0|[1-9][0-9]*)$ ]] || continue
        [[ "$model_index" == all || "$index" == "$model_index" ]] || continue
        [[ "$sample_id" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$ ]] || \
            die "Invalid or overlong sample identifier: $sample_id"
        folded_id=${sample_id,,}
        [[ -z "${seen_ids[$folded_id]+present}" ]] || die "Duplicate sample identifier: $sample_id"
        seen_ids[$folded_id]=1
        [[ -s "$model" ]] || die "Empty model file: $model"
        model_path=$(realpath -- "$model")
        validate_tsv_text 'Model path' "$model_path"
        printf '%s\t%s\t%s\n' "$sample_id" "$model_path" "$label" >> "$manifest_tmp"
        folder_model_count=$((folder_model_count + 1))
        model_count=$((model_count + 1))
    done
    (( folder_model_count > 0 )) || \
        die "No matching non-empty model CIFs for index '$model_index' in $folder"
    folder_count=$((folder_count + 1))
    log "$label: $folder_model_count model(s)"
done
(( folder_count > 0 )) || die "No fold_* directories found immediately below $models_dir"
mv -- "$manifest_tmp" "$manifest_path"
manifest_tmp=''

log "Discovered $model_count model(s) in $folder_count folder(s); prediction index: $model_index"
log "Manifest: $manifest_path"
log "Results:  $output_dir"
log "Threads:  $threads; timeout per external command: ${timeout_seconds}s"
if [[ "$dry_run" == true ]]; then
    log 'Dry run complete. No analysis tools were loaded or executed.'
    exit 0
fi

runner=()
if [[ "$use_conda" == true ]]; then
    command -v "$conda_exe" >/dev/null 2>&1 || \
        die 'Conda executable unavailable. Pass --conda-exe /full/path/to/conda, or use --no-conda with an active environment.'
    runner=("$conda_exe" run --no-capture-output --name "$conda_env")
else
    command -v protein-pockets >/dev/null 2>&1 || \
        die 'protein-pockets is unavailable. Activate protein_pockets or remove --no-conda.'
fi
command_args=(
    protein-pockets run
    --manifest "$manifest_path"
    --output "$output_dir"
    --fpocket "$fpocket"
    --p2rank "$p2rank"
    --require-p2rank 2.5.1
    --predict-config alphafold
    --rescore-config rescore_2024
    --confidence plddt
    --threads "$threads"
    --timeout "$timeout_seconds"
)
[[ -z "$chain" ]] || command_args+=(--chain "$chain")
[[ "$resume" == false ]] || command_args+=(--resume)
printf 'Launching:'
printf ' %q' "${runner[@]}" "${command_args[@]}"
printf '\n'
if "${runner[@]}" "${command_args[@]}"; then
    status=0
else
    status=$?
fi
case "$status" in
    0) log 'Analysis completed successfully.' ;;
    2) log 'Analysis has failed or partial models. Review Model_checks, Method_runs and pipeline.log.' >&2 ;;
    *) log "Pipeline exited with status $status. Review the Slurm logs and pipeline.log if present." >&2 ;;
esac
log "Results directory: $output_dir"
if [[ -f "$output_dir/report.html" ]]; then
    log "HTML report: $output_dir/report.html"
fi
exit "$status"
