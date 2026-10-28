# Upstream code and viewer notices

This package is MIT-licensed, with the root Peter Thorpe copyright notice.

The original protein-pocket-pipeline source from E3_project_draft commit
`147c21f152e1e595575dfa07236ef7e160402a64` is privately bundled under
`pocket_workbench._pipeline`. Only import-resource lookup and logger namespace
references were adapted; its preparation, prediction, parsing and ranking
algorithms are reused. It is not installed under the original `protein_pockets`
namespace, so it can coexist with that package.

E3-compatible geometric comparison definitions were inspected in
`e3_structural_alignment` and `e3_python_app/structural_help.py`. The new generic
workbench does not reproduce E3-specific group selection or production gates.

Viewer assets:

- 3Dmol.js **2.5.3**, from the npm release's `build/3Dmol-min.js`; licence at
  `src/pocket_workbench/assets/3Dmol-LICENSE.txt`.
- Alignment Viewer 2 **2.0.0-beta-2**, React **18.2.0**, and its CSS, reused from
  the E3 app's vendored build.
- JBrowse MSA / react-msaview **9.8.0**, reused from that same pinned build.
- Complete upstream viewer notices are in
  `src/pocket_workbench/assets/THIRD_PARTY_NOTICES.txt`.

Every viewer asset has a SHA-256 entry in `assets/checksums.json`. The runtime
verifies third-party library bytes before generating a viewer page. Third-party
software dependencies retain their own installed package licences. No USalign,
MAFFT, fpocket or P2Rank executable binaries are bundled in this ZIP.
