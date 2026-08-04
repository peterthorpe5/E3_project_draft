#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' \
  'ERROR: 03b_download_atlas_files_python.sh is retired because the old' \
  'R-generated manifest did not enforce the configuration-XML condition-group' \
  'contract. Use 02_python_discover_download_atlas.sh or' \
  'run_python_first_then_r.sh.' >&2
exit 2
