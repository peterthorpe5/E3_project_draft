# ARIA E3 Shiny reporter v0.12.0

- Adds a scientifically separate DeepClust/1KP sequence-neighbourhood panel to
  the Orthology page, with coverage metrics, an interactive distribution,
  inherited-seed and 1KP filters, optional evolutionary-group links and
  TSV/Excel downloads.
- Adds independent log-scale controls for both axes of the OrthoFinder and 1KP
  coverage plots; downloaded PDFs use the selected scales.
- Adds runtime PDF controls to compatible legacy pocket-review iframes, so the
  current 3D canvas and complete alignment can be downloaded without
  regenerating the original review bundle.
- Adds the previously missing PDF download for the bounded expression plot.
- Fixes the Orthology taxonomy selector constructing taxon labels before the
  represented-species table existed.
