# Inputs

## Simple folder

`--models` reads a **flat** folder of `.pdb`, `.cif` or `.mmcif` files. Each file
must contain exactly one coordinate model. Each filename stem must be unique.
The pipeline processes every supplied file, including multiple predictions of
one sequence. It does not select an AlphaFold sample or seed automatically.

By default, a structure with one protein chain is analysed directly. A structure
with several protein chains needs an explicit selection. To analyse author chain
A in every model, add `--chain A`. Chain names are author identifiers from the
input, including multi-character mmCIF names. A manifest can select a different
chain for each model.

## Manifest TSV

Use `--manifest /path/to/samples.tsv` instead of `--models`. The required columns
are `sample_id` and `model_path`. Optional columns are `sequence_id`, `cluster`
and `chain`. Model paths are absolute or relative to the TSV's directory.

Copy [the example](../examples/manifest.example.tsv) and replace the placeholders.
It contains real tab separators. A manifest is useful when model names and FASTA
identifiers differ, or when models are stored in separate AlphaFold job folders.

```bash
protein-pockets run \
  --manifest /path/to/samples.tsv \
  --fasta /path/to/representatives.fasta \
  --output /path/to/results \
  --p2rank /path/to/p2rank_2.5.1/prank
```

`cluster` is a descriptive label only. No species metadata, sequence alignment
or evolutionary comparison is required for pocket prediction or ranking.

## Optional FASTA

Use ungapped protein sequences. Identifiers are the first whitespace-delimited
token after `>`, without rewriting pipe-delimited accessions. Duplicate/empty IDs,
gaps and terminal stop symbols are rejected. Lower-case sequence is normalised to
upper case. Unused FASTA records are logged, and any referenced missing ID is an
input error.

Without `sequence_id`, a supplied FASTA is matched by `sample_id`. Several model
rows may deliberately use the same `sequence_id`. If no FASTA is supplied, leave
`sequence_id` empty too. FASTA is an identity/coverage check; it does not predict
the structure or the pockets.

The model sequence must match the supplied sequence exactly. For a domain model,
`--allow-fragments` permits a **unique exact contiguous substring** and retains
its one-based positions in the full FASTA. Internal gaps, substitutions,
ambiguous repeated fragments and guessed alignments are rejected. Inspect or
correct the input, or omit optional FASTA if it is not appropriate for that run.

## Complexes and model preparation

Set `chain` to `all`, or use `--chain all`, only for deliberate complex-level
analysis. Interface pockets can then be predicted between protein chains. A
multi-chain complex cannot be mapped to one FASTA using this route; select the
target chain if that mapping is needed.

Prepared models contain protein heavy atoms only. Water, ions, metals, other
ligands and residues without alpha carbons are excluded and counted in a warning.
Alternative atom locations use highest occupancy, with deterministic ties.
Selenomethionine is normalised to methionine. The original input is retained.

Chains and residue numbers are normalised only in the tool input, with a complete
mapping table back to author chain, author number, insertion code and any FASTA
position. No structure alignment, pLDDT trimming, model repair or hydrogen addition
is performed. PDB conversion is explicitly limited to 62 protein chains, 9,999
residues per chain and 99,999 heavy atoms; larger structures fail with a clear
message rather than being truncated.

## Confidence fields

`--confidence plddt` is the default for AlphaFold input. It treats each heavy
atom's B field as pLDDT on a 0–100 scale. This accommodates AF3 per-atom confidence:
values are averaged within each residue, then residue means are summarised.
Values outside 0–100 or non-finite values are rejected. Constant values trigger
a warning because structure conversion may have replaced the confidence values.

Use `--confidence none` if B fields are experimental temperature factors, were
lost on conversion or have an unknown meaning. All pLDDT-derived fields then stay
NULL. AlphaFold summary/PAE JSON files are not ingested by this release.
