# ARIA plant E3 Shiny reporter v0.17.0

## Expanded operating help

Every primary tab retains its collapsed **❓ How to use this tab** panel. Each
entry now has a separate **What this tab yields** paragraph identifying the
tables, plots, evidence rows and downloads produced by that page.

## Recorded methods and thresholds

Fourteen scientific tabs now include a separate collapsed **ⓘ Methods and
thresholds** panel. The annotations cover the recorded grant-aligned gates,
ranking weights, OrthoFinder grouping, domain and expression denominators,
AlphaFold Database retrieval and QC, FPocket/P2Rank pocket selection, MAFFT
pocket-region analysis, US-align/TM-align 3D comparison and preliminary
chemistry hand-off.

The structural annotations explicitly record:

- a whole-model AlphaFold QC flag at 0.50 of residues with pLDDT at least 70,
  explicitly distinguished from downstream pocket-local selection;
- pocket mapping 0.95, pocket pLDDT fraction 0.70 and druggability 0.50;
- TM-score 0.50, centroid distance 8 Angstrom and 3D pocket overlap 0.50;
- local residue match 0.50, chemical-group conservation 0.60 and group support
  0.75, with both structural aligners agreeing; and
- the distinction between strict rank-one results and top-five pocket
  sensitivity evidence.

The 3D-alignment panel links to Xu and Zhang (2010), which supports TM-score
0.50 as an approximate fold/topology boundary. It also states that this global
fold threshold does not establish pocket equivalence.

No scientific calculation, threshold, ranking or source resource is changed by
this release.

## Release gate

```bash
cd E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

Any actual dependency, parse, functional or test failure blocks release.
