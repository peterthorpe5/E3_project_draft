# E3 structural-alignment and pocket-review package v0.3.2

This reporting-only patch does not recalculate structures, pockets, alignments,
scores, thresholds or candidate decisions.

- The structure viewer's **Fit structure** control is renamed **Fit and centre**.
- The action now restores the default orientation as well as the auto-fit zoom,
  so it remains visibly useful after rotation or zoom.
- An accessible live status message confirms that fitting and centring completed.
- **Reset rotation** now changes orientation only, keeping its purpose distinct
  from the full fit-and-centre action.
- Regression assertions cover the control label, complete reset handler and
  accessible confirmation region.
