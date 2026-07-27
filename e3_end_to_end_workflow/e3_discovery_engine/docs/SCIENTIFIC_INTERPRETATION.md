# Scientific interpretation and reporting language

## Primary interpretation

The central output is a set of **sequence clusters containing at least one
previously identified E3 candidate**.

The following statement is appropriate:

> The DIAMOND DeepClust workflow grouped protein sequences by configurable
> similarity and coverage criteria. Clusters containing one or more accessions
> from a curated known-E3 candidate set were retained as E3-seeded clusters.

The following statement is not appropriate:

> Every sequence in an E3-seeded cluster is an E3 ligase.

## Why the distinction matters

Sequence clustering identifies similarity, not molecular function. A cluster may
contain:

- a validated E3 ligase;
- a putative orthologue or paralogue;
- another protein sharing only part of the architecture;
- a non-E3 protein recruited through a shared domain;
- a fragmented or misannotated protein model;
- a sequence passing broad clustering criteria but failing strict realignment
  thresholds.

Therefore, raw cluster membership must be combined with additional evidence
before an individual sequence is described as an E3 ligase.

## Evidence levels used by this package

### Level 1: known E3 seed

The sequence matches an accession in the supplied curated seed table. The
strength of this evidence depends on the source and curation quality of that
table.

### Level 2: raw E3-seeded cluster member

The sequence belongs to a raw DeepClust cluster containing at least one known E3
seed. This is broad discovery evidence only.

### Level 3: strict E3-seeded cluster member

The sequence belongs to an E3-seeded cluster and passes every configured exact
post-realignment threshold relative to the cluster representative. This is
stronger sequence-similarity evidence, but still not proof of E3 function.

### Level 4: independently supported E3 candidate

Future integration may add E3-relevant domains, curated GO terms, literature,
orthology, conserved catalytic/substrate-recognition features, expression,
structure and ligandability. These layers are outside the core clustering claim
and should be reported separately.

## Recommended result labels

Use these labels consistently:

- `known_E3_seed`
- `raw_E3_seeded_cluster_member`
- `strict_E3_seeded_cluster_member`
- `independently_supported_E3_candidate` (only when other evidence exists)

Avoid labels such as `confirmed_E3`, `new_E3_ligase` or `E3_orthologue` unless
those statements are supported by appropriate independent analyses.

## Recommended milestone wording

> We delivered a reproducible DIAMOND DeepClust/Snakemake workflow that
> identifies sequence clusters containing at least one previously identified E3
> candidate. The workflow preserves raw cluster membership, performs explicit
> representative-member realignment, applies configurable exact identity,
> coverage, bit-score and e-value thresholds, and provides auditable TSV,
> Parquet, DuckDB and FASTA outputs. Cluster membership is interpreted as
> sequence-similarity evidence and is not assumed to confer E3 function on every
> member.

## Interpreting cluster counts

Cluster count depends on:

- the seed set;
- the sequence database and its redundancy;
- proteome completeness and annotation quality;
- identifier normalisation;
- DIAMOND version;
- masking and clustering parameters;
- exact versus approximate identity;
- whether representatives are included explicitly;
- post-realignment thresholds.

A difference from the inherited count of 6,707 is not automatically an error.
The production and legacy-reproduction modes should be evaluated separately.

## Interpreting the strict subset

The strict subset is not necessarily expected to include every raw member. A
large reduction can indicate that broad DeepClust membership was driven by
local similarity, a shared domain or approximate clustering behaviour. It may
also expose incomplete realignment records. QC should distinguish biological
filtering from missing technical data.

## Functional follow-up

Priority candidates should subsequently be assessed for:

- E3-relevant domain architecture and residue conservation;
- appropriate orthology or phylogenetic support;
- expression in relevant plant tissues and developmental stages;
- AlphaFold confidence and structural comparability;
- conserved and ligandable surface pockets;
- experimental capacity to recruit the ubiquitination machinery and degrade a
  target.
