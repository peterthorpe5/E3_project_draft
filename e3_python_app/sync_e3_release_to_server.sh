#!/usr/bin/env bash
# Transfer the established E3 visualisation resources from macOS to the RHEL VM.

set -Eeuo pipefail

umask 027

readonly PROGRAM_NAME=${0##*/}
readonly DEFAULT_REMOTE_HOST="pthorpe001@e3tgts-ls-at1.dundee.ac.uk"
readonly DEFAULT_REMOTE_ROOT="e3_release_upload"
readonly DEFAULT_RESOURCE_DUCKDB="/Users/PThorpe001/e3_app_cache/grant_aligned_corrected_expression_structural_top200_v0_14_0_20260805/10_integrated_resource/duckdb/e3_integrated_resource.duckdb"
readonly DEFAULT_POCKET_REVIEW_DIR="/Users/PThorpe001/e3_app_cache/grant_aligned_corrected_expression_structural_top200_v0_14_0_20260805/pocket_review_top200_v0_3_1"
readonly DEFAULT_HUMAN_PLANT_REVIEW_DIR="/Users/PThorpe001/e3_app_cache/grant_human_plant_structural_top200_v0_16_0_20260826/pocket_review"
readonly RETAINED_FREE_KIB=$((3 * 1024 * 1024))

REMOTE_HOST="${DEFAULT_REMOTE_HOST}"
REMOTE_ROOT="${DEFAULT_REMOTE_ROOT}"
RESOURCE_DUCKDB="${DEFAULT_RESOURCE_DUCKDB}"
POCKET_REVIEW_DIR="${DEFAULT_POCKET_REVIEW_DIR}"
HUMAN_PLANT_REVIEW_DIR="${DEFAULT_HUMAN_PLANT_REVIEW_DIR}"
DRY_RUN=false

log() {
    printf '%s INFO %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2
}

fail() {
    printf '%s ERROR %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2
    exit 2
}

usage() {
    cat <<EOF
Usage:
  ./${PROGRAM_NAME} [OPTIONS]

Synchronise the established E3 DuckDB and review bundles to the University VM.
Transfers are resumable and rerunnable. Existing unrelated remote files are never
deleted.

Options:
  --remote-host HOST              SSH destination (default: ${DEFAULT_REMOTE_HOST}).
  --remote-root DIRECTORY         Relative directory under the remote home
                                  (default: ${DEFAULT_REMOTE_ROOT}).
  --resource-duckdb PATH          Integrated top-200 DuckDB.
  --pocket-review-dir PATH        Plant pocket-review bundle.
  --human-plant-review-dir PATH   Combined human-and-plant review bundle.
  --dry-run                       Show what rsync would transfer.
  --help                          Show this help and exit.
EOF
}

require_value() {
    local option_name=$1
    local remaining_count=$2
    ((remaining_count >= 2)) || fail "${option_name} requires a value."
}

parse_arguments() {
    while (($#)); do
        case "$1" in
            --remote-host)
                require_value "$1" "$#"
                REMOTE_HOST=$2
                shift 2
                ;;
            --remote-root)
                require_value "$1" "$#"
                REMOTE_ROOT=$2
                shift 2
                ;;
            --resource-duckdb)
                require_value "$1" "$#"
                RESOURCE_DUCKDB=$2
                shift 2
                ;;
            --pocket-review-dir)
                require_value "$1" "$#"
                POCKET_REVIEW_DIR=$2
                shift 2
                ;;
            --human-plant-review-dir)
                require_value "$1" "$#"
                HUMAN_PLANT_REVIEW_DIR=$2
                shift 2
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            *)
                fail "Unknown option: $1"
                ;;
        esac
    done
}

