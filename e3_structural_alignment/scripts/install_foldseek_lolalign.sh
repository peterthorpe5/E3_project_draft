#!/usr/bin/env bash
# Install the tested Linux AVX2 LoL-enabled Foldseek build into a new prefix.
# No existing installation is overwritten. An archive can be supplied offline.
set -euo pipefail

FOLDSEEK_INSTALL_PREFIX=""
FOLDSEEK_INSTALL_ARCHIVE=""
FOLDSEEK_INSTALL_REVISION="463739e0014a1549a527de589102cde98f802f37"
FOLDSEEK_INSTALL_SHA256="f886374e29ebbf03849cd9c4c8929be00904856dd271627d8c3043607e2af95a"
FOLDSEEK_INSTALL_URL="https://mmseqs.com/foldseek/foldseek-linux-avx2.tar.gz"

while (($#)); do
    case "$1" in
        --prefix|--archive)
            if (($# < 2)); then
                printf 'ERROR: %s requires a value\n' "$1" >&2
                exit 2
            fi
            if [[ "$1" == "--prefix" ]]; then
                FOLDSEEK_INSTALL_PREFIX="$2"
            else
                FOLDSEEK_INSTALL_ARCHIVE="$2"
            fi
            shift 2
            ;;
        --help)
            printf '%s\n' \
                'Usage: bash install_foldseek_lolalign.sh --prefix /absolute/new/path [--archive FILE]' \
                'Installs the checksum-pinned, LoL-enabled Linux x86_64 AVX2 Foldseek build.'
            exit 0
            ;;
        *) printf 'ERROR: unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
done

FOLDSEEK_INSTALL_PREFIX="${FOLDSEEK_INSTALL_PREFIX%/}"
if [[ "$FOLDSEEK_INSTALL_PREFIX" != /* ]]; then
    printf 'ERROR: --prefix must be an absolute, new directory path\n' >&2
    exit 2
fi
if [[ -e "$FOLDSEEK_INSTALL_PREFIX" || -L "$FOLDSEEK_INSTALL_PREFIX" ]]; then
    printf 'ERROR: installation prefix already exists: %s\n' "$FOLDSEEK_INSTALL_PREFIX" >&2
    exit 2
fi
if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]] \
    || ! grep -qw avx2 /proc/cpuinfo; then
    printf 'ERROR: this pinned build requires Linux x86_64 with AVX2\n' >&2
    exit 2
fi
for FOLDSEEK_INSTALL_COMMAND in tar sha256sum mktemp; do
    command -v "$FOLDSEEK_INSTALL_COMMAND" >/dev/null
done
FOLDSEEK_INSTALL_PARENT="$(dirname -- "$FOLDSEEK_INSTALL_PREFIX")"
mkdir -p -- "$FOLDSEEK_INSTALL_PARENT"
FOLDSEEK_INSTALL_TMP="$(mktemp -d "$FOLDSEEK_INSTALL_PARENT/.foldseek-install.XXXXXXXX")"
trap 'rm -rf -- "${FOLDSEEK_INSTALL_TMP:?}"' EXIT

if [[ -n "$FOLDSEEK_INSTALL_ARCHIVE" ]]; then
    cp -- "$FOLDSEEK_INSTALL_ARCHIVE" "$FOLDSEEK_INSTALL_TMP/foldseek.tar.gz"
else
    printf 'Downloading the pinned LoL-enabled Foldseek build\n' >&2
    curl --fail --location --silent --show-error --retry 3 \
        --connect-timeout 30 --max-time 600 \
        --output "$FOLDSEEK_INSTALL_TMP/foldseek.tar.gz" "$FOLDSEEK_INSTALL_URL"
fi
if ! printf '%s  %s\n' "$FOLDSEEK_INSTALL_SHA256" "$FOLDSEEK_INSTALL_TMP/foldseek.tar.gz" \
    | sha256sum --check --status; then
    printf 'ERROR: Foldseek archive checksum differs from the tested build\n' >&2
    exit 2
fi
tar --extract --gzip --no-same-owner \
    --file "$FOLDSEEK_INSTALL_TMP/foldseek.tar.gz" --directory "$FOLDSEEK_INSTALL_TMP"
FOLDSEEK_INSTALL_ACTUAL_REVISION="$("$FOLDSEEK_INSTALL_TMP/foldseek/bin/foldseek" version)"
if [[ "$FOLDSEEK_INSTALL_ACTUAL_REVISION" != "$FOLDSEEK_INSTALL_REVISION" ]]; then
    printf 'ERROR: Foldseek revision differs from the tested revision\n' >&2
    exit 2
fi
"$FOLDSEEK_INSTALL_TMP/foldseek/bin/foldseek" easy-search -h \
    > "$FOLDSEEK_INSTALL_TMP/help.txt" 2>&1
if ! grep -q -- '--lolalign-multidomain' "$FOLDSEEK_INSTALL_TMP/help.txt"; then
    printf 'ERROR: Foldseek does not advertise LoL-align support\n' >&2
    exit 2
fi
printf 'field\tvalue\nrevision\t%s\narchive_sha256\t%s\nsource_url\t%s\n' \
    "$FOLDSEEK_INSTALL_REVISION" "$FOLDSEEK_INSTALL_SHA256" "$FOLDSEEK_INSTALL_URL" \
    > "$FOLDSEEK_INSTALL_TMP/foldseek/INSTALL_PROVENANCE.tsv"
mv --no-target-directory --no-clobber -- \
    "$FOLDSEEK_INSTALL_TMP/foldseek" "$FOLDSEEK_INSTALL_PREFIX"
if [[ -d "$FOLDSEEK_INSTALL_TMP/foldseek" ]]; then
    printf 'ERROR: another installation created the destination concurrently\n' >&2
    exit 2
fi
printf 'Installed revision: %s\nExecutable: %s/bin/foldseek\n' \
    "$FOLDSEEK_INSTALL_REVISION" "$FOLDSEEK_INSTALL_PREFIX"
