#!/usr/bin/env python3
"""Reject the retired manifest-driven Expression Atlas download path.

The former implementation accepted an R-generated FTP manifest that did not
enforce the configuration-XML metadata contract now required to interpret
Expression Atlas condition groups.  Keeping that implementation executable
would allow a user to create an apparently complete, but scientifically
under-specified, dataset.  The Python-first discovery/downloader is the sole
supported acquisition path.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Return a failure with the supported replacement command.

    Args:
        argv: Ignored legacy command-line arguments.

    Returns:
        Exit status 2, indicating unsupported command usage.
    """
    del argv
    print(
        "ERROR: download_atlas_files.py is retired because its R-generated "
        "manifest does not enforce the configuration-XML condition-group "
        "contract. Use inst/scripts/02_python_discover_download_atlas.sh or "
        "inst/scripts/run_python_first_then_r.sh.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
