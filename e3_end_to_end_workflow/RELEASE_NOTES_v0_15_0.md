# E3 end-to-end workflow v0.15.0

This release connects the current full-universe structure-guided chemistry
campaign to the normal workflow DAG and application resource.

- Stage 09c now depends on the completed Stage 09b structural comparison.
- The production template uses generated ligandability and can run the
  checksum-bound all-group chemistry campaign without a hand-written candidate
  manifest.
- Stage 10 imports the chemistry target, pharmacophore, sensitivity, integrated
  evidence and optional ranked-pocket relations into DuckDB.
- Fresh-run validation rejects unresolved placeholders anywhere in the YAML,
  rather than checking only tool and command fields.
- Both application hand-offs continue to use the same integrated DuckDB and
  run-directory contracts.

The strict fresh-run review still requires real, package-compatible adapters for
fresh discovery, orthology and expression acquisition before a new expanded
proteome panel can be submitted. The template keeps these requirements explicit
and fails closed while they are unresolved.
