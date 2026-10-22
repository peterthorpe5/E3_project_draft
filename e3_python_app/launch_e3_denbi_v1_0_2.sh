#!/usr/bin/env bash
# Launch Pete's full E3 app on Sabrina and open it through SSH on this Mac.
# Usage: bash launch_e3_denbi.sh --help
# Bash 3.2+; no Python is embedded in this script. Version 1.0.2.

set -Eeuo pipefail
trap 'printf "[E3] Unexpected failure at line %s (exit %s).\n" "$LINENO" "$?" >&2' ERR

E3_MODE="start"
E3_OPEN_BROWSER="yes"
E3_SSH_HOST="denbi"
E3_LOCAL_PORT="8509"
E3_REMOTE_PORT="8504"
E3_RESTART_APP="no"

while (($#)); do
    case "$1" in
        --help|-h)
            cat <<'USAGE'
Run on your Mac:
  bash launch_e3_denbi.sh                 Start/reuse E3 and open the browser.
  bash launch_e3_denbi.sh --no-browser    Start/reuse E3 and print its URL.
  bash launch_e3_denbi.sh --status        Inspect services, jobs and the tunnel.
  bash launch_e3_denbi.sh --stop-tunnel   Disconnect this launcher's tunnel.
  bash launch_e3_denbi.sh --local-port 8509
                                        Choose the Mac port (default 8509).
  bash launch_e3_denbi.sh --remote-port 8504
                                        Choose the Sabrina port (default 8504).
  bash launch_e3_denbi.sh --restart-app   Restart only the owned full E3 GUI.

The E3 app and analysis worker run on Sabrina through your existing SSH alias
"denbi". Their tmux session survives closing the Mac terminal. Stopping the
tunnel leaves remote analyses running. Run the launcher again to reconnect.
USAGE
            exit 0
            ;;
        --version)
            printf 'E3 Sabrina launcher 1.0.2\n'
            exit 0
            ;;
        --no-browser) E3_OPEN_BROWSER="no" ;;
        --restart-app) E3_RESTART_APP="yes" ;;
        --local-port|--remote-port)
            if (($# < 2)) || [[ ! "$2" =~ ^[1-9][0-9]{0,4}$ ]] \
                || (( $2 < 1024 || $2 > 65535 )); then
                printf '[E3] %s requires a port between 1024 and 65535.\n' "$1" >&2
                exit 2
            fi
            if [[ "$1" == "--local-port" ]]; then
                E3_LOCAL_PORT="$2"
            else
                E3_REMOTE_PORT="$2"
            fi
            shift
            ;;
        --status|--stop-tunnel)
            if [[ "$E3_MODE" != "start" ]]; then
                printf '[E3] Choose one action: --status or --stop-tunnel.\n' >&2
                exit 2
            fi
            E3_MODE="${1#--}"
            ;;
        *)
            printf '[E3] Unknown option: %s. Use --help.\n' "$1" >&2
            exit 2
            ;;
    esac
    shift
done

if [[ "$E3_MODE" != "start" && "$E3_RESTART_APP" == "yes" ]]; then
    printf '[E3] --restart-app applies only to a normal launch.\n' >&2
    exit 2
fi
E3_URL="http://127.0.0.1:$E3_LOCAL_PORT"
E3_CONTROL_PATH="$HOME/.ssh/e3_denbi_${E3_LOCAL_PORT}_${E3_REMOTE_PORT}.sock"

if ! command -v ssh >/dev/null 2>&1; then
    printf '[E3] OpenSSH (ssh) is required on this computer.\n' >&2
    exit 1
fi

if [[ "$E3_MODE" == "stop-tunnel" ]]; then
    if ssh -F /dev/null -S "$E3_CONTROL_PATH" -O check "$E3_SSH_HOST" >/dev/null 2>&1; then
        ssh -F /dev/null -S "$E3_CONTROL_PATH" -O exit "$E3_SSH_HOST"
        printf '[E3] Tunnel disconnected. Remote E3 and analysis jobs remain running.\n'
    else
        printf '[E3] This launcher has no active tunnel.\n'
    fi
    exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
    printf '[E3] curl is required for the app readiness check.\n' >&2
    exit 1
fi

printf '[E3] Launcher v1.0.2: connecting to Sabrina using SSH alias %s...\n' "$E3_SSH_HOST"
if ! ssh -T -o ClearAllForwardings=yes -o ConnectTimeout=15 \
    -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
    "$E3_SSH_HOST" "bash -s -- $E3_MODE $E3_REMOTE_PORT $E3_RESTART_APP" <<'E3_REMOTE'
set -Eeuo pipefail
trap 'printf "[E3 remote] Failure at line %s (exit %s).\n" "$LINENO" "$?" >&2' ERR

