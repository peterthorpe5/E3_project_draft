#!/usr/bin/env bash
# Install or update the E3 Python application as a managed RHEL 9 service.

set -Eeuo pipefail

umask 027

readonly PROGRAM_NAME=${0##*/}
readonly APPLICATION_ROOT="/opt/e3-python-app"
readonly APPLICATION_SOURCE="${APPLICATION_ROOT}/source"
readonly APPLICATION_PACKAGE="${APPLICATION_SOURCE}/e3_python_app"
readonly APPLICATION_VENV="${APPLICATION_ROOT}/venv"
readonly DATA_ROOT="/srv/e3-python-app"
readonly RELEASES_ROOT="${DATA_ROOT}/releases"
readonly CURRENT_RELEASE="${DATA_ROOT}/current"
readonly CACHE_ROOT="/var/cache/e3-python-app"
readonly LOG_ROOT="/var/log/e3-python-app"
readonly STATE_ROOT="/var/lib/e3-python-app"
readonly ENVIRONMENT_FILE="/etc/e3-python-app.env"
readonly FIREWALL_RULE_FILE="/etc/e3-python-app.firewall-rule"
readonly SERVICE_FILE="/etc/systemd/system/e3-python-app.service"
readonly SERVICE_NAME="e3-python-app.service"
readonly SERVICE_USER="e3app"
readonly DEFAULT_REPOSITORY_URL="https://github.com/peterthorpe5/E3_project_draft.git"
readonly MINIMUM_REMAINING_BYTES=$((3 * 1024 * 1024 * 1024))

REPOSITORY_REF="main"
REPOSITORY_URL="${DEFAULT_REPOSITORY_URL}"
RESOURCE_DUCKDB=""
EXPRESSION_DUCKDB=""
POCKET_REVIEW_DIR=""
HUMAN_PLANT_REVIEW_DIR=""
TAXONOMY_MAP=""
SERVER_ADDRESS="127.0.0.1"
SERVER_PORT="8501"
MAX_ROWS="1000"
FIREWALL_SOURCE=""
PREPARE_ONLY=false
REPLACE_RELEASE=false
STAGING_ROOT=""

log() {
    printf '%s INFO %s\n' "$(date --utc '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2
}

fail() {
    printf '%s ERROR %s\n' "$(date --utc '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2
    exit 2
}

cleanup() {
    if [[ -n "${STAGING_ROOT}" && -d "${STAGING_ROOT}" ]]; then
        rm --recursive --force -- "${STAGING_ROOT}"
    fi
}

trap cleanup EXIT

usage() {
    cat <<EOF
Usage:
  sudo ./${PROGRAM_NAME} --prepare-only [OPTIONS]
  sudo ./${PROGRAM_NAME} --resource-duckdb PATH [OPTIONS]

Install or update e3_python_app on RHEL 9. The default deployment listens only
on the VM loopback interface and is tested through an SSH tunnel.

Required for a complete deployment:
  --resource-duckdb PATH       Integrated e3_integrated_resource.duckdb source.

Optional release companions:
  --expression-duckdb PATH     Separate Expression Atlas DuckDB.
  --pocket-review-dir PATH     Plant pocket-review bundle.
  --human-plant-review-dir PATH
                               Combined human-and-plant review bundle.
  --taxonomy-map PATH          Reviewed custom taxonomy mapping TSV.

Deployment options:
  --prepare-only               Install code and service assets without data or start.
  --repository-url URL         GitHub URL or trusted local Git clone/bundle.
  --repository-ref REF         Git branch, tag or commit (default: main).
  --server-address ADDRESS     Bind address (default: 127.0.0.1).
  --server-port PORT           Streamlit port (default: 8501).
  --max-rows INTEGER           Per-query row ceiling (default: 1000).
  --firewall-source CIDR       Sole source IP/CIDR allowed to a non-loopback port.
  --replace-release            Activate a different validated release.
  --help                       Show this help and exit.

Do not use --server-address 0.0.0.0 until IT supplies the exact www-2 proxy
source IP or CIDR. The installer never disables SELinux.
EOF
}

require_value() {
    local option_name=$1
    local remaining_count=$2
    ((remaining_count >= 2)) || fail "${option_name} requires a value."
}

validate_text_value() {
    local option_name=$1
    local value=$2
    [[ -n "${value}" ]] || fail "${option_name} must not be empty."
    [[ "${value}" != *$'\n'* && "${value}" != *$'\r'* ]] || {
        fail "${option_name} must not contain a newline."
    }
}

validate_bounded_integer() {
    local option_name=$1
    local value=$2
    local minimum=$3
    local maximum=$4
    [[ "${value}" =~ ^[0-9]+$ ]] || fail "${option_name} must be an integer."
    local parsed_value=$((10#${value}))
    ((parsed_value >= minimum && parsed_value <= maximum)) || {
        fail "${option_name} must be between ${minimum} and ${maximum}."
    }
}

parse_arguments() {
    while (($#)); do
        case "$1" in
            --prepare-only)
                PREPARE_ONLY=true
                shift
                ;;
            --resource-duckdb)
                require_value "$1" "$#"
                RESOURCE_DUCKDB=$2
                shift 2
                ;;
            --expression-duckdb)
                require_value "$1" "$#"
                EXPRESSION_DUCKDB=$2
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
            --taxonomy-map)
                require_value "$1" "$#"
                TAXONOMY_MAP=$2
                shift 2
                ;;
            --repository-ref)
                require_value "$1" "$#"
                REPOSITORY_REF=$2
                shift 2
                ;;
            --repository-url)
                require_value "$1" "$#"
                REPOSITORY_URL=$2
                shift 2
                ;;
            --server-address)
                require_value "$1" "$#"
                SERVER_ADDRESS=$2
                shift 2
                ;;
            --server-port)
                require_value "$1" "$#"
                SERVER_PORT=$2
                shift 2
                ;;
            --max-rows)
                require_value "$1" "$#"
                MAX_ROWS=$2
                shift 2
                ;;
            --firewall-source)
                require_value "$1" "$#"
                FIREWALL_SOURCE=$2
                shift 2
                ;;
            --replace-release)
                REPLACE_RELEASE=true
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

    validate_text_value "--repository-ref" "${REPOSITORY_REF}"
    validate_text_value "--repository-url" "${REPOSITORY_URL}"
    validate_text_value "--server-address" "${SERVER_ADDRESS}"
    case "${SERVER_ADDRESS}" in
        127.0.0.1|0.0.0.0) ;;
        *) fail "--server-address must be 127.0.0.1 or 0.0.0.0." ;;
    esac
    validate_bounded_integer "--server-port" "${SERVER_PORT}" 1 65535
    validate_bounded_integer "--max-rows" "${MAX_ROWS}" 1 100000
    if [[ "${PREPARE_ONLY}" == false && -z "${RESOURCE_DUCKDB}" ]]; then
        fail "--resource-duckdb is required unless --prepare-only is used."
    fi
    if [[ "${PREPARE_ONLY}" == true ]]; then
        [[ -z "${RESOURCE_DUCKDB}${EXPRESSION_DUCKDB}${POCKET_REVIEW_DIR}" ]] || {
            fail "--prepare-only cannot be combined with release resource paths."
        }
        [[ -z "${HUMAN_PLANT_REVIEW_DIR}${TAXONOMY_MAP}" ]] || {
            fail "--prepare-only cannot be combined with release resource paths."
        }
    fi
    if [[ "${SERVER_ADDRESS}" != "127.0.0.1" ]]; then
        [[ -n "${FIREWALL_SOURCE}" ]] || {
            fail "A non-loopback --server-address requires --firewall-source."
        }
    elif [[ -n "${FIREWALL_SOURCE}" ]]; then
        fail "--firewall-source is unnecessary while listening only on loopback."
    fi
    if [[ -n "${FIREWALL_SOURCE}" && ! "${FIREWALL_SOURCE}" =~ ^[0-9a-fA-F:./]+$ ]]; then
        fail "--firewall-source contains unsupported characters."
    fi
}

