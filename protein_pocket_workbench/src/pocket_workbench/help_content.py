"""Shared searchable glossary, field help and concise scientific methods."""

from importlib.resources import files

GLOSSARY = {
    "Accession": (
        "A database identifier for a sequence or structure. An accession alone does not"
        " prove that two files contain the same sequence; this app maps models by exact"
        " amino acid sequence or an explicit mapping TSV."
    ),
    "Alignment": (
        "A proposed correspondence between residues. A sequence alignment places gaps"
        " between amino acids; a structural alignment matches residues using their 3D"
        " geometry."
    ),
    "Alignment column": (
        "One position in a multiple sequence alignment, including gap characters. It is"
        " different from an ungapped sequence position or an author residue number."
    ),
    "AlphaFold model": (
        "A predicted protein structure. Its local confidence and the relative placement"
        " of domains need assessment before interpreting a pocket."
    ),
    "Angstrom (Å)": (
        "A length unit equal to 0.1 nanometres. Coordinates, RMSD and pocket distances"
        " use Angstroms."
    ),
    "Author residue number": (
        "The chain, residue number and insertion code assigned in the original"
        " structure. Tool-normalised residue numbers are mapped back to these labels."
    ),
    "B-factor": (
        "A structure file field used for atomic displacement in experimental models."
        " AlphaFold exports use it for pLDDT. Select confidence=none for experimental"
        " B-factors and set fit pLDDT to 0."
    ),
    "Bootstrap support": (
        "The percentage of resampled alignment-column datasets that recover a split. It"
        " measures stability under this resampling procedure; it is not the probability"
        " that the split is biologically correct."
    ),
    "C-alpha (Cα / CA)": (
        "The alpha carbon in each amino acid backbone. This app uses one CA coordinate"
        " per lining residue for pocket geometry comparisons."
    ),
    "Cavity": (
        "A geometric depression or enclosed region predicted on a structure. A"
        " predicted cavity is a candidate pocket, not evidence of ligand binding."
    ),
    "Centroid distance": (
        "Distance between arithmetic means of the two sets of pocket CA coordinates"
        " after superposition. This is not a distance between independently predicted"
        " cavity centres."
    ),
    "Chain": (
        "A protein chain in a coordinate model. Import one explicit target chain per"
        " model when structures contain multiple protein chains."
    ),
    "Complete mapping": (
        "Every reported lining residue has a corresponding CA coordinate. Incomplete"
        " pockets cannot receive positional-support status."
    ),
    "Confidence selection": (
        "The residue pLDDT threshold used to choose fit atoms. Changing it changes the"
        " structure region being compared. It does not delete residues from the"
        " original models."
    ),
    "Coverage": (
        "Aligned CA count divided by the complete model CA count. TM-scores are"
        " normalised by the selected fit inputs, which can be much shorter than the"
        " whole protein."
    ),
    "Domain": (
        "A chosen protein region. The app accepts an inclusive reference sequence"
        " range, then obtains mobile residues through the global sequence"
        " correspondence before fitting."
    ),
    "Druggability": (
        "A model-dependent assessment of features associated with small-molecule"
        " binding. fpocket druggability scores do not establish binding affinity,"
        " selectivity or therapeutic efficacy."
    ),
    "DuckDB": (
        "The materialised local analytical database. The workbench builds a separate"
        " schema containing imported evidence, residue coordinates, fits and pocket"
        " comparisons."
    ),
    "FASTA": (
        "A text sequence format with a >identifier header followed by amino acid"
        " letters. Identifiers use the first header token; supplied identifiers are"
        " preserved."
    ),
    "FAMSA": (
        "A protein multiple sequence alignment algorithm, provided locally through"
        " pyfamsa. The alignment guide tree is separate from the neighbour-joining tree"
        " inferred for display."
    ),
    "Fit": (
        "The rigid rotation and translation that superpose selected model coordinates."
        " A fit does not imply that every domain or pocket is conserved."
    ),
    "Fold support": (
        "Whether both USalign TM-scores meet the chosen threshold within the compared"
        " input region. For sequence-guided Kabsch fits this value is unavailable. A"
        " domain fit does not assess whole-protein fold conservation."
    ),
    "fpocket": (
        "A geometry-based cavity detection tool. Native score, druggability score and"
        " volume describe different pocket properties."
    ),
    "Gap": (
        "A dash in an alignment representing an insertion/deletion correspondence. Gaps"
        " and ambiguous amino acids are excluded from pairwise p-distance calculations."
    ),
    "Group": (
        "A user-provided label for related inputs. For an AlphaFold folder it initially"
        " records the parent folder name; it does not imply a species or orthology"
        " relationship."
    ),
    "Jaccard index": (
        "Shared sequence-corresponding lining residues divided by their union."
        " Unmatched mobile residues remain in the denominator. This is distinct from"
        " spatial overlap."
    ),
    "Kabsch": (
        "A least-squares rigid superposition of sequence-corresponding CA atoms. The"
        " app uses a proper rotation and excludes reflection. It does not calculate a"
        " USalign TM-score."
    ),
    "Ligandability": (
        "The potential for a site to bind a ligand. It is a useful prioritisation"
        " concept, but pocket prediction alone does not measure experimental ligand"
        " binding."
    ),
    "Local pocket confidence": (
        "The imported pipeline's assessment of lining-residue pLDDT. Its default rule"
        " is at least 80% of all lining residues with residue-mean pLDDT >=70 and no"
        " unmapped residues. The original run settings are retained."
    ),
    "MAFFT": (
        "An optional external multiple sequence aligner. The app runs --auto --amino"
        " with an explicit thread count and retains the command and stderr log."
    ),
    "Mapping TSV": (
        "An optional tab-separated file with unique sample_id and sequence_id columns,"
        " and optional chain/group_id. It resolves identical FASTA records or"
        " explicitly maps a unique exact sequence fragment."
    ),
    "mmCIF": (
        "A structure format supporting richer identifiers than PDB. The app accepts"
        " AlphaFold mmCIF models and prepares tool-compatible PDBs with residue maps."
    ),
    "Model replicate": (
        "One of several predictions for a sequence. All models remain individually"
        " accessible, while identical derived sequences share one sequence record for"
        " alignment/tree analysis."
    ),
    "MSA": (
        "Multiple sequence alignment: proposed residue correspondence across several"
        " proteins. Ambiguous or disordered regions may be difficult to align reliably."
    ),
    "Mutual-nearest match fraction": (
        "2M/(Nref+Nmobile), where M is the number of mutual-nearest CA pairs within the"
        " residue distance threshold. It is a geometric one-to-one residue fraction,"
        " not amino acid identity."
    ),
    "Neighbour joining (NJ)": (
        "An exploratory distance-tree algorithm. This app uses protein p-distance with"
        " pairwise deletion after column filtering. It does not perform"
        " maximum-likelihood inference or molecular dating."
    ),
    "Newick": (
        "A text format for tree topology, branch lengths and optional support values."
        " Imported tip names must match the selected alignment identifiers exactly."
    ),
    "P2Rank": (
        "A machine-learning pocket predictor. Independent predictions and rescoring of"
        " fpocket cavities are distinct analyses with separate scores."
    ),
    "p-distance": (
        "The fraction of differing amino acids among canonical amino acid columns"
        " comparable for a sequence pair. It is not corrected for repeated"
        " substitutions."
    ),
    "PAE": (
        "Predicted aligned error: AlphaFold confidence about relative residue"
        " positions. PAE is not imported or analysed by this release; pLDDT alone does"
        " not establish domain orientation."
    ),
    "pLDDT": (
        "Predicted local confidence on a 0–100 scale; larger values indicate greater"
        " local confidence. AlphaFold 3 residue confidence is averaged over retained"
        " heavy atoms by the original preparation code."
    ),
    "Pocket lining residue": (
        "A residue associated with a predicted pocket. Its CA represents a coarse"
        " location; side-chain chemistry and true cavity-volume shape require further"
        " assessment."
    ),
    "Position supported": (
        "Every lining residue maps, the pocket centroid distance is below its chosen"
        " limit, and symmetric CA overlap meets its chosen threshold after"
        " superposition. Interpret alongside fit coverage, RMSD, local confidence and"
        " the fit region."
    ),
    "Probability": (
        "A calibrated method-specific tool output when available. P2Rank probabilities"
        " do not represent the probability that a drug will bind or work."
    ),
    "Provenance": (
        "Recorded inputs, checksums, software versions, commands and analysis settings"
        " used to make a result traceable."
    ),
    "Reference / mobile": (
        "The reference stays fixed; a fitted rotation and translation move the mobile"
        " model into the reference coordinate frame."
    ),
    "Rescore": (
        "P2Rank scoring of the same fpocket cavities. The rescore_2024 profile is"
        " experimental; its ordering is distinct from independent P2Rank pocket"
        " predictions."
    ),
    "Review rank": (
        "A within-model ordering of fpocket cavities, normally by P2Rank rescoring with"
        " a labelled fpocket fallback. Rank 1 in two models does not imply the same"
        " pocket location."
    ),
    "RMSD": (
        "Root-mean-square distance between fitted/aligned CA atoms, in Angstroms. It"
        " depends on which residues and how many atoms are aligned; a low value over a"
        " short fragment is not whole-protein similarity."
    ),
    "Sequence position": (
        "A one-based index in the representative protein FASTA when mapped exactly. For"
        " an unmapped model the app labels positions as model sequence indices."
    ),
    "Superposition": (
        "Putting structures into one coordinate frame using a fitted rotation and"
        " translation. Coordinates from independent models cannot be compared spatially"
        " before this step."
    ),
    "Symmetric overlap": (
        "Mean of the reference-to-mobile and mobile-to-reference fractions of pocket CA"
        " atoms within the residue distance threshold. It is a lining-residue proximity"
        " measure, not a cavity-volume overlap."
    ),
    "TM-score": (
        "A structural similarity score reported by USalign, normalised by an input"
        " structure length. This app retains both normalisations for the selected"
        " inputs and does not substitute a Kabsch-derived proxy."
    ),
    "TSV": (
        "Tab-separated values, the plain-text table format used for all exported"
        " tables."
    ),
    "USalign": (
        "An optional external structural aligner used to obtain a geometry-based"
        " superposition and both TM-scores. Its transform, stdout, command and"
        " executable checksum are retained."
    ),
    "Volume": (
        "The native fpocket cavity-volume estimate in cubic Angstroms. This app's"
        " cross-model overlap measure compares lining CA coordinates rather than that"
        " volume."
    ),
}

