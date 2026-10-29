# Protein pocket workbench 1.4.0: methods

## Scope and inputs

The workbench compares local protein models and predicted pockets for any
project. It accepts PDB/mmCIF structures, AlphaFold Server model folders in ZIPs,
protein FASTA, an existing protein-pocket-pipeline report/run/database, aligned
FASTA and matching Newick. It makes no assumptions about species, gene family,
orthology or E3 membership. Import one target protein chain per model.

Uploaded HTML is parsed only for its inert JSON tables; its scripts are never
executed. ZIP paths, symlinks, duplicate names and extraction bounds are checked.
MSA/template folders and AF3 full-data JSON are skipped by ordinary import.
The separate quality-rerun command analyses same-model PAE before cropping;
AF3 summary ranking scores are not used for pocket ranking. The schema is rebuilt in a separate workbench
DuckDB; the original pipeline database remains usable independently.

## Confidence-aware batch rerun

The optional `pocket-workbench-rerun` workflow is a separate analysis alongside
the original full-length predictions. It assesses all original models and
same-model AF Server/AF3 PAE before predicting on contiguous candidate regions.
It never joins disjoint fragments or overwrites the original models/results.
Automatic candidates are not annotated biological domains.

Residue-mean pLDDT ≥70 defines core anchors. Automatic grouping splits at more
than 30 intervening non-core residues, a CA gap >5 Å, or when fewer than 80% of
a new anchor's symmetric PAE links to existing group anchors are ≤10 Å.
Up to five residues are added at each end, without overlapping neighbours.
Accepted candidates need ≥50 residues, ≥40 core residues, ≥50% core content,
no backbone gap and ≥80% of all off-diagonal core pairs with symmetric PAE
≤10 Å. Symmetric PAE is the maximum of the two directional values. Short
internal uncertain loops remain within a contiguous region.

Explicit inclusive parent-sequence/model-index ranges can replace automatic
proposals but still undergo quality checks. Exact FASTA mapping is required
for sequence-coordinate ranges. Missing PAE rejects candidates by default;
the explicit missing-PAE override retains unassessed secondary evidence.
Invalid or irreconcilable PAE is never silently assigned to the protein chain.
The complete QC, retained/rejected decisions and exclusions are recorded.

After the original three predictor stages, the preparation/context screen
requires complete lining-residue mapping, the original local pocket confidence
rule, assessed accepted within-region PAE and no proximity flags. A cut-end
flag means any lining CA lies within 8 Å of the first/last three CAs at an
artificial terminus. An uncertain-context flag means any lining CA is within
6 Å of a retained residue CA with pLDDT <50. These distance proxies are
heuristics; passing does not validate binding or exclude all cropping artefacts.
All original method records/ranks remain available and no rank is promoted.

The region planner aligns complete parent sequences, then requires at least
70% correspondence coverage of each retained range. Ordinal candidate names
do not identify corresponding domains. When both ranges are explicit, their
curated region names must also agree. Computational connected groups are
labelled corresponding-region groups, never HOGs. The default reference is
the most directly connected region, then highest mean pLDDT, then stable ID;
only directly eligible neighbours are fitted. An all-eligible-pairs option
is available. This eligibility remains a sequence-based heuristic.

Both USalign and TMalign fit independent complete retained traces. These
results have scope `cleaned_region`; TM-scores and CA coverage refer to the
cropped input, not the parent protein. Primary pocket comparisons consider
passing **original ranks ≤5**, leaving excluded rank-one evidence unassessed.
The full-representative MSA/tree preserves supplied sequences without models
and separates prediction replicates in pocket annotation tracks.

Cropping does not improve retained coordinates and can remove real interfaces.
No capping, minimisation, refolding or biological assembly reconstruction is
performed. Removed cofactors/ions and other chains remain unassessed. Compare
with the original full-length results and review known/tandem domain context.
The thresholds are workbench policy choices, not a validated segmentation or
ligandability method. Full operational detail is in `docs/QUALITY_RERUN.md`.

## Structure preparation and residue mapping

The original protein-pocket-pipeline 1.0.0 preparation code is bundled under a
private namespace. It selects protein heavy atoms, resolves alternate locations
by occupancy, normalises tool chains and residue numbering, and retains original
author chain/residue/insertion labels. Waters, metals and cofactors are excluded.
Exactly one coordinate MODEL is required. Protein residues need C-alpha atoms;
CA-only traces are not supported by the pocket-prediction preparation code.

