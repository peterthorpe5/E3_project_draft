# E3 Shiny reporter v0.11.1

This patch corrects defensive validation in the new OrthoFinder grouping-level
resolver. Unknown, missing, empty or non-scalar group-type values now raise the
documented `Unsupported OrthoFinder group type` error before named-vector
indexing. Unit tests cover both valid mappings and all malformed input classes.

Scientific calculations, filters and displayed results are unchanged from
v0.11.0.
