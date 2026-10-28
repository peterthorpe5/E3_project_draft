"""Public tool entry points and the E3 context needed for a manual hand-off."""

from __future__ import annotations

from dataclasses import dataclass

from e3app.alphafold_hog_bundle import AF3_INSPECTOR_URL
from e3app.external_actions import EMERALD_BASE_URL, MOLSTAR_VIEWER_BASE_URL

PROTEIN_IMAGER_URL = "https://3dproteinimaging.com/protein-imager/"


@dataclass(frozen=True)
class ExternalResource:
    """One public tool entry point with its required preparation.

    Attributes:
        name: Public service name shown beside its link.
        url: Service start page, without any selected protein or local path.
        purpose: What the external viewer or analysis can help inspect.
        source_pages: Existing E3 pages providing the necessary selection or data.
        preparation: Manual inputs and limitations of this directory shortcut.
    """

    name: str
    url: str
    purpose: str
    source_pages: tuple[str, ...]
    preparation: str


EXTERNAL_RESOURCES = (
    ExternalResource(
        name="Protein Imager",
        url=PROTEIN_IMAGER_URL,
        purpose=(
            "Inspect a protein structure, highlight pocket residues and prepare molecular views."
        ),
        source_pages=("Ligandability", "3D structures & pockets"),
        preparation=(
            "Load the retained PDB/mmCIF model used for the E3 analysis, then select the "
            "recorded pocket chain and residue identifiers manually. The link opens a blank "
            "workspace; it does not transfer the model or pocket annotations. A rendered "
            "HTML/C-alpha view is not a replacement for the full coordinate file."
        ),
    ),
    ExternalResource(
        name="Mol* Viewer",
        url=MOLSTAR_VIEWER_BASE_URL,
        purpose="Explore molecular structures and residue-level model confidence.",
        source_pages=("3D alignment", "Human & plant 3D alignment"),
        preparation=(
            "Use the existing reference/comparison links on the source pages to open a "
            "selected canonical UniProt accession directly. This directory opens the empty "
            "viewer, where you can load your own coordinate file or choose a database entry."
        ),
    ),
    ExternalResource(
        name="AlphaFold Database",
        url="https://alphafold.ebi.ac.uk/",
        purpose="Inspect available predicted models and their confidence evidence.",
        source_pages=("3D alignment", "Human & plant 3D alignment"),
        preparation=(
            "Use the selected accession links on the source pages, or search by an exact "
            "accession here. A current database model can differ from the version retained "
            "in the E3 release; retain model identity when inspecting recorded pocket residues."
        ),
    ),
    ExternalResource(
        name="EMERALD",
        url=EMERALD_BASE_URL,
        purpose="Explore pairwise sequence alignments and alignment-safe windows.",
        source_pages=("3D alignment", "Human & plant 3D alignment"),
        preparation=(
            "Select the reference/comparison pair on a source page for the pre-populated "
            "UniProt link or exact pair FASTA download. This directory supplies no pair; "
            "enter the intended accessions or sequences manually. Alignment-safe windows "
            "are not direct biological-disorder calls."
        ),
    ),
    ExternalResource(
        name="AlphaFold 3 Multi-Model Inspector",
        url=AF3_INSPECTOR_URL,
        purpose="Compare selected HOG-member models in the external Inspector.",
        source_pages=("HOG model comparison",),
        preparation=(
            "Prepare and download the selected-member ZIP in HOG model comparison, then "
            "upload that ZIP manually to the Inspector. Read the bundle audit for missing "
            "models or PAE. This directory neither prepares a ZIP nor transfers selected models."
        ),
    ),
)