validate_options() {
    [[ "${REMOTE_HOST}" =~ ^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+$ ]] || {
        fail "--remote-host must have the form user@hostname."
    }
    [[ "${REMOTE_ROOT}" =~ ^[A-Za-z0-9._/-]+$ ]] || {
        fail "--remote-root contains unsupported characters."
    }
    [[ "${REMOTE_ROOT}" != /* ]] || fail "--remote-root must be relative."
    [[ "/${REMOTE_ROOT}/" != *"/../"* ]] || {
        fail "--remote-root must not contain a parent-directory component."
    }
    [[ -f "${RESOURCE_DUCKDB}" ]] || {
        fail "Resource DuckDB was not found: ${RESOURCE_DUCKDB}"
    }
    [[ -d "${POCKET_REVIEW_DIR}" ]] || {
        fail "Plant pocket-review directory was not found: ${POCKET_REVIEW_DIR}"
    }
    [[ -d "${HUMAN_PLANT_REVIEW_DIR}" ]] || {
        fail "Combined review directory was not found: ${HUMAN_PLANT_REVIEW_DIR}"
    }
}

require_commands() {
    local command_name
    for command_name in ssh rsync du awk; do
        command -v "${command_name}" >/dev/null 2>&1 || {
            fail "Required command was not found: ${command_name}"
        }
    done
}

selected_size_kib() {
    du -sk \
        "${RESOURCE_DUCKDB}" \
        "${POCKET_REVIEW_DIR}" \
        "${HUMAN_PLANT_REVIEW_DIR}" \
        | awk '{total += $1} END {print total + 0}'
}

prepare_remote_directory() {
    ssh "${REMOTE_HOST}" "mkdir -p -- '${REMOTE_ROOT}'"
}

report_capacity() {
    local selected_kib=$1
    local available_kib
    available_kib=$(ssh "${REMOTE_HOST}" \
        "df -Pk -- '${REMOTE_ROOT}' | awk 'NR == 2 {print \$4}'")
    local conservative_required_kib=$((2 * selected_kib + RETAINED_FREE_KIB))
    log "Selected resources occupy approximately $((selected_kib / 1024)) MiB."
    log "Remote filesystem currently has approximately $((available_kib / 1024)) MiB free."
    if ((available_kib < conservative_required_kib)); then
        log "WARNING: the upload plus managed copy may leave less than 3 GiB free."
        log "The server installer will check capacity again and fail safely if required."
    fi
}

sync_resources() {
    local rsync_options=(--archive --human-readable --partial --progress)
    [[ "${DRY_RUN}" == false ]] || rsync_options+=(--dry-run)

    rsync "${rsync_options[@]}" \
        "${RESOURCE_DUCKDB}" \
        "${REMOTE_HOST}:${REMOTE_ROOT}/e3_integrated_resource.duckdb"
    rsync "${rsync_options[@]}" \
        "${POCKET_REVIEW_DIR}/" \
        "${REMOTE_HOST}:${REMOTE_ROOT}/plant_pocket_review/"
    rsync "${rsync_options[@]}" \
        "${HUMAN_PLANT_REVIEW_DIR}/" \
        "${REMOTE_HOST}:${REMOTE_ROOT}/combined_pocket_review/"
}

report_result() {
    if [[ "${DRY_RUN}" == true ]]; then
        log "Dry run complete; no files were changed."
        return 0
    fi
    log "Transfer complete. Remote resource sizes follow."
    ssh "${REMOTE_HOST}" \
        "du -sh -- '${REMOTE_ROOT}/e3_integrated_resource.duckdb' '${REMOTE_ROOT}/plant_pocket_review' '${REMOTE_ROOT}/combined_pocket_review'; df -h -- '${REMOTE_ROOT}'"
    cat <<EOF

On the VM, install and activate this release with:

cd ~/E3_project_draft_deployment
sudo ./e3_python_app/deployment/rhel9/install_e3_python_app.sh \\
  --resource-duckdb "\$HOME/${REMOTE_ROOT}/e3_integrated_resource.duckdb" \\
  --pocket-review-dir "\$HOME/${REMOTE_ROOT}/plant_pocket_review" \\
  --human-plant-review-dir "\$HOME/${REMOTE_ROOT}/combined_pocket_review" \\
  --repository-ref main \\
  --max-rows 1000
EOF
}

main() {
    parse_arguments "$@"
    validate_options
    require_commands
    prepare_remote_directory
    local selected_kib
    selected_kib=$(selected_size_kib)
    report_capacity "${selected_kib}"
    sync_resources
    report_result
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
