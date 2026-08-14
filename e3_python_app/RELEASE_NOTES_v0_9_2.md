# ARIA E3 Python reporter v0.9.2

- Repairs the headless Streamlit fixture so `orthogroup_membership`,
  `hierarchical_membership` and `candidate_group_member_sequences` follow the
  production relation contracts.
- Scopes Orthology widget assertions to their actual Streamlit tabs, preserving
  explicit coverage of both log-axis controls and both corrected grouping-level
  labels.
- Fixes the single v0.9.1 test failure in
  `test_app_renders_and_searches`; application logic, data queries and scientific
  results are unchanged.
- The Plotly/Kaleido messages reported alongside the failure are dependency
  deprecation warnings and are not test failures.