require_root() {
    ((EUID == 0)) || fail "Run this installer through sudo."
}

install_operating_system_dependencies() {
    log "Installing RHEL application dependencies."
    dnf install --assumeyes git python3.11 python3.11-pip rsync
    command -v git >/dev/null 2>&1 || fail "git installation did not provide git."
    command -v python3.11 >/dev/null 2>&1 || fail "Python 3.11 is unavailable."
    command -v rsync >/dev/null 2>&1 || fail "rsync installation did not provide rsync."
}

create_service_account_and_directories() {
    if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
        log "Creating unprivileged service account ${SERVICE_USER}."
        useradd \
            --system \
            --home-dir "${STATE_ROOT}" \
            --create-home \
            --shell /sbin/nologin \
            "${SERVICE_USER}"
    fi
    install --directory --owner=root --group="${SERVICE_USER}" --mode=0755 \
        "${APPLICATION_ROOT}"
    install --directory --owner=root --group="${SERVICE_USER}" --mode=0750 \
        "${DATA_ROOT}" "${RELEASES_ROOT}"
    install --directory --owner="${SERVICE_USER}" --group="${SERVICE_USER}" --mode=0750 \
        "${CACHE_ROOT}" "${LOG_ROOT}" "${STATE_ROOT}"
}

resolve_repository_ref() {
    local requested_ref=$1
    if git -C "${APPLICATION_SOURCE}" rev-parse --verify --quiet \
        "origin/${requested_ref}^{commit}" >/dev/null; then
        printf 'origin/%s\n' "${requested_ref}"
        return 0
    fi
    if git -C "${APPLICATION_SOURCE}" rev-parse --verify --quiet \
        "${requested_ref}^{commit}" >/dev/null; then
        printf '%s\n' "${requested_ref}"
        return 0
    fi
    fail "Repository ref does not resolve to a commit: ${requested_ref}"
}

