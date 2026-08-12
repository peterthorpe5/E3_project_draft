# E3 Python reporter v0.7.4

This sensitivity-analysis release keeps the authoritative 0.50 result, source
values, recorded ranks and every other production gate unchanged.

- The Computational recommendations page now contains a focused slider for the
  final all-members druggability gate.
- The rule is represented exactly as an inclusive minimum-member requirement:
  `minimum_druggability_score >= selected_threshold`.
- The selected list is recalculated from the complete fixed gate intersection;
  lowering the threshold cannot bypass pre-structure, pocket mapping,
  conservation, structural coverage or strict 3D requirements.
- Recorded and selected pass counts are shown together, with a separate table
  identifying groups entering or leaving relative to 0.50.
- The authoritative recommendation table is not rewritten. The recalculated
  list is explicitly labelled as sensitivity analysis and has paired TSV and
  formatted Excel downloads.
- Compatibility sources missing any required gate field are rejected with a
  clear message rather than being misreported as an empty biological result.
- Horizontal box plots show retained selected-pocket scores and individual
  assessed members for each lead cluster reaching the last gate; the reference
  line follows the selected slider value.
- The portable structure viewer's former zoom-only action is upgraded to
  **Fit and centre**, which restores orientation and zoom and confirms the
  action visibly.
- The Python quality gate includes regression tests for the inclusive equality
  boundary, fixed-setting contract, source-field validation, entrant/leaver
  classification, member distributions, rendered slider and legacy viewer
  repair.
