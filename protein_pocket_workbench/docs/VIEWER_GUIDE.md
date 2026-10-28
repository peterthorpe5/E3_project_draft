# Reading structures, pockets and evidence

Version 1.3.0 improves presentation using saved evidence. Predictions, pocket
ranks, coordinates and fitted transforms are unchanged. The same viewer works
with original full-length resources and finished quality-rerun resources.

## Finding and inspecting a pocket

1. Open **Models & pockets** and choose a model. The table is ordered by original
   rank, rather than the cavity's identification number.
2. Choose the pocket evidence: fpocket cavities, independent P2Rank sites or
   same-cavity rescoring, where available. These are different evidence types.
3. The 3D viewer starts with one selected pocket, muted local protein context
   and a bright lining surface. The card identifies the actual rank, pocket ID,
   confidence, available scores and mapped lining-residue count.
4. Use **Selected pocket** for a different site. **Original ranks 1–3**, for
   example, includes only records with those original ranks. Filtering out rank
   one never promotes rank three to rank one. Unknown ranks stay unreported.
5. Click a lining atom or C-alpha marker for original author residue numbering,
   prepared-model numbering, FASTA position and confidence, when available.

**Focus pockets** shows a close-up with local context. The initial context
radius is 12 Å, measured between residue CA atoms in the displayed coordinate
frame. Change the radius for more surroundings. **Show whole models** reveals
the full protein context allowed by the current display filters. **Pockets
only** removes that background. Rotate, full-screen and PNG export are available.

The **Pocket appearance** controls change surface opacity, sticks, markers and
labels. **Protein context and background** controls change trace/cartoon,
protein opacity, confidence colours and the background. A pale background and
muted trace make pockets easier to distinguish. For many selected pockets,
surfaces/labels are limited to the first eight; other lining markers remain.

The surface encloses atoms of the selected **lining residues**. It is not a
measured empty cavity, pocket-volume overlap or experimental binding site.
fpocket's separately reported volume is a predictor metric, not the coloured
volume drawn by this viewer. A high pocket score alone does not establish binding.

## Display filters and analytical preparation

The context pLDDT/position filters hide background residues only. Selected
pocket lining stays visible for inspection, even if its confidence is low.
Use **Only locally confident pockets** to filter the sites themselves. The
page-level preparation/context screen, where available, uses stored cut-boundary,
mapping and uncertain-context annotations.

These controls do not trim an analytical input or change a fit. The HPC quality
workflow creates new contiguous region structures and reruns prediction in a
separate output. Review its **Input quality** audit and retain the original
full-length results as a sensitivity baseline.

## Comparing structures

Choose **Reference model in saved fit**, **Compared model** and **Saved analysis**.
The recorded orientation is preserved; no fitting starts when a selection changes.
RMSD, aligned length, minimum TM-score and both input coverages describe that saved
fit. The coverage denominator is its selected input, which may be a retained region.
A small RMSD over a short fragment is insufficient evidence of a shared whole fold.

The original rank-one pair is the first pocket-pair choice when it exists.
Alternatives retain their own ranks. The 3D viewer initially uses blue for the
reference and orange for the mobile model, so two pockets with the same rank
remain distinguishable. Toggle either model to inspect an obscured surface.
Changing a pocket inside the embedded viewer changes its display; metrics outside
it continue to describe the pair selected in the app above the viewer.

Expand **Similarity matrix and all saved fits** for a larger heatmap. Short labels
retain model replicate/region identity; hover shows full IDs. Rows are reference
models and columns are compared models. Missing measurements remain blank, and
one fit scope/tool/settings combination is displayed at a time. RMSD is offered
when an analysis, such as sequence-guided Kabsch, has no TM-score.

## Reading the structural evidence plot

Select a single scope; the cards, plot and summary table use that same scope.

- **Original rank-one pair:** overlap and point colour both refer to the two
  original rank-one cavities.
- **Best tested member pocket:** reference rank one stays fixed; the highest
  overlap among original member ranks up to the selected limit is plotted.
  Colour refers to this plotted pair, not the strict rank-one decision.
  The top-k support card counts any passing tested pair (including member rank
  one); the highest-overlap pair can still fail another position rule.
- Position support also requires the saved centroid-distance and complete-mapping
  rules. An overlap above the horizontal line alone is insufficient.
- A missing pair or TM-score remains unassessed, and points lacking required
  numerical values are omitted with an explicit count.

Threshold guides use recorded settings. Alternative support does not overwrite
the strict result. Tool agreement additionally needs the same member pocket
under both aligners with matching remaining settings.

Use **Open this fit in Compare structures** on the evidence or model-group page
to inspect the exact saved fit. An explicit HOG/source link is shown only when
supplied; a generic model group is not an inferred orthogroup.

## FASTA alignment and pocket tracks

**Pocket-annotated FASTA** initially shows the first available model per
sequence/input range. It is a display reduction, not a selection of the best
AlphaFold replicate, and never combines pockets across models. Choose
**All model replicates** for every model. Different retained ranges stay separate.

Search/select a sequence, choose the maximum original rank, then click a track
marker to jump to that alignment region. Increase residue font size if needed.
The column ruler counts alignment positions including gaps. Hover/click a letter
for its ungapped FASTA position; the two numbering systems can differ.

Only displayed ranks appear in the legend. Counts and **Download displayed
annotation TSV** follow the current sequence, row, search, rank and confidence
filters. The separate app download contains all prepared tracks (ranks 1–10),
including unmapped rows. Exact source identifiers are retained in both downloads.
An unmapped annotation is not a guessed coordinate. Shared alignment columns
show sequence correspondence, not proof of spatially corresponding pockets.

The JBrowse MSA alignment/tree and Alignment Viewer 2 remain alternative viewers.
Definitions and downloadable methods are under **Methods & glossary**.

## What changed after reviewing the screenshots

| Observed difficulty | Change |
| --- | --- |
| Protein trace dominated very small pocket markers | Selected-pocket close-up, muted context, bright surfaces/sticks/markers and labels |
| Two aligned pockets of the same rank were difficult to distinguish | Reference/mobile colours, offset labels and independent visibility |
| Cavity IDs appeared in place of intuitive ranking | Rank-ordered tables and explicit rank/ID selection labels |
| Long identifiers squeezed the heatmap and fit chooser | Short collision-safe labels, larger matrix and separate model/analysis selectors |
| Best-alternative overlap was coloured by a strict rank-one decision | Separate plot modes with matching metric and decision |
| Global counts and selected-tool evidence had different scope | Scope-consistent cards, plot and summary |
| Original full-length resource lacked an informative quality page | Stored-confidence summary and FASTA/model coverage, with missing preparation audit explained |
| Many replicate rows made the sequence view crowded | Compact range-aware rows, larger text, active legends and selection-aware downloads |

Tests use synthetic examples; the supplied screenshots do not contain the
underlying BRCA1 coordinates. Visual checks therefore confirm the revised controls
and rendering, rather than validating biological pocket predictions.