GLOSSARY.update(
    {
        "Candidate region": (
            "A contiguous input range selected by confidence/PAE heuristics or an "
            "explicit range TSV. An automatic candidate is not a validated biological "
            "domain; cutting changes surface geometry and may remove real interfaces."
        ),
        "Cut boundary": (
            "A new model terminus created by cropping. A pocket is flagged when any "
            "lining CA is within 8 Å of the first/last three CAs at a cut end. This "
            "heuristic cannot detect every artefact caused by removing a region."
        ),
        "Preparation quality screen": (
            "Complete pocket mapping, the original local pocket confidence rule, "
            "assessed within-region PAE and no cut-boundary or very-low-confidence "
            "context flags. Nearby uncertain context uses lining-to-residue CA "
            "distances (6 Å; pLDDT <50). Passing is not experimental validation."
        ),
        "Corresponding region group": (
            "A computational connected group of retained ranges linked through full "
            "parent-sequence alignments with at least 70% mutual region coverage. "
            "It is not an inferred domain, species assignment or HOG. Reference "
            "comparisons require a direct qualifying link."
        ),
        "HOG": (
            "Hierarchical orthogroup: an explicitly supplied evolutionary membership. "
            "A generic model group is not automatically a HOG."
        ),
        "Slurm": (
            "The Dundee cluster scheduler. The supplied batch script reserves compute "
            "resources and builds the finished data before the app opens it."
        ),
        "Global fit": (
            "A structural aligner compares independent full target-chain traces. A "
            "positive confidence cutoff or domain range changes the fit scope."
        ),
        "Paired fit": (
            "Fit input is restricted to sequence-corresponding residues. Kabsch uses "
            "this mode and cannot supply a structural-aligner TM-score."
        ),
        "Top-k sensitivity": (
            "Keep the reference rank-one cavity fixed and test original member "
            "pocket ranks up to k. This does not replace the rank-one result."
        ),
        "Chemical-group conservation": (
            "Fraction of comparable mutual-nearest pocket residue pairs in the same "
            "E3 chemical class: hydrophobic, polar, positive, negative or special. "
            "Exact sequence coordinates are required; missing evidence is unknown."
        ),
        "Aligner agreement": (
            "USalign and TMalign must support the same member pocket with identical "
            "remaining fit settings. Different supported alternatives do not agree."
        ),
        "TMalign": (
            "TM-align structural superposition. Its independently calculated "
            "transform, "
            "TM-scores, RMSD and raw output remain separate from USalign evidence."
        ),
        "Display trimming": (
            "Hide low-confidence or terminal protein context in the viewer only. "
            "Selected pocket lining stays visible for inspection. This does not "
            "change saved coordinates, pocket ranks, fits or analytical conclusions."
        ),
        "Local protein context": (
            "Protein residues within the selected CA distance of any selected "
            "lining-residue CA, initially 12 Å. Geometry uses the displayed fitted "
            "coordinates. Confidence and position filters affect this background, "
            "not the analytical input or selected pocket lining."
        ),
        "Compact alignment rows": (
            "A display of the first available model per representative sequence and "
            "input range. It neither chooses the best AlphaFold replicate nor "
            "combines pocket annotations. All model replicates remain selectable."
        ),
        "Best tested member pocket": (
            "The original member pocket with the highest saved overlap with reference "
            "rank one, among tested member ranks 1 through k. Its plot colour uses "
            "that same pair's position rule. It may differ from the original "
            "rank-one result and does not replace that conclusion."
        ),
        "Lining-atom surface": (
            "A visual surface around atoms of selected pocket-lining residues. It is "
            "not a computed cavity boundary or cavity-volume overlap."
        ),
        "Inspector model index": (
            "A zero-based model number in a compatibility ZIP. manifest.tsv maps it "
            "back to the original sample, sequence and group identifiers."
        ),
        "Portable review": (
            "A downloaded folder with index.html, offline viewers, Excel, TSV, "
            "DuckDB "
            "and a native app resource ZIP. It needs no cluster account."
        ),
    }
)


def field_help(*, term: str) -> str:
    """Return the shared glossary definition used by question-mark help.

    Args:
        term: Exact glossary term.

    Returns:
        Plain-language field definition.
    """
    return GLOSSARY.get(
        term, "See Methods and glossary for this field's interpretation."
    )


def methods_text() -> str:
    """Read the installed, downloadable methods document.

    Returns:
        Versioned methods Markdown.
    """
    return (
        files("pocket_workbench")
        .joinpath("content", "METHODS.md")
        .read_text(encoding="utf-8")
    )


def glossary_rows() -> list[dict]:
    """Return alphabetically sorted glossary records for app/TSV/Excel exports.

    Returns:
        Term and definition records.
    """
    return [
        {"term": term, "definition": GLOSSARY[term]}
        for term in sorted(GLOSSARY, key=str.casefold)
    ]
