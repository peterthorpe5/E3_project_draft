#!/usr/bin/env python3
"""Small external DIAMOND double for subprocess integration tests."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def option(arguments: list[str], name: str) -> str:
    """Return the value immediately following a named option."""

    try:
        return arguments[arguments.index(name) + 1]
    except (ValueError, IndexError) as error:
        raise SystemExit(f"missing option: {name}") from error


def fasta_identifiers(path: Path) -> list[str]:
    """Return FASTA identifiers in input order."""

    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(">"):
            values.append(line[1:].split()[0])
    return values


def main(arguments: list[str]) -> int:
    """Implement the DIAMOND subcommands used by the package."""

    if not arguments:
        return 2
    command = arguments[0]
    if os.environ.get("FAKE_DIAMOND_FAIL_STAGE") == command:
        print(f"deliberate {command} failure", file=sys.stderr)
        return 9
    delay = float(os.environ.get("FAKE_DIAMOND_DELAY", "0"))
    if delay:
        time.sleep(delay)
    if command == "version":
        print("diamond version " + os.environ.get("FAKE_DIAMOND_VERSION", "2.2.3"))
        return 0
    if command == "makedb":
        source = Path(option(arguments, "--in")).resolve()
        destination = Path(option(arguments, "--db"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(str(source) + "\n", encoding="utf-8")
        return 0
    if command in {"deepclust", "linclust"}:
        database = Path(option(arguments, "--db"))
        source = Path(database.read_text(encoding="utf-8").strip())
        identifiers = fasta_identifiers(source)
        destination = Path(option(arguments, "--out"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        rows = ["centroid\tmember"]
        for index, member in enumerate(identifiers):
            representative = identifiers[(index // 2) * 2]
            rows.append(f"{representative}\t{member}")
        destination.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return 0
    if command == "realign":
        clusters = Path(option(arguments, "--clusters"))
        destination = Path(option(arguments, "--out"))
        members = [line.split("\t") for line in clusters.read_text().splitlines()[1:]]
        rows = ["qseqid\tsseqid\tpident"]
        rows.extend(f"{centroid}\t{member}\t100" for centroid, member in members)
        destination.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return 0
    print(f"unsupported command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
