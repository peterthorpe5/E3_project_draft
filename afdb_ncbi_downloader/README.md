# Standalone AlphaFold Database downloader

This Python 3.10+ command retrieves **published AlphaFold Database predictions**.
It does not run AlphaFold inference. It accepts one explicitly selected type of
input per run:

- NCBI RefSeq **protein** accessions, such as `NP_000537.3`;
- numeric NCBI **Gene IDs**, such as `7157`;
- UniProt accessions, such as `P04637`.

The NCBI types are mapped using UniProt's current ID mapping service. The
AlphaFold Database prediction endpoint is then queried using each mapped
UniProt accession. A Gene ID can map to several UniProt proteins; **all**
mappings are recorded and requested. No arbitrary isoform is chosen. IDs with
no mapping and proteins with no published model have distinct statuses.

The script needs Python's standard library only. It accesses
`rest.uniprot.org` for NCBI ID mapping and `alphafold.ebi.ac.uk` for model
metadata and files. It follows redirects only within each original host.
The `examples/` directory contains one-column starter lists for each ID type.

## Example commands

Unpack the supplied ZIP, change to the unpacked directory, then run:

```bash
# One RefSeq protein accession; download mmCIF and available PAE JSON.
python3 fetch_alphafold_models.py \
  --id-type refseq-protein \
  --id NP_000537.3 \
  --output-dir "$HOME/alphafold_refseq_example" \
  --include-pae
```

```bash
# One NCBI Gene ID. The manifest can list more than one mapped protein.
python3 fetch_alphafold_models.py \
  --id-type gene-id \
  --id 7157 \
  --output-dir "$HOME/alphafold_gene_example"
```

```bash
# Several UniProt accessions, requesting PDB rather than mmCIF files.
python3 fetch_alphafold_models.py \
  --id-type uniprot \
  --id P04637 \
  --id Q39090 \
  --format pdb \
  --output-dir "$HOME/alphafold_uniprot_example"
```

For a list, place **one ID per line, without a header**, in a UTF-8 text file.
Blank lines and lines beginning with `#` are ignored:

```text
NP_000537.3
XP_012345678.1
```

```bash
python3 fetch_alphafold_models.py \
  --id-type refseq-protein \
  --ids-file "$HOME/refseq_proteins.txt" \
  --output-dir "$HOME/alphafold_batch_example"
```

`XP_012345678.1` illustrates the input format; it is not a promise that a
mapping or published model exists. Output directories must be **new or empty**
so existing work cannot be overwritten. The `--id-type` applies to every ID in
that run. The default limit is 50 distinct mapped models per run; increase it
explicitly with `--max-models` (maximum 500) if needed. The `--id-type` applies
to every ID in that run. Use separate invocations for different types of ID.
`--help` lists all options.

## Optional exact sequence check

When the input protein sequence is available, provide an unaligned FASTA file
with headers containing the original input IDs. Every requested ID must have
exactly one record:

```text
>NP_000537.3
MEEPQSDPSVEPPLSQETFSDLWKLLPENNVLSPLPSQAMDDLMLSPDDIEQWFTEDPGP
...
```

```bash
python3 fetch_alphafold_models.py \
  --id-type refseq-protein \
  --ids-file "$HOME/refseq_proteins.txt" \
  --sequence-fasta "$HOME/refseq_proteins.faa" \
  --output-dir "$HOME/alphafold_checked_example"
```

The script compares each FASTA sequence to the **UniProt sequence reported in
AlphaFold Database metadata**. It does not download a model when they differ
or when the metadata lack a sequence. This checks the identifier mapping
against the supplied sequence; it is not a coordinate-level residue check.
Without `--sequence-fasta`, the manifest says `NOT_PROVIDED` rather than
claiming sequence identity. Do not use the abbreviated FASTA illustration
above as an actual input record.

## Output and interpretation

```text
OUTPUT_DIR/
  manifest.tsv
  models/
    AF-<UniProt accession>-F1-model_v<version>.cif
    AF-<UniProt accession>-F1-predicted_aligned_error_v<version>.json
```

The manifest retains the input ID and type, every mapped UniProt accession,
model source URL and version, SHA-256 checksum, relative path, PAE outcome,
sequence comparison status, and a clear result status:

- `DOWNLOADED`: an available canonical F1 model was written (or reused within
  this run for another ID mapped to the same UniProt accession);
- `UNMAPPED`: UniProt supplied no accession for this input ID;
- `MODEL_NOT_AVAILABLE`: no canonical F1 model of the requested format was
  available from AlphaFold Database;
- `SEQUENCE_MISMATCH`: the optional input FASTA did not match AlphaFold
  metadata, and no model was downloaded for that input ID;
- `FAILED`: a service, response-validation or file error occurred. Inspect
  `detail` and rerun into a fresh output directory.

The command exits `0` when requests finished, including known unavailable
models; it exits `1` when one or more model requests or explicitly requested
PAE files failed, and `2` for an invalid input or other fatal error. PAE
failures are recorded in `pae_status`. A model file is stored once per UniProt accession even when
several input IDs resolve to it. The canonical F1 selection excludes other
fragments and isoforms; their existence does not imply a matching F1 model.

These are AlphaFold Database predictions and associated confidence data.
There is no AlphaFold 3 pTM/ipTM or AF3 ranking score in these downloads.

## Test

All included tests use stubbed HTTP responses and make **no network calls**:

```bash
python3 -m unittest discover -s tests -v
```

The authoring environment could not connect to UniProt or AlphaFold Database,
so the packaged version was not validated against their live services. The
first small example above is a suitable live smoke test on a machine with
internet access. Check `manifest.tsv` before using any model in an analysis.

API references: [UniProt ID mapping](https://www.uniprot.org/api-documentation/idmapping)
and the [AlphaFold Database API description](https://academic.oup.com/nar/article/50/D1/D439/6430488).