For AlphaFold models, B fields are interpreted as pLDDT and averaged over retained
heavy atoms in each residue. Choose `confidence=none` for experimental B-factors;
use a fit pLDDT threshold of 0 when confidence is unavailable. For a completed
pipeline run, its prepared structure and original residue-map TSV are preferred.

FASTA mapping uses exact amino acid sequences. If multiple FASTA records match
identically, the mapping remains ambiguous until an explicit TSV identifies the
record. An explicitly identified unique exact fragment is accepted and its
sequence offset is recorded. Filenames are not used to infer accession mapping.
Without FASTA, identical structure-derived sequences share one sequence record.
Prediction replicates remain separate models and do not automatically become
independent tree tips. Imported duplicate FASTA records remain explicit records.

## Pocket prediction and ranking

New predictions use fpocket 4.2.2, P2Rank 2.5.1 `predict -c alphafold`, and
P2Rank `rescore -c rescore_2024` applied to the same fpocket cavities. The
rescore_2024 profile is experimental. The bundled original pipeline exports the
independent predictions and rescoring separately. fpocket native score,
druggability, volume and P2Rank outputs retain their separate meanings.

Within-model fpocket review rank normally follows P2Rank rescoring, with a
labelled fpocket druggability fallback when rescoring is unavailable. Pocket IDs
and ranks are not cross-model pocket identifiers. Existing imported ranks and
confidence labels are retained. The pipeline's default local-confidence rule
requires no unmapped lining residues and at least 80% of all lining residues with
residue-mean pLDDT >=70. Consult the retained source manifest for the actual rule.

Native P2Rank CSV output is converted to TSV by the bundled pipeline. Workbench
table downloads are TSV; Excel cells retain numeric values. Predicted pockets
and method scores support prioritisation; they do not establish ligand binding,
affinity, selectivity, chemical tractability or therapeutic efficacy.

## Structural correspondence and superposition

First, a global affine-gap amino acid alignment defines candidate corresponding
residues: match +3, mismatch -1, gap opening -8 and gap extension -0.5. A requested
domain is an inclusive reference FASTA range when mapped, otherwise an inclusive
model-sequence range. Its mobile counterpart follows this sequence alignment.
The existing-result build default is independent full target-chain traces: `fit_scope=global`,
minimum pLDDT 0 and a minimum of 12 CA atoms per trace. USalign and TMalign
receive the independent traces, retaining insertions and unequal lengths.
With a positive pLDDT threshold each trace is filtered independently and the
result is labelled as a selected-region fit.

The legacy paired mode retains sequence-corresponding C-alpha residues passing
the pLDDT threshold in both models (default 70 for the compare command).
Kabsch requires paired mode. Original coordinates and pocket membership are
not modified by fit filtering or display-only trimming.

For explicit domain fits, only pockets whose complete lining membership lies
within the selected reference region and its mobile sequence correspondence
are compared. Expand the region if a pocket crosses its boundary. Domain jobs
use one fixed reference against selected models, so coordinates retain a single
reference sequence meaning. The overview matrix filters to one engine and one
complete set of analysis settings.

`auto` uses installed USalign or explicitly selects Kabsch in paired mode.
Production builds default to separate USalign and TMalign runs and fail early
when a requested binary is missing. Both structural aligners supply rigid
matrices, aligned length, RMSD and two length-normalised TM-scores. Conda pins
follow E3: USalign 20241201 and TMalign 20240303. Actual binary checksums,
reported versions, commands, matrices and raw outputs are retained.
Kabsch minimises squared distances over the sequence-corresponding selections
using SVD and a proper rotation; reflection is excluded. It has no TM-score.
Transforms map mobile coordinates to reference coordinates as `mobile @ R.T + t`.
The same transform is applied to every mobile atom for viewing/export.

**TM-scores refer to the selected aligner input region**, potentially a domain
or a confidence-selected subset, rather than necessarily the whole protein.
Both scores are retained, normalised by the two selected input lengths. The
default region-specific fold-support threshold is min(TM1, TM2) >=0.5. Full-model
CA coverage is reported separately for the input model (a crop in quality runs). RMSD depends on fit size and residue
selection. A short, good fit does not establish global fold conservation.

Low pLDDT and uncertain domain orientation are relevant for long or disordered
proteins such as the supplied BRCA1 models. Local pLDDT does not establish the
relative orientation of distant domains. The interface therefore exposes domain
and confidence selection and records the choices with every comparison.

## Pocket comparison in the shared frame

