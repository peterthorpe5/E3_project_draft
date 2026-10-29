# Pocket conservation and alignment quality

Open **Pocket conservation** in the sidebar, or use the conservation button
beside a saved 3D comparison. It reads existing fit/pocket records without
running an aligner or changing analytical decisions.

1. Choose the reference, compared model and saved alignment.
2. Choose the pocket pair. The original rank-one pair comes first when tested;
   alternatives keep their actual ranks and are labelled explicitly.
3. Read **Pocket position**, **Fold support** and **Conservation rule**.
4. Review centroid/overlap evidence alongside alignment quality.
5. Inspect threshold checks, matched-residue distances and author/FASTA positions.
6. **Open this pocket pair in 3D** selects exactly those pockets in the saved fit.

The all-pair and selected-pair tables offer numeric TSV and formatted Excel.
The selected-pair export includes pocket and alignment metrics together.
**Local pocket confidence and preparation context** retains imported pLDDT,
quality-screen and cut/uncertain-context flags.

| Decision | Evidence used |
| --- | --- |
| Pocket position | Complete lining mapping, centroid distance within the saved limit and sufficient symmetric CA overlap |
| Fold support | Recorded rule using the minimum of the two TM-scores and its saved threshold |
| Conservation rule | Position/fold support, sufficient mutual-nearest lining match and sufficient chemical-group agreement |

These follow existing E3-style workbench evidence rules. They do not establish
experimental binding, conserved function or whole-protein conservation.
Exact amino-acid identity and sequence Jaccard are descriptive, not extra gates.

**Not assessed** means required evidence is absent, such as an excluded pair,
missing chemical comparison or a fit without TM-scores. It differs from a pair
that was assessed and failed a rule. Kabsch can supply positional distances
while fold and combined conservation remain unassessed.

## Distances and their denominators

- **Centroid separation:** distance between pocket lining-CA centroids.
- **Reference/compared lining within radius:** directional fraction of one
  pocket's CA positions close to any CA in the other pocket.
- **Symmetric overlap:** mean of those directional fractions.
- **Mutual-nearest lining match:** twice the unique mutual-nearest match count
  divided by the combined lining-residue count.
- **Mean/median/maximum CA distance:** summaries of saved matched residue pairs,
  already selected within the recorded matching radius.

The distance plot excludes unmatched residues. A small mean distance among a
few matches cannot establish that the whole pocket matches. Read overlap,
mutual-match fraction and mapping evidence too. Neither these distances nor
the coloured lining surface measure empty-cavity volume overlap.

An empty saved match list reports zero recorded matches. If that list was not
supplied, count/distance summaries remain unavailable. Invalid distances are
omitted explicitly and never changed to zero.

## Alignment quality

| Metric | Interpretation |
| --- | --- |
| RMSD | Difference across aligned CA pairs only; a low value over a short fragment can mislead |
| Aligned CA pairs | Number of paired CA positions contributing to the fit |
| Reference/compared TM-score | Normalised to the respective selected fit input |
| Minimum TM-score | Shared score used by the saved fold threshold |
| Reference/compared coverage | Fraction of each selected fit input covered |
| Input scope | Full model, confidence-selected traces or retained/reference-defined region |

For cropped/filtered inputs, these denominators are not the complete parent
protein. Scope, input counts and both coverages therefore remain visible.

Typical defaults are 4 Å matching radius, 8 Å centroid separation, 0.5 overlap,
0.5 minimum TM-score, 0.5 mutual match and 0.6 chemical agreement. The page uses
recorded thresholds. Established defaults for missing legacy fields are
identified; invalid recorded thresholds remain unavailable.

## Offline review

New exports include `comparisons/<comparison_id>/conservation.html` beside the
3D viewer, with the same evidence, TSV downloads and an exact-pocket 3D link.
The main audit includes rank-one centroid/overlap, RMSD, TM-score and coverage.
The existing `review_evidence.xlsx` contains the rank-one/top-k audit.

Regenerate a new review from the finished native resource to update earlier
HTML. No analysis rerun or DuckDB rebuild is needed.
