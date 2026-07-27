# E3 structural alignment v0.1.0

- Adds checksum-bound PDB/mmCIF model resolution from retained ligandability asset manifests.
- Uses both US-align and TM-align to superpose every eligible group member to a deterministic
  reference model, requiring consensus across enabled tools for group support.
- Preserves raw standard output and the rotation/translation matrix for each comparison.
- Measures selected-pocket centroid separation, symmetric residue-neighbour overlap and mean
  bidirectional nearest-residue distance after superposition.
- Publishes paired TSV/Parquet evidence tables, group summaries, formal validation and a complete
  SHA-256 run manifest.
- Supports bounded concurrency, atomic publication, explicit resume/force behaviour, file/console
  logging and retained failed staging directories.
- Treats missing compatible structures as unavailable evidence rather than a biological negative.