install_application() {
    if [[ -d "${APPLICATION_SOURCE}/.git" ]]; then
        [[ -z "$(git -C "${APPLICATION_SOURCE}" status --porcelain)" ]] || {
            fail "Deployment checkout contains local changes: ${APPLICATION_SOURCE}"
        }
        log "Refreshing the existing application checkout."
        git -C "${APPLICATION_SOURCE}" fetch --prune --tags origin
    elif [[ -e "${APPLICATION_SOURCE}" ]]; then
        fail "Application source exists but is not a Git checkout: ${APPLICATION_SOURCE}"
    else
        log "Cloning ${REPOSITORY_URL}."
        git clone "${REPOSITORY_URL}" "${APPLICATION_SOURCE}"
    fi

    local resolved_ref
    resolved_ref=$(resolve_repository_ref "${REPOSITORY_REF}")
    git -C "${APPLICATION_SOURCE}" checkout --detach "${resolved_ref}"
    [[ -f "${APPLICATION_PACKAGE}/pyproject.toml" ]] || {
        fail "The selected ref does not contain e3_python_app."
    }

    local commit_sha
    commit_sha=$(git -C "${APPLICATION_SOURCE}" rev-parse HEAD)
    log "Installing E3 Python application commit ${commit_sha}."
    if [[ ! -x "${APPLICATION_VENV}/bin/python" ]]; then
        python3.11 -m venv "${APPLICATION_VENV}"
    fi
    "${APPLICATION_VENV}/bin/python" -m pip install --upgrade pip setuptools wheel
    "${APPLICATION_VENV}/bin/python" -m pip install --upgrade "${APPLICATION_PACKAGE}"
    "${APPLICATION_VENV}/bin/python" -m pip check
    "${APPLICATION_VENV}/bin/python" -m pip freeze \
        >"${APPLICATION_ROOT}/installed-packages.txt"
    printf '%s\n' "${commit_sha}" >"${APPLICATION_ROOT}/installed-commit.txt"
    chown --recursive root:"${SERVICE_USER}" \
        "${APPLICATION_SOURCE}" \
        "${APPLICATION_VENV}"
    chmod --recursive u=rwX,g=rX,o= \
        "${APPLICATION_SOURCE}" \
        "${APPLICATION_VENV}"
    chmod 0644 \
        "${APPLICATION_ROOT}/installed-packages.txt" \
        "${APPLICATION_ROOT}/installed-commit.txt"
}

install_service_assets() {
    local script_directory
    script_directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
    install --owner=root --group=root --mode=0755 \
        "${script_directory}/start_e3_service.sh" \
        "${APPLICATION_ROOT}/start_e3_service.sh"
    install --owner=root --group=root --mode=0644 \
        "${script_directory}/e3-python-app.service" \
        "${SERVICE_FILE}"
    systemctl daemon-reload
}