E3_ACTION="${1:-start}"
E3_PORT="${2:-8504}"
E3_RESTART="${3:-no}"
E3_ENV="/home/ubuntu/data/pete/software/miniforge3/envs/e3_python_app"
E3_CONFIG="/home/ubuntu/data/protein_research/config/research.toml"
E3_RESOURCES="/home/ubuntu/data/protein_research/e3_resources/top200_20260805_human_plant_20260826"
E3_SESSION="e3-research"
E3_APP_WINDOW="$E3_SESSION:=full-e3"
E3_WORKER_WINDOW="$E3_SESSION:=worker"
E3_TMUX="$E3_ENV/bin/tmux"
E3_WORKBENCH="$E3_ENV/bin/protein-research-workbench"
E3_APP="$E3_ENV/bin/e3-python-app"
E3_HEALTH="http://127.0.0.1:$E3_PORT/_stcore/health"
E3_LOG_ROOT="/home/ubuntu/data/protein_research/logs"
E3_APP_LOG="$E3_LOG_ROOT/full_e3_server.log"
E3_WORKER_LOG="$E3_LOG_ROOT/research_worker.log"

e3_window_dead() {
    # Read a service window's state using strict tmux target resolution.
    #
    # Args:
    #     $1: Exact service window target.
    #
    # Returns:
    #     Prints 0 (live), 1 (dead) or absent. Fails for multiple panes.
    local e3_state
    if ! e3_state="$("$E3_TMUX" list-panes -t "$1" -F '#{pane_dead}' 2>/dev/null)"; then
        printf 'absent\n'
        return 0
    fi
    case "$e3_state" in
        0|1) printf '%s\n' "$e3_state" ;;
        *)
            printf '[E3 remote] Expected one service pane in %s; inspect that window.\n' "$1" >&2
            return 1
            ;;
    esac
}

e3_diagnostics() {
    # Show recent console output and the retained service log.
    #
    # Args:
    #     $1: Exact service window target.
    #     $2: Retained log file.
    #
    # Returns:
    #     Zero after printing available diagnostics to standard error.
    "$E3_TMUX" capture-pane -p -S -80 -t "$1" >&2 || true
    if [[ -f "$2" ]]; then
        printf '\n[E3 remote] Recent output from %s:\n' "$2" >&2
        tail -n 80 "$2" >&2
    fi
    return 0
}