The legacy compare command selects up to 10 locally confident fpocket cavities.
The batch build defaults to five original review ranks without filtering
confidence, keeping rank-one assessability and all confidence labels visible.
With confidence filtering, up to the configured number of cavities are selected,
ordered by review rank after confidence filtering. All selected reference/mobile
pocket combinations are measured; pocket IDs are not assumed to correspond.

For each cavity, one CA coordinate represents every mapped lining residue.
After superposition, with a default residue threshold of 4 Å:

- **Centroid distance:** distance between arithmetic mean lining CA coordinates.
- **Directional fractions:** fraction of one pocket's CA atoms within 4 Å of at
  least one CA atom of the other pocket.
- **Symmetric overlap:** mean of the two directional fractions.
- **Mutual-nearest match fraction:** `2M/(Nref + Nmobile)`, with M mutual-nearest
  CA pairs within 4 Å. Deterministic first-index tie breaking is used.
- **Sequence Jaccard:** shared sequence-corresponding lining residues divided
  by the union; unmatched mobile residues remain in the denominator.

These measure lining-residue proximity and sequence correspondence. They are
not cavity-volume overlaps, chemical similarity scores or binding predictions.
Position-supported status requires complete lining-residue coordinate mapping,
centroid distance <=8 Å and symmetric overlap >=0.5 by default. Fold support is
retained separately and is unavailable for Kabsch. Thresholds are configurable.
No automatic equivalence clusters or universal combined score are inferred.

Mutual-nearest residue correspondences retain original chain/number/insertion
labels, FASTA positions, CA distance, amino acid identity and chemical groups.
Chemical classes follow E3: hydrophobic AVLIMFWY; polar STNQ; positive KRH;
negative DE; special CGP. Identity/chemical fractions use only matched pairs
with exact sequence coordinates and canonical amino acids. Missing sequence
evidence is unknown.

Rank-one results compare original reference rank one with member rank one.
Top-k sensitivity fixes reference rank one and tests original member ranks up
to k. It never replaces the strict result. A missing/excluded rank-one pair
is not assessed. Conserved-pocket evidence additionally requires the saved
fold threshold, mutual-nearest fraction >=0.5 and chemical-group fraction
>=0.6 by default. Dual-aligner support requires both aligners with identical
remaining settings and the same member pocket number. Different supported
alternative pockets do not create agreement.

## Multiple sequence alignment and phylogeny

FAMSA is supplied locally through pyfamsa and uses an UPGMA guide tree with an
explicit thread count. Optional MAFFT runs `--auto --amino --thread N`. The
alignment guide tree is not presented as an inferred phylogeny. Existing aligned
FASTA must preserve each selected ungapped sequence exactly. Tree analyses are
bounded to 200 records and two million input residues.

The default exploratory phylogeny is an unrooted neighbour-joining tree using
protein p-distance. Columns with more than the configured non-canonical fraction
(default 0.5, counting gaps and ambiguous amino acids) are excluded for tree
inference. Pairwise distances use canonical amino acids present in both records;
insufficient comparable sites cause a failure instead of a zero-distance guess.
The displayed full MSA is retained without this column filtering.

Optional bootstrap support resamples retained columns with replacement using
the recorded NumPy seed. Support is the fraction of replicate unrooted splits,
reported as a percentage. With zero replicates, no support is invented. Raw NJ
Newick retains negative branches; display Newick clips negative lengths to zero
and records their count. Both files remain in the resource. Trees are not
maximum-likelihood estimates, species trees or time-calibrated trees.

A user-supplied Newick tree is accepted only when its unique leaf names match
the selected alignment exactly. Its original support values are preserved. The
user should document the external inference method and meaning of those values.

## Viewers, exports and provenance

Bundled third-party libraries are 3Dmol.js 2.5.3, Alignment Viewer 2
2.0.0-beta-2, and JBrowse MSA/react-msaview 9.8.0. Their source versions, licences
and asset SHA-256 digests are included. Viewer pages embed coordinates/alignment
and code locally, with no CDN requirement or protein-data submission. WebGL is
needed for the 3D view. Browser widgets provide camera, visibility, pocket and
confidence-colour controls. Original residue labels are available in TSV/Excel.

The default 3D view focuses on one selected pocket with muted local protein
context. A coloured van der Waals surface covers the selected lining atoms; it
is a visual aid, not an empty cavity volume or a cavity-overlap calculation.
Local context is selected by CA proximity to lining-residue CAs (initially 12 Å),
using coordinates from the displayed PDB after any saved mobile transform.
Aligned pairs use distinct reference/mobile colours by default. Labels and
surfaces are capped at the first eight selected pockets for rendering.