canonical_file() {
    local label=$1
    local source_path=$2
    local resolved
    resolved=$(realpath --canonicalize-existing "${source_path}") || {
        fail "${label} does not exist: ${source_path}"
    }
    [[ -f "${resolved}" && -s "${resolved}" ]] || {
        fail "${label} is not a non-empty file: ${resolved}"
    }
    printf '%s\n' "${resolved}"
}

canonical_directory() {
    local label=$1
    local source_path=$2
    local resolved
    resolved=$(realpath --canonicalize-existing "${source_path}") || {
        fail "${label} does not exist: ${source_path}"
    }
    [[ -d "${resolved}" ]] || fail "${label} is not a directory: ${resolved}"
    printf '%s\n' "${resolved}"
}

path_fingerprint() {
    local source_path=$1
    if [[ -f "${source_path}" ]]; then
        sha256sum "${source_path}" | awk '{print $1}'
        return 0
    fi
    (
        cd "${source_path}"
        find . -type f -print0 \
            | LC_ALL=C sort --zero-terminated \
            | xargs --null --no-run-if-empty sha256sum
    ) | sha256sum | awk '{print $1}'
}

release_fingerprint() {
    local resource_path=$1
    local expression_path=$2
    local pocket_path=$3
    local human_plant_path=$4
    local taxonomy_path=$5
    {
        printf 'resource\t%s\n' "$(path_fingerprint "${resource_path}")"
        [[ -z "${expression_path}" ]] || {
            printf 'expression\t%s\n' "$(path_fingerprint "${expression_path}")"
        }
        [[ -z "${pocket_path}" ]] || {
            printf 'pocket_review\t%s\n' "$(path_fingerprint "${pocket_path}")"
        }
        [[ -z "${human_plant_path}" ]] || {
            printf 'human_plant_review\t%s\n' "$(path_fingerprint "${human_plant_path}")"
        }
        [[ -z "${taxonomy_path}" ]] || {
            printf 'taxonomy\t%s\n' "$(path_fingerprint "${taxonomy_path}")"
        }
    } | sha256sum | awk '{print substr($1, 1, 20)}'
}

ensure_copy_capacity() {
    local required_bytes=0
    local source_path
    for source_path in "$@"; do
        [[ -z "${source_path}" ]] && continue
        required_bytes=$((required_bytes + $(du --summarize --bytes "${source_path}" | awk '{print $1}')))
    done
    local available_bytes
    available_bytes=$(df --output=avail --block-size=1 "${DATA_ROOT}" | tail -n 1 | tr -d ' ')
    ((available_bytes >= required_bytes + MINIMUM_REMAINING_BYTES)) || {
        fail "Insufficient disk space to stage the release and retain 3 GiB free."
    }
}

validation_command() {
    local release_path=$1
    local command=(
        "${APPLICATION_VENV}/bin/e3-python-app"
        --resource-duckdb "${release_path}/e3_integrated_resource.duckdb"
        --max-rows "${MAX_ROWS}"
        --validate-only
    )
    [[ ! -f "${release_path}/expression.duckdb" ]] || {
        command+=(--expression-duckdb "${release_path}/expression.duckdb")
    }
    [[ ! -d "${release_path}/pocket_review" ]] || {
        command+=(--pocket-review-dir "${release_path}/pocket_review")
    }
    [[ ! -d "${release_path}/human_plant_review" ]] || {
        command+=(--human-plant-review-dir "${release_path}/human_plant_review")
    }
    [[ ! -f "${release_path}/taxonomy_mapping.tsv" ]] || {
        command+=(--taxonomy-map "${release_path}/taxonomy_mapping.tsv")
    }
    # install_release is called in a command substitution whose stdout is
    # reserved exclusively for the resolved release path. Keep validation
    # diagnostics visible without allowing them to contaminate that value.
    runuser --user "${SERVICE_USER}" -- "${command[@]}" >&2
}

validate_release_or_fail() {
    local release_path=$1
    validation_command "${release_path}" || {
        fail "Release validation failed as service user ${SERVICE_USER}: ${release_path}"
    }
}