e3_wait_for_app() {
    # Wait for HTTP readiness while checking that the E3 pane is still alive.
    #
    # Returns:
    #     Zero if ready; one on process exit or after the bounded wait.
    local e3_attempt e3_dead
    for ((e3_attempt = 0; e3_attempt < 30; e3_attempt++)); do
        e3_dead="$(e3_window_dead "$E3_APP_WINDOW")" || return 1
        if [[ "$e3_dead" != "0" ]]; then
            return 1
        fi
        if curl --fail --silent --max-time 1 "$E3_HEALTH" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

for E3_BINARY in "$E3_TMUX" "$E3_WORKBENCH" "$E3_APP"; do
    if [[ ! -x "$E3_BINARY" ]]; then
        printf '[E3 remote] Required executable is missing: %s\n' "$E3_BINARY" >&2
        exit 1
    fi
done
if ! command -v curl >/dev/null 2>&1; then
    printf '[E3 remote] curl is required on Sabrina.\n' >&2
    exit 1
fi

if [[ "$E3_ACTION" == "status" ]]; then
    if ! "$E3_TMUX" list-windows -t "$E3_SESSION"; then
        printf '[E3 remote] The E3 tmux session is not running.\n' >&2
        exit 1
    fi
    "$E3_WORKBENCH" --config "$E3_CONFIG" jobs
    E3_APP_DEAD="$(e3_window_dead "$E3_APP_WINDOW")"
    E3_WORKER_DEAD="$(e3_window_dead "$E3_WORKER_WINDOW")"
    if [[ "$E3_APP_DEAD" != "0" ]]; then
        printf '[E3 remote] The full E3 service window is not running.\n' >&2
        e3_diagnostics "$E3_APP_WINDOW" "$E3_APP_LOG"
        exit 1
    fi
    if ! curl --fail --silent --show-error --max-time 5 "$E3_HEALTH"; then
        printf '\n[E3 remote] Full E3 app is not responding on port %s.\n' "$E3_PORT" >&2
        e3_diagnostics "$E3_APP_WINDOW" "$E3_APP_LOG"
        exit 1
    fi
    printf '\n'
    if [[ "$E3_WORKER_DEAD" != "0" ]]; then
        printf '[E3 remote] The research worker is not running.\n' >&2
        exit 1
    fi
    exit 0
fi

for E3_DIRECTORY in "$E3_RESOURCES/plant_pocket_review" "$E3_RESOURCES/pocket_review"; do
    if [[ ! -d "$E3_DIRECTORY" ]]; then
        printf '[E3 remote] Required review directory is missing: %s\n' "$E3_DIRECTORY" >&2
        exit 1
    fi
done
for E3_FILE in "$E3_CONFIG" "$E3_RESOURCES/e3_integrated_resource.duckdb"; do
    if [[ ! -r "$E3_FILE" ]]; then
        printf '[E3 remote] Required file is missing or unreadable: %s\n' "$E3_FILE" >&2
        exit 1
    fi
done

E3_ARGUMENTS=(
    --resource-duckdb "$E3_RESOURCES/e3_integrated_resource.duckdb"
    --pocket-review-dir "$E3_RESOURCES/plant_pocket_review"
    --human-plant-review-dir "$E3_RESOURCES/pocket_review"
    --research-config "$E3_CONFIG"
    --max-rows 1000 --host 127.0.0.1 --port "$E3_PORT" --headless
)
E3_APP_DEAD="$(e3_window_dead "$E3_APP_WINDOW")"
if [[ "$E3_APP_DEAD" != "0" || "$E3_RESTART" == "yes" ]]; then
    printf '[E3 remote] Validating the transferred E3 database and both review bundles...\n'
    if ! "$E3_APP" "${E3_ARGUMENTS[@]}" --validate-only; then
        printf '[E3 remote] Resource validation failed; resolve the error above and retry.\n' >&2
        exit 1
    fi
fi

if [[ "$E3_APP_DEAD" == "0" && "$E3_RESTART" == "yes" ]]; then
    E3_STARTED_COMMAND="$("$E3_TMUX" list-panes -t "$E3_APP_WINDOW" -F '#{pane_start_command}')"
    if [[ "$E3_STARTED_COMMAND" != *"$E3_APP"* \
        || "$E3_STARTED_COMMAND" != *"$E3_CONFIG"* ]]; then
        printf '[E3 remote] Refusing to restart an unrecognised command in full-e3.\n' >&2
        exit 1
    fi
    printf '[E3 remote] Restarting the full E3 GUI; the research worker continues running.\n'
    "$E3_TMUX" kill-pane -t "$E3_APP_WINDOW"
    E3_APP_DEAD="absent"
fi

# Explicit cache/temp paths keep newly started services on the large data disk.
E3_TEMP="/home/ubuntu/data/pete/tmp"
E3_CACHE="/home/ubuntu/data/pete/cache/xdg"
mkdir -p "$E3_TEMP" "$E3_CACHE" "$E3_LOG_ROOT"
E3_SERVICE_ENV=(env "TMPDIR=$E3_TEMP" "XDG_CACHE_HOME=$E3_CACHE" PYTHONUNBUFFERED=1)
E3_APP_COMMAND=(
    "${E3_SERVICE_ENV[@]}" "E3_LAUNCHER_LOG=$E3_APP_LOG"
    bash -c 'exec "$@" >>"$E3_LAUNCHER_LOG" 2>&1' e3-app
    "$E3_APP" "${E3_ARGUMENTS[@]}"
)
E3_WORKER_COMMAND=(
    "${E3_SERVICE_ENV[@]}" "E3_LAUNCHER_LOG=$E3_WORKER_LOG"
    bash -c 'exec "$@" >>"$E3_LAUNCHER_LOG" 2>&1' e3-worker
    "$E3_WORKBENCH" --config "$E3_CONFIG" worker
)
E3_WORKER_DEAD="$(e3_window_dead "$E3_WORKER_WINDOW")"
if [[ "$E3_WORKER_DEAD" == "1" ]]; then
    "$E3_TMUX" respawn-pane -t "$E3_WORKER_WINDOW" \
        "${E3_WORKER_COMMAND[@]}"
elif [[ "$E3_WORKER_DEAD" != "0" ]]; then
    if "$E3_TMUX" has-session -t "$E3_SESSION" 2>/dev/null; then
        "$E3_TMUX" new-window -d -t "$E3_SESSION:" -n worker \
            "${E3_WORKER_COMMAND[@]}"
    else
        "$E3_TMUX" new-session -d -s "$E3_SESSION" -n worker \
            "${E3_WORKER_COMMAND[@]}"
    fi
fi
if [[ "$E3_APP_DEAD" == "1" ]]; then
    "$E3_TMUX" respawn-pane -t "$E3_APP_WINDOW" \
        "${E3_APP_COMMAND[@]}"
elif [[ "$E3_APP_DEAD" != "0" ]]; then
    "$E3_TMUX" new-window -d -t "$E3_SESSION:" -n full-e3 \
        "${E3_APP_COMMAND[@]}"
fi

printf '[E3 remote] Waiting for the full E3 interface...\n'
if ! e3_wait_for_app; then
    e3_diagnostics "$E3_APP_WINDOW" "$E3_APP_LOG"
    printf '[E3 remote] Full E3 did not become ready on Sabrina port %s.\n' "$E3_PORT" >&2
    printf '[E3 remote] Use --restart-app to replace an earlier E3 GUI started on another port.\n' >&2
    exit 1
fi
E3_WORKER_DEAD="$(e3_window_dead "$E3_WORKER_WINDOW")"
if [[ "$E3_WORKER_DEAD" != "0" ]]; then
    e3_diagnostics "$E3_WORKER_WINDOW" "$E3_WORKER_LOG"
    printf '[E3 remote] The research worker stopped during startup.\n' >&2
    exit 1
fi
printf '[E3 remote] Full E3 app and research worker are running.\n'
E3_REMOTE
then
    printf '[E3] Could not prepare the remote app. Check the diagnostic above.\n' >&2
    exit 1
fi

if [[ "$E3_MODE" == "status" ]]; then
    if ! ssh -F /dev/null -S "$E3_CONTROL_PATH" -O check "$E3_SSH_HOST"; then
        printf '[E3] No tunnel owned by this launcher. Run the launcher to connect.\n' >&2
        exit 1
    fi
else
    E3_NEW_MASTER="no"
    if ssh -F /dev/null -S "$E3_CONTROL_PATH" -O check "$E3_SSH_HOST" >/dev/null 2>&1; then
        printf '[E3] Reusing this launcher\047s SSH connection.\n'
    else
        # Keep alias, identity, proxy and host-key settings for authentication.
        # Clear inherited forwards before creating this dedicated connection.
        if ! ssh -fNT -M -S "$E3_CONTROL_PATH" \
            -o ControlPersist=yes -o ClearAllForwardings=yes \
            -o ConnectTimeout=15 \
            -o ServerAliveInterval=15 -o ServerAliveCountMax=3 "$E3_SSH_HOST"; then
            printf '[E3] Could not establish the launcher\047s SSH connection.\n' >&2
            printf '[E3] The remote E3 services remain running.\n' >&2
            exit 1
        fi
        E3_NEW_MASTER="yes"
    fi
    # Control requests use the already authenticated socket. Reading no config
    # here prevents inherited forwards from being added back. Setting
    # ClearAllForwardings=yes with -L would also erase the requested E3 forward.
    # OpenSSH acknowledges an identical existing forward, so this is repeatable
    # and also repairs a master left without a forward by an interrupted run.
    printf '[E3] Connecting Mac port %s to Sabrina port %s...\n' "$E3_LOCAL_PORT" "$E3_REMOTE_PORT"
    if ! ssh -F /dev/null -S "$E3_CONTROL_PATH" -O forward \
        -o ExitOnForwardFailure=yes \
        -L "127.0.0.1:$E3_LOCAL_PORT:127.0.0.1:$E3_REMOTE_PORT" "$E3_SSH_HOST"; then
        printf '[E3] Tunnel failed for Mac port %s. Choose another --local-port if it is occupied.\n' "$E3_LOCAL_PORT" >&2
        if [[ "$E3_NEW_MASTER" == "yes" ]]; then
            if ! ssh -F /dev/null -S "$E3_CONTROL_PATH" -O exit "$E3_SSH_HOST" >/dev/null 2>&1; then
                printf '[E3] Could not close the new SSH connection; use --stop-tunnel to retry.\n' >&2
            fi
        fi
        printf '[E3] The remote E3 services remain running.\n' >&2
        exit 1
    fi
fi

if ! curl --fail --silent --show-error --max-time 3 \
    --retry 5 --retry-connrefused --retry-delay 1 --retry-max-time 15 \
    "$E3_URL/_stcore/health" >/dev/null; then
    printf '[E3] The tunnel did not reach E3. Try --stop-tunnel, then run the launcher again.\n' >&2
    exit 1
fi

printf '\n[E3] Full E3 app: %s\n' "$E3_URL"
printf '[E3] Research: stage 3 > Protein research workbench > Discover > E3 ranked groups\n'
if [[ "$E3_MODE" == "start" && "$E3_OPEN_BROWSER" == "yes" ]]; then
    if [[ "$(uname -s)" == "Darwin" ]] && command -v open >/dev/null 2>&1; then
        if ! open "$E3_URL"; then
            printf '[E3] Browser could not open automatically; open the URL above.\n' >&2
        fi
    fi
fi