Viewer confidence/position filters affect the protein context, while selected
lining remains visible. Pocket confidence filters apply separately. Display
choices never change saved ranks, predictors, prepared coordinates, transforms
or analytical decisions. Original ranks 1 through k refer to those recorded
ranks, without promotion after filtering; absent ranks remain unreported.

The evidence page separates original rank-one overlap from the best-tested
member-pocket overlap, with colour describing the plotted pair's position rule.
Cards, plots and tables share a selected engine/settings/scope. The similarity
matrix retains the recorded direction of each fit and leaves absent values
blank. No whole-protein interpretation is assigned to a retained-region fit.

Compact pocket-alignment rows show the first available model per sequence/input
range, rather than a best-model choice or a union of predictions. All replicates
remain available. Position labels distinguish MSA columns (including gaps) from
ungapped FASTA positions. Track colours, displayed counts and TSV downloads
follow the active row, rank, sequence and confidence selections.

The resource retains typed materialised DuckDB tables, original pocket records,
prepared PDBs, residue coordinates, comparison transforms and settings, sequence
artifacts, commands, logs, input hashes and tool fingerprints. Concurrent stale
project writes are rejected. Batch fits run concurrently with one parent writer.
The app opens in browsing mode; local workers require explicit operator opt-in.
Final review ZIPs contain offline viewers, annotated alignments, Excel, DuckDB
and a reusable app resource. Only external source/Inspector links require a
network connection.

## Pocket conservation review and external tools

The conservation page separates recorded pocket-position and fold flags from
the existing combined conservation rule: position and fold support, sufficient
mutual-nearest lining match fraction and sufficient chemical-group agreement.
Exact residue identity and sequence Jaccard are descriptive, not extra binary
gates. Missing required values remain unassessed. Alternatives retain original
ranks and never replace the original rank-one conclusion.

Alignment quality includes RMSD, aligned CA pairs, both normalised TM-scores,
their minimum, both selected-input coverages and recorded scope. Mean, median
and maximum distances summarise saved mutual-nearest lining CA pairs already
admitted within the matching radius. Empty and absent distance records are
distinct. No prediction or structural fit is recomputed. Threshold checks use
saved settings; established defaults for missing legacy fields are identified
explicitly, while invalid recorded thresholds remain unavailable.

External links follow the E3-supported Mol*, AlphaFold Database, EMERALD,
Protein Imager and Multi-Model Inspector hand-offs. Populated database links
require an explicit canonical UniProt accession; local/RefSeq/isoform IDs are
not silently rewritten. Public database models/sequences can differ from the
saved de novo inputs. Local coordinate and residue TSV downloads retain exact
prepared tool numbering and available author/FASTA mappings. FASTA exports
distinguish model inputs from full representatives.

Compatibility ZIPs retain model hashes, original pocket ranks, exact available
input sequences and a coordinate-frame audit. An explicitly selected saved fit
reuses its recorded transformed mobile; no new fitting is run. No replacement
database models are fetched and no local files are automatically uploaded.
Missing PAE/AF3 metrics remain unknown. Users load downloaded files manually.
External results do not change the recorded project evidence.

New offline reviews include external-tool and per-fit conservation pages,
linked to the exact selected pocket IDs in the local 3D viewer. Existing native
resources require no DuckDB rebuild or analysis rerun. Previously exported HTML
needs a new review export, which reuses saved evidence.

## References and implementation sources

- [fpocket](https://doi.org/10.1186/1471-2105-10-168)
- [fpocket druggability](https://doi.org/10.1021/jm100574m)
- [P2Rank](https://doi.org/10.1186/s13321-018-0285-8)
- [USalign](https://github.com/pylelab/USalign)
- [FAMSA / pyfamsa](https://pyfamsa.readthedocs.io/)
- [MAFFT](https://mafft.cbrc.jp/alignment/software/)
- [Biopython tree construction](https://biopython.org/wiki/Phylo)
- [3Dmol.js](https://3dmol.org/)
- [Alignment Viewer 2](https://github.com/sanderlab/AlignmentViewer2.0)
- [JBrowse MSA](https://github.com/GMOD/react-msaview)
- [Original E3 app/workflow](https://github.com/peterthorpe5/E3_project_draft),
  inspected at commit `147c21f152e1e595575dfa07236ef7e160402a64`.