install_release() {
    local resource_path
    local expression_path=""
    local pocket_path=""
    local human_plant_path=""
    local taxonomy_path=""
    resource_path=$(canonical_file "Resource DuckDB" "${RESOURCE_DUCKDB}")
    [[ -z "${EXPRESSION_DUCKDB}" ]] || {
        expression_path=$(canonical_file "Expression DuckDB" "${EXPRESSION_DUCKDB}")
    }
    [[ -z "${POCKET_REVIEW_DIR}" ]] || {
        pocket_path=$(canonical_directory "Pocket-review bundle" "${POCKET_REVIEW_DIR}")
    }
    [[ -z "${HUMAN_PLANT_REVIEW_DIR}" ]] || {
        human_plant_path=$(canonical_directory \
            "Human-and-plant review bundle" "${HUMAN_PLANT_REVIEW_DIR}")
    }
    [[ -z "${TAXONOMY_MAP}" ]] || {
        taxonomy_path=$(canonical_file "Taxonomy mapping" "${TAXONOMY_MAP}")
        [[ "${taxonomy_path}" == *.tsv ]] || fail "Taxonomy mapping must end in .tsv."
    }

    local release_id
    release_id=$(release_fingerprint \
        "${resource_path}" \
        "${expression_path}" \
        "${pocket_path}" \
        "${human_plant_path}" \
        "${taxonomy_path}")
    local destination_path="${RELEASES_ROOT}/${release_id}"
    if [[ -d "${destination_path}" ]]; then
        log "Release ${release_id} is already installed; validating it again."
        validate_release_or_fail "${destination_path}"
    else
        ensure_copy_capacity \
            "${resource_path}" \
            "${expression_path}" \
            "${pocket_path}" \
            "${human_plant_path}" \
            "${taxonomy_path}"
        STAGING_ROOT=$(mktemp --directory "${RELEASES_ROOT}/.incoming.XXXXXX")
        local staging_release="${STAGING_ROOT}/${release_id}"
        install --directory --mode=0750 "${staging_release}"
        rsync --archive --no-owner --no-group \
            "${resource_path}" "${staging_release}/e3_integrated_resource.duckdb"
        [[ -z "${expression_path}" ]] || {
            rsync --archive --no-owner --no-group \
                "${expression_path}" "${staging_release}/expression.duckdb"
        }
        [[ -z "${pocket_path}" ]] || {
            rsync --archive --no-owner --no-group \
                "${pocket_path}/" "${staging_release}/pocket_review/"
        }
        [[ -z "${human_plant_path}" ]] || {
            rsync --archive --no-owner --no-group \
                "${human_plant_path}/" "${staging_release}/human_plant_review/"
        }
        [[ -z "${taxonomy_path}" ]] || {
            rsync --archive --no-owner --no-group \
                "${taxonomy_path}" "${staging_release}/taxonomy_mapping.tsv"
        }
        (
            cd "${staging_release}"
            find . -type f ! -name SHA256SUMS.txt -print0 \
                | LC_ALL=C sort --zero-terminated \
                | xargs --null --no-run-if-empty sha256sum
        ) >"${staging_release}/SHA256SUMS.txt"
        chown --recursive root:"${SERVICE_USER}" "${staging_release}"
        chmod --recursive u=rwX,g=rX,o= "${staging_release}"
        validate_release_or_fail "${staging_release}"
        mv "${staging_release}" "${destination_path}"
        rmdir "${STAGING_ROOT}"
        STAGING_ROOT=""
        log "Installed validated release ${release_id}."
    fi

    if [[ -L "${CURRENT_RELEASE}" ]]; then
        local active_target
        active_target=$(readlink --canonicalize "${CURRENT_RELEASE}")
        if [[ "${active_target}" != "${destination_path}" && "${REPLACE_RELEASE}" == false ]]; then
            fail "A different release is active; review it and rerun with --replace-release."
        fi
    elif [[ -e "${CURRENT_RELEASE}" ]]; then
        fail "Current release path exists but is not a managed symbolic link."
    fi

    local temporary_link="${DATA_ROOT}/.current.${release_id}"
    ln --symbolic --force "releases/${release_id}" "${temporary_link}"
    mv --no-target-directory "${temporary_link}" "${CURRENT_RELEASE}"
    printf '%s\n' "${CURRENT_RELEASE}"
}

