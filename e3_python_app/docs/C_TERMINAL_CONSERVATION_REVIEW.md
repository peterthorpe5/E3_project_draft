# C-terminal conservation review

Version: 0.18.8. Updated: 3 October 2026.

Open **3 · E3 orthology context → C-terminal conservation**. The default screen
is unchanged: terminal `N`, at least 80% of assessed selected plant proteins,
at least two assessed plant proteins and two assessed plant species, and an
Arabidopsis match when Arabidopsis is selected. Human members never enter the
plant conservation calculation. This page belongs to `e3_python_app`.

## Read the compact group table

| Display field | Exact meaning |
| --- | --- |
| Plant proteins matching / assessed | Matching selected plant proteins divided by those with a published sequence |
| Plant species matching / assessed | Selected species with at least one matching protein divided by selected species with an assessed protein |
| Plant sequences available / published | Assessed selected plant proteins divided by all published selected plant members |
| Arabidopsis matching IDs | Matching reviewed Arabidopsis accessions, falling back to exact source protein IDs |
| Human IDs / comparison | All human identifiers and a separate assessed match state |
| Group rank after structure | Existing pipeline rank; independent of terminal-conservation order |
| Linked E3 families | Annotations of linked E3 source clusters, rather than annotations of every HOG member |

For example, `16/17 (94.1%)` proteins and `10/11 (90.9%)` species are different
measures of the same group. Gene-family expansion can change their relationship.
The stricter count of fully matching assessed species remains in complete
group evidence. An unavailable sequence is excluded from the match fraction
and explicitly included in the sequence-coverage calculation.

Click a compact-table row or use **Orthology group to inspect**. The full group
table and source annotations remain expandable. Group exports contain raw
counts, numeric fractions and identifiers rather than display-only strings.

## Taxonomy controls and denominators

**Plant species included in the conservation calculation** defines the plant
denominator. Choices retain the reviewed accepted species name, NCBI taxon ID
and exact workflow source label. Legacy names such as
`Lycopersicon_esculentum` display the reviewed accepted name
*Solanum lycopersicum* without changing the source identifier.

The taxon-ID controls answer a separate membership question:

| Control | Group requirement |
| --- | --- |
| Must contain exact taxon IDs | A published member from each requested exact taxon; alternate reviewed source labels for one taxon are equivalent |
| Include clades | A published member below each requested clade; outside members allowed |
| Only in clades | Every published member must be reviewed and inside every requested clade |
| Exclude exact taxon IDs | No published member from any requested exact taxon |
| Exclude clades and descendants | No published member below any requested excluded clade |

All active predicates use AND and are applied before result limiting. They test
membership regardless of whether its protein ending matches. Exclusion removes
the entire group; it does not remove a species from the plant denominator.
For example, an only-in-plants filter rejects a HOG containing human members.
Use the plant denominator selector to study plant conservation while retaining
human context. Outside and unresolved members fail an only-in predicate.

Filters are limited to reviewed taxa represented in the active grouping and
sequence authority. Unavailable or contradictory selections fail clearly.
Custom reviewed source aliases for Arabidopsis and human are recognised by
taxon IDs 3702 and 9606. Non-reviewed mappings remain outside the authority.

## Optional gates

**Minimum matching plant species (%)** requires the selected percentage of
assessed species to have at least one matching member. It can reduce the effect
of paralogue expansion in a single species.

**Minimum plant sequence coverage (%)** requires the selected percentage of
published selected plant members to have sequences. It is not a measurement of
complete source-proteome coverage. Both gates default to zero so the original
screen remains unchanged until the user enables them deliberately.

## Screen and species audits

The page calculates the following counts without applying the display limit:

1. Groups in the selected sequence authority and grouping level.
2. Groups containing at least one selected plant member.
3. Groups with at least one assessable selected plant member.
4. Selected-plant groups passing the membership-taxonomy predicates.
5. Groups passing all active conservation, coverage, breadth and taxonomy rules.

The displayed-group count and result limit are separate. Settings/count exports
are available even if no group qualifies. Group downloads contain only the
returned bounded subset; a warning states when additional groups qualify.

The selected-group species audit includes every selected plant, reviewed human
label and represented comparison species. It distinguishes:

- `NOT_REPRESENTED`: no member published in this group/sequence authority;
- `UNAVAILABLE`: a member is published but none has an assessable sequence;
- `NO_MATCH`: assessed members exist but none has the exact ending;
- `SOME_MATCH`: some assessed members match;
- `ALL_MATCH`: every assessed member matches.

Fractions with no assessed denominator are null, not zero. Fully matching
assessed members do not establish that unavailable members also match.
For a group exceeding the 100,000-member preview bound, the app reports the
partial member view and withholds a complete species audit.

## Annotations and exports

Published member descriptions are displayed when present. Linked seed names,
categories and E3/domain context are labelled as source-cluster annotations.
They must not be assigned indiscriminately to non-seed HOG members. Exact
member-domain annotations join accession, source species and linked cluster,
plus primary group ID/type when those fields are published. Missing annotations
remain nullable. No network annotation is retrieved or invented.

Member previews can filter exact matches, assessed non-matches, unavailable
sequences, species, selected plants, Arabidopsis, human and other comparisons.
These filters do not alter the group screen or species audit. Complete loaded
member downloads retain every sequence state and full available sequence;
separately labelled filtered downloads contain only the preview subset.

Downloadable outputs are group, species, member and settings/count TSV and
Excel, plus available selected-group sequences as FASTA. Text tables use tabs.
FASTA omits unavailable sequences while the evidence tables retain those rows.

Candidate-linked resources remain candidate-focused pilot screens. The app
prefers a complete published `orthology_group_member_sequences` authority when
available, but this update does not publish a new scientific resource. A
matching ending does not establish Cereblon binding, ubiquitination, degradation
or accumulation. Confirm the experimental isoform and its C terminus before
laboratory prioritisation.
