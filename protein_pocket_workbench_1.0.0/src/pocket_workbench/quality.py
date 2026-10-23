"""Conservative, contiguous region selection with explicit confidence evidence."""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path

import gemmi
import numpy as np
from scipy.spatial.distance import cdist

from .core import WorkbenchError

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class CleaningSettings:
    """Auditable heuristics, not validated biological domain definitions.

    Attributes:
        core_plddt: Minimum residue-mean confidence for a core anchor.
        max_low_gap: Maximum internal non-core stretch retained between anchors.
        min_length: Minimum retained contiguous region length.
        min_core: Minimum number of core residues in a region.
        min_fraction: Minimum fraction of core residues in the whole region.
        padding: Boundary padding in residues, without overlapping other regions.
        max_pae: Maximum symmetric PAE admitted for a confident core pair.
        pae_fraction: Required fraction of core pairs passing max_pae.
        require_pae: Reject unassessed PAE instead of silently ignoring it.
        boundary_distance: Cut-end proximity flag in Angstroms.
        uncertain_plddt: Very low confidence used for pocket context flags.
        context_distance: Very-low-confidence proximity flag in Angstroms.
    """

    core_plddt: float = 70.0
    max_low_gap: int = 30
    min_length: int = 50
    min_core: int = 40
    min_fraction: float = 0.5
    padding: int = 5
    max_pae: float = 10.0
    pae_fraction: float = 0.8
    require_pae: bool = True
    boundary_distance: float = 8.0
    uncertain_plddt: float = 50.0
    context_distance: float = 6.0

    def __post_init__(self) -> None:
        """Reject non-finite thresholds, boolean counts and invalid bounds."""
        for name in ("core_plddt", "uncertain_plddt"):
            if (
                not math.isfinite(getattr(self, name))
                or not 0 <= getattr(self, name) <= 100
            ):
                raise WorkbenchError(f"{name} must be in [0, 100]")
        for name in ("max_low_gap", "min_length", "min_core", "padding"):
            value = getattr(self, name)
            if type(value) is not int or value < (
                0 if name in {"padding", "max_low_gap"} else 1
            ):
                raise WorkbenchError(f"Invalid {name}")
        for name in ("min_fraction", "pae_fraction"):
            if (
                not math.isfinite(getattr(self, name))
                or not 0 < getattr(self, name) <= 1
            ):
                raise WorkbenchError(f"{name} must be in (0, 1]")
        for name in ("max_pae", "boundary_distance", "context_distance"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise WorkbenchError(f"{name} must be finite and positive")
        if type(self.require_pae) is not bool:
            raise WorkbenchError("require_pae must be a boolean")


def find_pae_file(*, model_path: Path) -> Path | None:
    """Find a uniquely named AF Server/AF3/AFDB confidence sidecar.

    Args:
        model_path: Original coordinate model, never a prepared/cropped model.

    Returns:
        Exact same-sample sidecar, or None; ambiguity raises an error.
    """
    stem = model_path.stem
    candidates = {
        model_path.with_name(stem + "_confidences.json"),
        model_path.with_name(stem.removesuffix("_model") + "_confidences.json"),
        model_path.with_name(stem + "_pae.json"),
    }
    match = re.fullmatch(r"(.+)_model_(\d+)", stem)
    if match:
        candidates.add(model_path.with_name(f"{match[1]}_full_data_{match[2]}.json"))
        candidates.add(model_path.with_name(f"{match[1]}_confidences_{match[2]}.json"))
    found = sorted(p for p in candidates if p.is_file())
    if len(found) > 1:
        raise WorkbenchError(f"Ambiguous confidence sidecars for {model_path.name}")
    return found[0] if found else None


def read_pae(*, path: Path, residues: list[dict]) -> tuple[np.ndarray, str]:
    """Reconcile PAE token order with one complete selected protein chain.

    Args:
        path: AF3 full/confidence JSON or AFDB PAE JSON.
        residues: Full normalised chain in coordinate order, before cropping.

    Returns:
        Selected-chain square PAE matrix and explicit mapping basis.
    """
    if path.stat().st_size > 1024**3:
        raise WorkbenchError("Confidence JSON exceeds the 1 GiB input bound")
    payload = json.loads(path.read_text())
    if isinstance(payload, list) and len(payload) == 1:
        payload = payload[0]
    if not isinstance(payload, dict):
        raise WorkbenchError("Expected one confidence JSON object")
    matrix = np.asarray(
        payload.get("pae", payload.get("predicted_aligned_error", [])), dtype=float
    )
    if (
        matrix.ndim != 2
        or matrix.shape[0] != matrix.shape[1]
        or not matrix.size
        or matrix.shape[0] > 10000
        or not np.isfinite(matrix).all()
        or np.any(matrix < 0)
    ):
        raise WorkbenchError("PAE must be a finite, non-negative square matrix")
    chains = {str(r["author_chain"]) for r in residues}
    if len(chains) != 1:
        raise WorkbenchError("PAE reconciliation requires one selected protein chain")
    token_chains = payload.get("token_chain_ids")
    token_ids = payload.get("token_res_ids")
    if token_chains is not None:
        if not isinstance(token_chains, list) or len(token_chains) != len(matrix):
            raise WorkbenchError("PAE token chain IDs disagree with matrix dimensions")
        chain = next(iter(chains))
        indices = [i for i, value in enumerate(token_chains) if str(value) == chain]
        if token_ids is not None:
            if not isinstance(token_ids, list) or len(token_ids) != len(matrix):
                raise WorkbenchError("PAE token residue IDs disagree with dimensions")
            lookup = {}
            for i in indices:
                if not re.fullmatch(r"-?\d+", str(token_ids[i])):
                    raise WorkbenchError(
                        "PAE residue tokens must be integer identifiers"
                    )
                key = int(token_ids[i])
                if key in lookup:
                    raise WorkbenchError("Non-unique selected-chain PAE residue tokens")
                lookup[key] = i
            if any(r.get("insertion_code") for r in residues):
                raise WorkbenchError(
                    "Insertion codes cannot be guessed from PAE tokens"
                )
            try:
                indices = [lookup[int(r["author_residue_number"])] for r in residues]
            except KeyError as error:
                raise WorkbenchError(
                    "Selected residues are missing from PAE tokens"
                ) from error
            basis = "explicit_chain_and_residue_tokens"
        else:
            basis = "validated_selected_chain_token_order"
        if len(indices) != len(residues):
            raise WorkbenchError(
                "PAE chain token count does not match protein residues"
            )
    else:
        if matrix.shape != (len(residues), len(residues)):
            raise WorkbenchError(
                "Unlabelled PAE does not match the complete selected chain"
            )
        indices = list(range(len(residues)))
        basis = "complete_single_chain_coordinate_order"
    if token_ids is None and (
        any(r.get("insertion_code") for r in residues)
        or any(
            int(b["author_residue_number"]) != int(a["author_residue_number"]) + 1
            for a, b in zip(residues, residues[1:])
        )
    ):
        raise WorkbenchError(
            "Unlabelled PAE cannot be reconciled through missing residues"
        )
    return matrix[np.ix_(indices, indices)], basis


def select_regions(
    *,
    residues: list[dict],
    pae: np.ndarray | None,
    settings: CleaningSettings,
    explicit: list[dict] | None = None,
) -> list[dict]:
    """Select independent contiguous candidates while retaining short internal loops.

    Args:
        residues: Full-chain residues, including xyz and pLDDT.
        pae: Reconciled full-chain PAE matrix, or None.
        settings: Explicit quality heuristics.
        explicit: Optional inclusive zero-based model-index ranges and region names.

    Returns:
        Retained and rejected range decisions, never stitched coordinate fragments.
    """
    if not residues:
        raise WorkbenchError("No residues to prepare")
    scores = np.asarray([r["plddt"] for r in residues], dtype=float)
    xyz = np.asarray([r["xyz"] for r in residues], dtype=float)
    if not np.isfinite(scores).all() or np.any((scores < 0) | (scores > 100)):
        raise WorkbenchError("Residue pLDDT must be finite in [0, 100]")
    if xyz.shape != (len(residues), 3) or not np.isfinite(xyz).all():
        raise WorkbenchError("Residue coordinates must be finite XYZ values")
    if pae is not None and pae.shape != (len(residues), len(residues)):
        raise WorkbenchError("PAE and residue dimensions disagree")
    if pae is not None and (not np.isfinite(pae).all() or np.any(pae < 0)):
        raise WorkbenchError("PAE must contain finite, non-negative values")
    core = np.flatnonzero(scores >= settings.core_plddt).tolist()
    breaks = np.flatnonzero(np.linalg.norm(np.diff(xyz, axis=0), axis=1) > 5).tolist()
    proposed = []
    if explicit:
        proposed = [dict(r, selection_source="explicit_region") for r in explicit]
    else:
        groups = []
        for index in core:
            new = not groups or index - groups[-1][-1] - 1 > settings.max_low_gap
            if not new:
                previous = groups[-1]
                new = any(previous[-1] <= cut < index for cut in breaks)
                if not new and pae is not None:
                    cross = np.maximum(pae[index, previous], pae[previous, index])
                    new = (
                        float(np.mean(cross <= settings.max_pae))
                        < settings.pae_fraction
                    )
            if new:
                groups.append([])
            groups[-1].append(index)
        for i, group in enumerate(groups):
            previous_end = (groups[i - 1][-1] + group[0]) // 2 if i else -1
            next_start = (
                (group[-1] + groups[i + 1][0]) // 2 + 1
                if i + 1 < len(groups)
                else len(residues)
            )
            proposed.append(
                {
                    "start_index": max(previous_end + 1, group[0] - settings.padding),
                    "end_index": min(next_start - 1, group[-1] + settings.padding),
                    "region_name": f"candidate_{i+1:03d}",
                    "selection_source": "automatic_confidence_candidate",
                }
            )
    decisions = []
    for proposal in proposed:
        start, end = proposal["start_index"], proposal["end_index"]
        if not 0 <= start <= end < len(residues):
            raise WorkbenchError("Explicit region is outside the complete model")
        anchors = [i for i in core if start <= i <= end]
        length, fraction = end - start + 1, len(anchors) / (end - start + 1)
        local_pae = None
        if pae is not None and len(anchors) >= 2:
            square = np.maximum(
                pae[np.ix_(anchors, anchors)], pae[np.ix_(anchors, anchors)].T
            )
            local_pae = square[np.triu_indices(len(anchors), k=1)]
        pae_fraction = (
            float(np.mean(local_pae <= settings.max_pae))
            if local_pae is not None
            else None
        )
        reasons = []
        if length < settings.min_length:
            reasons.append("region_too_short")
        if len(anchors) < settings.min_core:
            reasons.append("too_few_confident_residues")
        if fraction < settings.min_fraction:
            reasons.append("low_confident_fraction")
        if any(start <= cut < end for cut in breaks):
            reasons.append("backbone_gap")
        if pae_fraction is None and settings.require_pae:
            reasons.append("pae_unassessed")
        elif pae_fraction is not None and pae_fraction < settings.pae_fraction:
            reasons.append("low_pae_coherence")
        decisions.append(
            dict(
                proposal,
                model_start=start + 1,
                model_end=end + 1,
                residue_count=length,
                core_residues=len(anchors),
                core_fraction=fraction,
                mean_plddt=float(scores[start : end + 1].mean()),
                pae_fraction=pae_fraction,
                median_core_pae=(
                    float(np.median(local_pae)) if local_pae is not None else None
                ),
                status="rejected" if reasons else "retained",
                reason=";".join(reasons),
                artificial_n_terminus=start > 0,
                artificial_c_terminus=end < len(residues) - 1,
            )
        )
    return decisions


def write_region_cif(
    *, prepared_pdb: Path, residues: list[dict], start: int, end: int, output: Path
) -> None:
    """Copy one contiguous region, restoring original author numbering.

    Args:
        prepared_pdb: Normalised full-chain coordinates.
        residues: Corresponding full-chain residue map.
        start: Inclusive zero-based start index.
        end: Inclusive zero-based end index.
        output: New mmCIF output path.
    """
    if not 0 <= start <= end < len(residues):
        raise WorkbenchError("Region bounds exceed the residue map")
    structure = gemmi.read_structure(str(prepared_pdb))
    if len(structure[0]) != 1 or len(structure[0][0]) != len(residues):
        raise WorkbenchError("Full prepared structure and residue map disagree")
    target, model = gemmi.Structure(), gemmi.Model("1")
    chain = gemmi.Chain(str(residues[start]["author_chain"]))
    for index in range(start, end + 1):
        row = residues[index]
        residue = structure[0][0][index].clone()
        residue.seqid = gemmi.SeqId(
            int(row["author_residue_number"]), row.get("insertion_code") or " "
        )
        chain.add_residue(residue)
    model.add_chain(chain)
    target.add_model(model)
    target.setup_entities()
    target.assign_label_seq_id()
    output.parent.mkdir(parents=True, exist_ok=True)
    target.make_mmcif_document().write_file(str(output))


def pocket_context(
    *, pocket: dict, residues: list[dict], region: dict, settings: CleaningSettings
) -> dict:
    """Flag artificial cut ends and very-low-confidence nearby retained residues.

    Args:
        pocket: Pocket with region-local tool-normalised residue keys.
        residues: Retained region residue map and CA coordinates.
        region: Region decision with artificial-terminus and PAE status.
        settings: Distance and confidence cutoffs.

    Returns:
        Conservative context flags, distances and an explicit quality-screen flag.
    """
    lookup = {r["residue_key"]: r for r in residues}
    lining = [lookup[k]["xyz"] for k in pocket["residues"] if k in lookup]
    complete = len(lining) == len(set(pocket["residues"])) and bool(lining)
    boundary = []
    if region["artificial_n_terminus"]:
        boundary.extend(r["xyz"] for r in residues[:3])
    if region["artificial_c_terminus"]:
        boundary.extend(r["xyz"] for r in residues[-3:])
    uncertain = [r["xyz"] for r in residues if r["plddt"] < settings.uncertain_plddt]
    boundary_distance = (
        float(cdist(lining, boundary).min()) if lining and boundary else None
    )
    uncertain_distance = (
        float(cdist(lining, uncertain).min()) if lining and uncertain else None
    )
    near_cut = (
        boundary_distance is not None
        and boundary_distance <= settings.boundary_distance
    )
    near_uncertain = (
        uncertain_distance is not None
        and uncertain_distance <= settings.context_distance
    )
    return {
        "near_cut_boundary": near_cut,
        "cut_boundary_distance_a": boundary_distance,
        "near_very_low_confidence": near_uncertain,
        "uncertain_context_distance_a": uncertain_distance,
        "quality_screen_pass": bool(
            complete
            and pocket.get("confidence_status") == "meets_local_confidence_rule"
            and not near_cut
            and not near_uncertain
            and region.get("pae_fraction") is not None
        ),
    }