write_environment_file() {
    local release_path=$1
    local temporary_file
    temporary_file=$(mktemp "${ENVIRONMENT_FILE}.XXXXXX")
    {
        printf 'E3_RESOURCE_DUCKDB=%s/e3_integrated_resource.duckdb\n' "${release_path}"
        [[ ! -f "${release_path}/expression.duckdb" ]] || {
            printf 'E3_EXPRESSION_DUCKDB=%s/expression.duckdb\n' "${release_path}"
        }
        [[ ! -d "${release_path}/pocket_review" ]] || {
            printf 'E3_POCKET_REVIEW_DIR=%s/pocket_review\n' "${release_path}"
        }
        [[ ! -d "${release_path}/human_plant_review" ]] || {
            printf 'E3_HUMAN_PLANT_REVIEW_DIR=%s/human_plant_review\n' "${release_path}"
        }
        [[ ! -f "${release_path}/taxonomy_mapping.tsv" ]] || {
            printf 'E3_TAXONOMY_MAP=%s/taxonomy_mapping.tsv\n' "${release_path}"
        }
        printf 'E3_MAX_TABLE_ROWS=%s\n' "${MAX_ROWS}"
        printf 'E3_APP_HOST=%s\n' "${SERVER_ADDRESS}"
        printf 'E3_APP_PORT=%s\n' "${SERVER_PORT}"
    } >"${temporary_file}"
    chmod 0640 "${temporary_file}"
    chown root:"${SERVICE_USER}" "${temporary_file}"
    mv "${temporary_file}" "${ENVIRONMENT_FILE}"
}

remove_tracked_firewall_rule() {
    [[ -f "${FIREWALL_RULE_FILE}" ]] || return 0
    local existing_rule
    existing_rule=$(<"${FIREWALL_RULE_FILE}")
    if firewall-cmd --permanent --query-rich-rule="${existing_rule}" >/dev/null 2>&1; then
        firewall-cmd --permanent --remove-rich-rule="${existing_rule}"
    fi
    rm --force -- "${FIREWALL_RULE_FILE}"
}

configure_firewall() {
    firewall-cmd --state >/dev/null 2>&1 || fail "firewalld is not running."
    local new_rule=""
    if [[ -n "${FIREWALL_SOURCE}" ]]; then
        local family="ipv4"
        [[ "${FIREWALL_SOURCE}" != *:* ]] || family="ipv6"
        new_rule="rule family=${family} source address=${FIREWALL_SOURCE} port port=${SERVER_PORT} protocol=tcp accept"
    fi

    local existing_rule=""
    [[ ! -f "${FIREWALL_RULE_FILE}" ]] || existing_rule=$(<"${FIREWALL_RULE_FILE}")
    if [[ "${existing_rule}" != "${new_rule}" ]]; then
        remove_tracked_firewall_rule
        if [[ -n "${new_rule}" ]]; then
            log "Restricting port ${SERVER_PORT} to ${FIREWALL_SOURCE}."
            firewall-cmd --permanent --add-rich-rule="${new_rule}"
            printf '%s\n' "${new_rule}" >"${FIREWALL_RULE_FILE}"
            chmod 0600 "${FIREWALL_RULE_FILE}"
        fi
        firewall-cmd --reload
    fi
}

start_and_verify_service() {
    systemctl enable "${SERVICE_NAME}"
    systemctl restart "${SERVICE_NAME}"
    local attempt
    for attempt in $(seq 1 45); do
        if curl \
            --fail \
            --silent \
            --show-error \
            --max-time 2 \
            "http://127.0.0.1:${SERVER_PORT}/_stcore/health" >/dev/null; then
            log "Application health check passed on port ${SERVER_PORT}."
            return 0
        fi
        sleep 1
    done
    journalctl --unit "${SERVICE_NAME}" --lines 100 --no-pager >&2 || true
    fail "Application did not become healthy within 45 seconds."
}

main() {
    parse_arguments "$@"
    require_root
    install_operating_system_dependencies
    create_service_account_and_directories
    install_application
    install_service_assets

    if [[ "${PREPARE_ONLY}" == true ]]; then
        log "Preparation complete; no release was copied and the service was not started."
        return 0
    fi

    local release_path
    release_path=$(install_release)
    write_environment_file "${release_path}"
    configure_firewall
    start_and_verify_service
    log "Deployment completed successfully."
    log "Inspect with: systemctl status ${SERVICE_NAME}"
    log "Follow logs with: journalctl --unit ${SERVICE_NAME} --follow"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
