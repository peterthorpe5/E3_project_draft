# ARIA plant E3 Python reporter v0.13.0

## Independent structural-review shortlist

The former ungated top-HOG page has been replaced by a scientifically explicit
shortlist for the computational team. It returns the top 200 root-level
`N0.HOG…` groups by default and can expand to 500. The recorded rank integrates
discovery, orthology/species, E3-domain and expression evidence. The recorded
pre-structure pass is available as an optional filter.

Existing AlphaFold/model, pocket, ligandability/druggability, mapping,
alignment, conservation and 3D fields are excluded from this shortlist and
from its deterministic tie-breaks. Those published results are unchanged and
remain available in the dedicated structural tabs.

## Richer Threshold explorer

Both threshold-result tables retain substantially more source context,
including available ranks, candidate and seed identifiers, component scores,
species coverage and missing species, domain and expression availability,
discovery composition, inclusion/exclusion reasons and missing-evidence fields.
The bounded result is then enriched with human and Arabidopsis representatives,
accessions and entries, total HOG member/species counts, species composition,
orthogroup/parent-clade links and review/mapping summaries. These fields are
present in the matching TSV and formatted Excel downloads.

## E3 seed catalogue

A new searchable catalogue returns one row per inherited known-E3 seed and
accepts pasted lists of identifiers, names or annotation terms. When the loaded
release publishes `known_e3_seeds`, exact metadata and row provenance are read
from that authority. Older releases reconstruct matched identifiers from the
candidate summaries and place non-one-to-one annotations in explicitly named
`associated_…` fields.

An exact protein sequence is reported only when the seed identifier matches a
sequence-bearing HOG member. The sequence search correctly considers every HOG
member; `is_input_candidate` is not used because it describes candidate status,
not seed status. Available sequences can be downloaded as FASTA, and the table
as TSV or formatted Excel. The dedicated query remains hard-bounded at 100,000
rows and its user-set cap can exceed the normal preview limit.

## Release gate

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

Any functional, style, documentation, shell or 95% branch-coverage failure
blocks release.
