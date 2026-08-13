# E3 Shiny reporter v0.10.6

This usability release makes the final-gate member druggability box plot
selectable without changing any recorded result or scientific gate.

- A searchable **Evolutionary group to display** selector lists every
  structurally assessed group with retained member-level selected-pocket scores.
- The default is the highest-ranked scored group reaching the final
  druggability gate; when none reaches it, the highest-ranked scored assessed
  group is used.
- **All groups reaching the last gate** preserves the ranked comparison view.
  It is bounded to 30 groups for readable plotting, while every scored assessed
  group remains individually selectable.
- The plot updates immediately when the selected group changes.
- A summary reports the evolutionary-group ID, lead cluster, displayed group
  count, assessed-member count, minimum member score and complete status at the
  selected threshold.
- Statuses distinguish `PASS`, `FAILS DRUGGABILITY` and
  `FAILS ANOTHER FIXED GATE`, preventing a good pocket score from concealing a
  different failed requirement.
- Unit and UI regression tests cover searchable choices, default selection,
  single-group filtering, comparison truncation, summary values and defensive
  validation.

The application remains read-only. The selector filters values already loaded
from the completed resource and does not rerun or rewrite scientific analyses.
