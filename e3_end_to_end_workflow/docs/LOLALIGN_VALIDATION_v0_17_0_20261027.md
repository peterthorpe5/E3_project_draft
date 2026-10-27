# LoL-align and model-selection validation — 27 October 2026

| Component | Version | Tests | Coverage and other gates |
|---|---|---:|---|
| Ligandability pipeline | 0.1.2 | 89 | Named function/test traceability, PEP 8 and shell syntax passed |
| Structural alignment | 0.7.0 | 102 | Branch-inclusive package coverage 92%; style, docstrings and shell syntax passed |
| End-to-end workflow | 0.17.0 | 261 | Branch-inclusive package coverage 90.03%; style, docstrings and Snakemake checks passed |

All **452 tests passed**. Source distributions and wheels for all three components built
successfully with the installed build backend. The complete synthetic Snakemake workflow,
bounded execution, resume and final no-work dry-run checks passed.

## Real external-tool checks

Foldseek revision `463739e0014a1549a527de589102cde98f802f37` was tested using the official
Linux AVX2 archive with SHA-256
`f886374e29ebbf03849cd9c4c8929be00904856dd271627d8c3043607e2af95a`.

The optional real-tool test used the upstream Foldseek `example/d1asha_` structure. It created
a copy with a known non-trivial rigid rotation and translation, ran LoL-align, and verified:

- Mobile coordinates transformed onto the reference within 0.1 Å at every C-alpha position.
- Both normalised geometric TM scores exceeded 0.99 and reported RMSD was below 0.1 Å.
- The complete LoL-only pocket workflow published method-tagged scores and supported the
  expected identical pocket position.
- Offline installation of the pinned archive verified its checksum, revision and LoL capability.

Tests of the software interfaces also cover explicit local no-hit results, invalid/multi-hit
outputs, invalid transforms, unavailable binaries, non-finite metrics, timeout and command
failure, stale-transform prevention, three-method consensus and rejection of unselected chains.

## Workflow and provenance checks

An offline human/plant integration case follows exact sequence authorities, local-model
bytes, pocket selection, coordinate mapping, combined model manifests, preserved plant
references and separate LoL metrics through component aggregation. It also rejects missing
component completion, missing exact sequences, unavailable preserved references and changed
plant reference identities. This contract test uses controlled external-component fixtures;
the actual LoL executable is tested separately as described above.

Method overrides in a standalone extension preserve its immutable parent configuration and
change the task digest when the effective methods change. Cached tasks are reused only under
matching method settings. Preparing another complete workflow configuration preserves the
source YAML and resolves its input paths identically while requiring a new run name.

## Validation environment

Python 3.12.14; BioPython 1.88; DuckDB 1.5.6; PyArrow 24.0.0; PyYAML 6.0.3;
pytest 8.4.2; coverage 7.17.0; psutil 7.2.2; Snakemake 9.27.1.

This validates software integration and coordinate handling. A LoL-align analysis of the
actual 1,972-group E3 campaign remains to be executed on HPC; no new biological candidate
counts or claims of method superiority are established by these tests.
