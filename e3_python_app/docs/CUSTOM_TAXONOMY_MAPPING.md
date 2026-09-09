# Custom taxonomy mapping

The E3 Python app uses the packaged, reviewed 13-species taxonomy snapshot by
default. A release containing other species, subspecies, varieties or cultivars
can supply a reviewed, tab-separated taxonomy bridge without changing the app.

Launch with:

```bash
e3-python-app \
  --resource-duckdb /path/to/e3_resource.duckdb \
  --taxonomy-map /path/to/reviewed_taxonomy_mapping.tsv
```

Alternatively set `E3_TAXONOMY_MAP`. A header-only starting point is provided as
`docs/taxonomy_mapping_template.tsv`.

## Required contract

Each row maps one exact value from the OrthoFinder membership `species` field.
The following canonical columns or documented aliases are accepted:

| Meaning | Canonical or accepted column names | Requirement |
| --- | --- | --- |
| Workflow label | `source_species_name`, `workflow_species_label`, `orthofinder_species_label` | Required and unique, ignoring case |
| Accepted name | `canonical_species_name`, `accepted_species_name` | Optional; the workflow label is made readable when absent |
| Terminal taxon ID | `taxon_id`, `ncbi_taxon_id`, `resolved_taxon_id` | Required positive integer |
| Ordered lineage IDs | `lineage_taxon_ids` | Required, root-to-terminal, separated by semicolons |
| Ordered lineage names | `lineage_names` | Optional; must align one-for-one with lineage IDs |
| Ordered lineage ranks | `lineage_ranks` | Optional; must align one-for-one with lineage IDs |
| Terminal rank | `taxon_rank`, `rank` | Optional; for example `species`, `subspecies`, `varietas` or `cultivar` |
| Review state | `mapping_status` | Optional; when present, only exact value `REVIEWED` is active |
| Project role | `role` | Optional grouping label for the role selector |

Do not provide two aliases for the same meaning in one file. Taxon IDs, names,
ranks and parent relationships must be internally consistent across lineages.
The terminal taxon may be omitted from `lineage_taxon_ids`; the loader then
appends it using the accepted name and terminal rank. If it is present, it must
be the last lineage ID.

## Scientific safeguards

- Mapping uses the exact source label; the app never guesses spelling variants.
- If `mapping_status` exists, `PENDING_REVIEW`, `AMBIGUOUS`, `UNMAPPED` and blank
  rows stay outside the active authority and are counted in the UI.
- `Only in clade` fails groups containing an unmapped or outside member.
- A cultivar-specific exact selector requires a reviewed terminal taxon ID for
  that cultivar. When the authority has only a species-level taxon ID, the app
  can select the species lineage but cannot invent cultivar-level resolution.
- The mapping changes filtering and reporting only. It does not recalculate
  OrthoFinder groups or imply conserved E3 function.

## Selector semantics

All active selectors are combined with AND:

- `Must contain exact taxon IDs`: each selected terminal ID must occur.
- `Include clades`: each clade must occur; members outside are allowed and
  remain visible.
- `Only in clades`: every mapped member must lie in the intersection of the
  selected clades, and no member may be unmapped.
- `Exclude exact taxon IDs`: no member with the selected terminal ID may occur.
- `Exclude clades and descendants`: no member below any selected clade may
  occur.

The app validates the file at launch and validates lineage meaning before it
runs a taxonomic group query.
