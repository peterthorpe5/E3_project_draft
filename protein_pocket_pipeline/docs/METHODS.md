# Methods and interpretation

## Question answered

Given a supplied local structure, **where are plausible small-molecule binding
pockets, how do the pocket-finding methods rank them, and how confident is the
predicted local geometry?** Every model is analysed separately. No species
comparison, sequence alignment, ligand docking or disease annotation is required.

## Three distinct outputs

| Method | What is evaluated | Main reported values |
| --- | --- | --- |
| fpocket | Cavities found from the supplied coordinates | Native pocket score, druggability score, volume and all numeric descriptors |
| P2Rank prediction | Sites predicted independently on the protein surface | Native rank, score, calibrated site probability, centre and lining residues |
| P2Rank rescoring | The exact cavities already produced by fpocket | New rank, score and calibrated probability for each original fpocket cavity |

P2Rank prediction uses `-c alphafold`. Its documentation recommends this profile
for predicted structures because it does not use experimental B factors as a
feature. Rescoring uses `-c rescore_2024`, matching the explicit choice in the E3
workflow. P2Rank describes this rescoring profile as experimental. Both choices
are configurable and captured in provenance.

fpocket is executed once per model. P2Rank then reads that retained fpocket
prediction and the identical prepared protein, using its documented two-column
rescoring dataset. Rescoring joins use the original cavity ID (`pocket.4` means
fpocket cavity 4), never the newly assigned rank. Missing or duplicate mappings
are a stage failure, not a guessed join.

## Ranking

`ranked_pockets` contains one row per **fpocket cavity**. Within each model:

1. With complete rescoring, preserve P2Rank's native rescoring rank.
2. With rescoring disabled or unavailable, order all cavities by descending
   fpocket druggability score, breaking ties by original cavity ID.
3. Record the route in `ranking_basis`. Rescoring scores remain NULL when absent.

The independent P2Rank predictions retain their own ranks and appear separately.
No blended score, global model ranking or hidden confidence weighting is added.
The local confidence filter is available alongside the rankings.

fpocket's druggability descriptor and P2Rank's site probability are different
quantities. Neither is a measurement of affinity, proof that a chosen ligand
binds, or a probability that a useful medicine can be developed. Absolute scores
can change with tool versions, structural conformation and model preparation.

## Local confidence

With `--confidence plddt`, the workflow interprets heavy-atom B fields as pLDDT.
Atom values are first averaged within each model residue. Model-level and pocket
mean pLDDT then give each residue equal weight; large side chains do not receive
more weight simply because they have more atoms. This also accommodates AF3's
per-atom pLDDT representation.

For a pocket with N distinct predicted lining residues:

`fraction_ge_threshold = mapped residues with mean pLDDT >= threshold / N`

Unmapped residues stay in N. They do not disappear through an inner join. The
reported mean uses available mapped pLDDT values and must be read with the mapped
and unmapped residue counts. The local confidence outcome is:

| Outcome | Meaning |
| --- | --- |
| `meets_local_confidence_rule` | Every lining residue maps and at least the configured fraction meets the threshold |
| `low_local_confidence` | Complete mapping but insufficient high-confidence lining residues |
| `unmapped_residues` | At least one predicted lining residue does not map to the model |
| `not_assessed` | pLDDT interpretation was deliberately disabled |

Defaults are pLDDT **70** and fraction **0.8**. Change with `--plddt-threshold`
and `--pocket-confidence-fraction`. These are transparent exploratory review
settings, not a published calibration of pocket validity. Low-confidence pockets
are retained rather than removed. With `--confidence none`, derived confidence
values are NULL.

## Within-model prediction overlap

For every fpocket/independent-P2Rank pocket pair in one model, the workflow
calculates lining-residue Jaccard similarity: intersection size divided by union
size. Pairs at or above `--overlap-threshold` (default 0.25) are retained.
`ranked_pockets` records the best such match when present. This is a transparent,
many-to-many descriptive comparison, not an independent experimental validation.
No sequence/structure alignment or corresponding-pocket claim between models is
made. Rescoring is not counted as an independent prediction.

## Structural limits

No pLDDT trimming occurs before pocket detection: trimming can change the surface
and create artificial cavities at cut boundaries. Instead, all predicted pockets
are annotated afterwards. Protein-only preparation removes waters, ions, metals,
other ligands and unselected partner chains. The original model is retained and
these exclusions are flagged. Metal/cofactor-dependent sites and protein partner
effects therefore need separate structural review.

High pLDDT describes local confidence. It does not establish the placement of
distant domains. This release does not ingest PAE, pTM or ipTM, so a cavity formed
between domains can look well ordered locally while its overall arrangement is
uncertain. Inspect this carefully for long, partly disordered proteins such as
BRCA1. Models with several protein chains require an explicit target-chain or
complex selection. AlphaFold sample/seed selection remains the user's choice.

Candidate sites should be inspected in the structure, particularly when scores
are high but confidence is low, a cavity crosses distant domains, or model
preparation removed a biologically relevant component. A successful software run
does not by itself validate a BRCA1 target or ligand.

## Sources

- Le Guilloux V, Schmidtke P, Tufféry P. Fpocket: an open source platform for
  ligand pocket detection. *BMC Bioinformatics* (2009).
  <https://doi.org/10.1186/1471-2105-10-168>
- Schmidtke P, Barril X. Understanding and predicting druggability. A
  high-throughput method for detection of drug binding sites. *J Med Chem* (2010).
  <https://doi.org/10.1021/jm100574m>
- Krivák R, Hoksza D. P2Rank: machine learning based tool for rapid and accurate
  prediction of ligand binding sites from protein structure. *J Cheminform* (2018).
  <https://doi.org/10.1186/s13321-018-0285-8>
- P2Rank 2.5.1 profiles, prediction outputs and rescoring commands:
  <https://github.com/rdk/p2rank/blob/2.5.1/README.md>
- AlphaFold 3 confidence output definitions:
  <https://github.com/google-deepmind/alphafold3/blob/main/docs/output.md>
- EMBL-EBI guidance on local pLDDT and domain orientation:
  <https://www.ebi.ac.uk/training/online/courses/alphafold/inputs-and-outputs/evaluating-alphafolds-predicted-structures-using-confidence-scores/plddt-understanding-local-confidence/>
