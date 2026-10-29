"""External-tool preparation controls over existing, read-only project evidence."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import zipfile
from pathlib import Path

import streamlit as st

from .core import WorkbenchError, inside
from .external_tools import (
    EMERALD_URL,
    MOLSTAR_URL,
    PROTEIN_IMAGER_URL,
    RESIDUE_COLUMNS,
    RESOURCES,
    bundle_model_file,
    emerald_pair_url,
    external_records,
    fasta_record,
    model_file,
    pair_fasta,
    pocket_tables,
    prepare_external_bundle,
    table_tsv,
)
from .groups import AF3_INSPECTOR_URL
from .presentation import analysis_label, model_labels, pocket_rank, ranked_pockets

LOGGER = logging.getLogger(__name__)


def external_jump(
    *,
    key: str,
    first: str | None = None,
    second: str | None = None,
    comparison: str | None = None,
    group: str | None = None,
    label: str = "External links and prepared downloads",
) -> None:
    """Open the shared external page with the current model/pair/group selection.

    Args:
        key: Unique button key on the calling page.
        first: Optional exact model:/sequence: record ID.
        second: Optional second record ID; None keeps a single-record hand-off.
        comparison: Optional existing saved fit to retain in the bundle controls.
        group: Optional explicitly supplied HOG/group filter.
        label: User-facing button text.
    """
    if st.button(label, key=key):
        request = {"group": group, "comparison": comparison}
        if first is not None:
            request.update(first=first, second=second)
        st.session_state["external_request"] = request
        st.session_state["pending_navigation"] = "External links"
        st.rerun()


def record_panel(*, root: Path, data: dict, record: dict, role: str) -> None:
    """Show exact local coordinates, pocket selections and available database links.

    Args:
        root: Completed native resource.
        data: Saved project evidence.
        record: Selected model/FASTA-only inventory record.
        role: first or second, used to label and key independent widgets.
    """
    st.subheader(f"{role.capitalize()} selection: {record['label']}")
    st.caption(
        f"Exact ID: {record['record_id']} · input scope: {record['input_scope']} · "
        f"representative FASTA: {record['sequence_id'] or 'unavailable'}"
    )
    if record.get("original_start") is not None:
        st.caption(
            f"Retained original sequence positions: {record['original_start']}–"
            f"{record['original_end']}."
        )
    links = record["public_links"]
    if links["molstar"]:
        left, right = st.columns(2)
        left.link_button(f"Open {role} in Mol* (database model)", links["molstar"])
        right.link_button(f"Open {role} in AlphaFold Database", links["alphafold"])
        st.caption(
            f"Public accession {record['canonical_accession']} comes from "
            f"{record['accession_basis']}. These links open database models, not the "
            "project's saved de novo coordinates."
        )
    else:
        st.caption(
            "No supported canonical UniProt accession is recorded for this selection. "
            "Use the exact local sequence/model downloads below."
        )
    if record.get("source_url"):
        st.link_button(f"Open {role} supplied source", record["source_url"])
    if record["kind"] != "model" or not record["coordinates_available"]:
        st.info(
            "This selection has no saved structure. Its available FASTA can still be"
            " exported."
        )
        return
    model = next(m for m in data["models"] if m["sample_id"] == record["sample_id"])
    try:
        cif = model_file(root=root, model=model, file_format="cif")
        pdb = model_file(root=root, model=model, file_format="pdb")
        left, right = st.columns(2)
        left.download_button(
            f"Download {role} saved model (mmCIF)",
            cif,
            file_name=model["sample_id"] + ".cif",
            key=f"external_{role}_cif",
        )
        right.download_button(
            f"Download {role} saved model (PDB)",
            pdb,
            file_name=model["sample_id"] + ".pdb",
            key=f"external_{role}_pdb",
        )
        st.link_button(f"Open Protein Imager for {role} saved file", PROTEIN_IMAGER_URL)
        st.link_button(f"Open Mol* for {role} saved file", MOLSTAR_URL)
        st.caption("Download the coordinate file above, then load it in the viewer.")
    except (WorkbenchError, OSError) as error:
        LOGGER.warning("Cannot offer saved model download: %s", error)
        st.info(str(error))
        return
    tables = pocket_tables(root=root, data=data, model_ids=[model["sample_id"]])
    pockets = ranked_pockets(
        pockets=[p for p in data["pockets"] if p["sample_id"] == model["sample_id"]]
    )
    pockets.sort(key=lambda p: (p["method"] != "fpocket", p["method"]))
    if not pockets:
        st.caption("No pocket membership was recorded for this model.")
        return
    choices = {(p["method"], p["pocket_id"]): p for p in pockets}
    pocket_key = (
        f"external_{role}_pocket_"
        + hashlib.sha256(record["record_id"].encode()).hexdigest()[:12]
    )
    if st.session_state.get(pocket_key) not in choices:
        st.session_state[pocket_key] = next(iter(choices))
    selection = st.selectbox(
        f"Pocket to highlight for {role} selection",
        list(choices),
        format_func=lambda k: (
            f"{k[0]} · original rank {pocket_rank(pocket=choices[k]) or 'unreported'}"
            f" · pocket {k[1]}"
        ),
        key=pocket_key,
        help=(
            "Use the prepared-model chain/residue labels with these exact saved files."
        ),
    )
    rows = [r for r in tables["residues"] if (r["method"], r["pocket_id"]) == selection]
    st.download_button(
        f"Download {role} selected-pocket residue TSV",
        table_tsv(rows=rows, columns=RESIDUE_COLUMNS),
        file_name=f"{model['sample_id']}_{selection[0]}_pocket_{selection[1]}.tsv",
        key=f"external_{role}_pocket_tsv",
    )
    mapped = [r for r in rows if r["mapping_status"] == "mapped"]
    st.caption(
        f"{len(mapped)}/{len(rows)} lining residues mapped. Select the following "
        "prepared-model labels in the external viewer; the TSV also retains original "
        "author/FASTA positions and unmapped entries."
    )
    if mapped:
        st.code(
            " ".join(f"{r['tool_chain']}:{r['tool_residue_number']}" for r in mapped),
            language=None,
        )


def selection_signature(
    *, root: Path, data: dict, model_ids: list[str], comparison_id: str | None
) -> str:
    """Fingerprint a download request and cheap source-file identity information.

    Args:
        root: Current native resource.
        data: Loaded metadata/revision.
        model_ids: Explicit model-set selection, independent from the sequence pair.
        comparison_id: Optional saved alignment for these same models.

    Returns:
        Signature that invalidates prepared downloads after input/selection changes.
    """
    paths = [root / "project.json"]
    for model in data["models"]:
        if model["sample_id"] in model_ids:
            paths.extend(
                inside(root=root, relative=model[k])
                for k in ("prepared_model", "coordinates")
                if model.get(k)
            )
    if comparison_id:
        comparison = next(
            c for c in data["comparisons"] if c["comparison_id"] == comparison_id
        )
        result_path = inside(root=root, relative=comparison["result_path"])
        paths.append(result_path)
        result = json.loads(result_path.read_text())
        if result.get("mobile_aligned"):
            paths.append(inside(root=root, relative=result["mobile_aligned"]))
    stats = []
    for path in paths:
        try:
            stat = path.stat()
            stats.append((str(path), stat.st_size, stat.st_mtime_ns))
        except FileNotFoundError:
            stats.append((str(path), "missing"))
    payload = [
        str(root.resolve()),
        data.get("revision", 0),
        model_ids,
        comparison_id,
        stats,
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def external_page(*, root: Path, data: dict) -> None:
    """Prepare E3-style public links and exact local inputs without running analyses.

    Args:
        root: Native resource directory.
        data: Loaded saved project evidence.
    """
    st.header("External links and prepared inputs")
    st.markdown(
        "Choose a protein, model or pair, then open a supported populated link or"
        " download its exact inputs. Local de novo models stay tied to their recorded"
        " pocket residue labels. This page does not run prediction or structural"
        " fitting."
    )
    with st.expander("How the links and downloads work", expanded=False):
        st.markdown(
            "**Public links** use a supplied canonical UniProt accession and load a"
            " database record. **Saved-model downloads** use this project's"
            " coordinates. **EMERALD** accepts a pre-filled two-UniProt link;"
            " local/RefSeq sequences use a two-record FASTA. **Protein Imager** takes"
            " the PDB/mmCIF files. **Inspector** takes the prepared model ZIP. Files"
            " are uploaded only when you choose them in the destination website. Pocket"
            " annotations are provided as matching residue TSVs; links do not transfer"
            " them automatically."
        )
    groups = sorted(
        {m.get("hog_id") or m.get("group_id") or "Ungrouped" for m in data["models"]}
    )
    pending = st.session_state.pop("external_request", None)
    if pending:
        st.session_state["external_group"] = (
            pending.get("group") if pending.get("group") in groups else None
        )
    if st.session_state.get("external_group") not in [None, *groups]:
        st.session_state["external_group"] = None
    group = st.selectbox(
        "HOG or model group for external tools",
        [None, *groups],
        format_func=lambda value: (
            "All models and FASTA-only records" if value is None else value
        ),
        key="external_group",
        help=(
            "Uses supplied membership only. FASTA-only records are available in the"
            " all-records view."
        ),
    )
    records = external_records(data=data, group=group)
    lookup = {r["record_id"]: r for r in records}
    selected_records = []
    if records:
        if pending and pending.get("first") in lookup:
            st.session_state["external_first"] = pending["first"]
            st.session_state["external_second"] = pending.get("second")
        if st.session_state.get("external_first") not in lookup:
            st.session_state["external_first"] = records[0]["record_id"]
        first = st.selectbox(
            "First protein or model",
            list(lookup),
            format_func=lambda key: lookup[key]["label"],
            key="external_first",
        )
        others = [k for k in lookup if k != first]
        if "external_second" not in st.session_state or st.session_state[
            "external_second"
        ] not in [None, *others]:
            st.session_state["external_second"] = next(
                (
                    k
                    for k in others
                    if lookup[k]["sequence_id"] != lookup[first]["sequence_id"]
                ),
                next(iter(others), None),
            )
        second = st.selectbox(
            "Second protein or model (optional)",
            [None, *others],
            format_func=lambda key: (
                "No second selection" if key is None else lookup[key]["label"]
            ),
            key="external_second",
        )
        selected_records = [lookup[k] for k in (first, second) if k is not None]
        scope = st.radio(
            "FASTA content",
            ["model_input", "representative_fasta"],
            format_func=lambda value: {
                "model_input": "Selected model inputs",
                "representative_fasta": "Full representative sequences",
            }[value],
            horizontal=True,
            help=(
                "Model inputs preserve any retained-region sequence. Full"
                " representatives use the supplied complete FASTA. FASTA-only records"
                " always use their own saved sequence."
            ),
        )
        try:
            content = (
                pair_fasta(data=data, first=first, second=second, scope=scope)
                if second
                else fasta_record(
                    record=lookup[first], scope=scope, role="first"
                ).encode()
            )
            st.download_button(
                (
                    "Download selected pair FASTA"
                    if second
                    else "Download selected sequence FASTA"
                ),
                content,
                file_name=(
                    "selected_pair.fasta" if second else "selected_sequence.fasta"
                ),
            )
            with st.expander("Copy the selected FASTA"):
                st.code(content.decode(), language=None)
        except WorkbenchError as error:
            st.info(str(error))
        if second:
            url = emerald_pair_url(
                first=lookup[first]["canonical_accession"],
                second=lookup[second]["canonical_accession"],
            )
            if url:
                st.link_button("Open selected pair in EMERALD", url)
                st.caption(
                    "This link loads public canonical sequences. The downloaded local"
                    " model-input FASTA may cover a different region or sequence."
                )
            else:
                st.link_button("Open EMERALD for FASTA upload", EMERALD_URL)
                st.caption(
                    "A populated EMERALD link needs two distinct canonical UniProt"
                    " accessions. Load this pair's exact downloaded FASTA in EMERALD."
                )
            if (
                lookup[first]["sequence_id"]
                and lookup[first]["sequence_id"] == lookup[second]["sequence_id"]
            ):
                st.info(
                    "These are different model records for the same representative"
                    " sequence. Their FASTA sequences may be identical."
                )
        with st.expander("Saved model files and pocket selections", expanded=True):
            columns = st.columns(len(selected_records))
            for column, role, record in zip(
                columns, ("first", "second"), selected_records
            ):
                with column:
                    record_panel(root=root, data=data, record=record, role=role)
    else:
        st.info(
            "No protein/model records are available in this selection. Tool start pages"
            " remain available below."
        )

    st.subheader("Prepare a local model ZIP for external tools")
    models = {
        m["sample_id"]: m
        for m in data["models"]
        if group is None
        or (m.get("hog_id") or m.get("group_id") or "Ungrouped") == group
    }
    labels = model_labels(identifiers=list(models))
    active = [r["sample_id"] for r in selected_records if r["kind"] == "model"]
    context = (str(root), data.get("revision", 0), group)
    if st.session_state.get("external_model_context") != context or pending:
        st.session_state["external_model_set"] = active
        st.session_state["external_model_context"] = context
    left, right = st.columns(2)
    if left.button("Use current model pair", disabled=not active):
        st.session_state["external_model_set"] = active
    if right.button("Select all models in this group", disabled=not models):
        st.session_state["external_model_set"] = list(models)
    st.session_state["external_model_set"] = [
        n for n in st.session_state.get("external_model_set", []) if n in models
    ]
    chosen = st.multiselect(
        "Models to include in the ZIP",
        list(models),
        key="external_model_set",
        format_func=lambda key: labels[key],
        help=(
            "This model set is independent of the exploratory sequence pair. Changing"
            " the pair does not silently change the ZIP selection."
        ),
    )
    fits = [
        c
        for c in data["comparisons"]
        if c["status"] == "complete"
        and len(chosen) == 2
        and set(chosen) == {c["reference"], c["mobile"]}
    ]
    fit_labels = {}
    for fit in fits:
        result = json.loads(inside(root=root, relative=fit["result_path"]).read_text())
        fit_labels[fit["comparison_id"]] = (
            labels[fit["reference"]]
            + " ← "
            + labels[fit["mobile"]]
            + " · "
            + analysis_label(
                engine=result["engine"],
                settings=result.get("settings", {}),
                scope=result.get("scope", ""),
            )
        )
    options = [None, *fit_labels]
    if pending:
        st.session_state["external_fit"] = pending.get("comparison")
    if st.session_state.get("external_fit") not in options:
        st.session_state["external_fit"] = None
    comparison_id = st.selectbox(
        "Coordinate frame for the ZIP",
        options,
        key="external_fit",
        format_func=lambda key: (
            "Original saved model frames (no superposition)"
            if key is None
            else fit_labels[key]
        ),
        help=(
            "A saved alignment is offered only for its exact selected two models. The"
            " recorded mobile transform is reused without running an aligner."
        ),
    )
    signature = selection_signature(
        root=root, data=data, model_ids=chosen, comparison_id=comparison_id
    )
    if st.session_state.get("external_prepared", {}).get("signature") != signature:
        st.session_state.pop("external_prepared", None)
    if st.button(
        "Prepare models for external tools",
        disabled=not any(models[n].get("prepared_model") for n in chosen),
    ):
        st.session_state.pop("external_prepared", None)
        try:
            payload = prepare_external_bundle(
                root=root, data=data, model_ids=chosen, comparison_id=comparison_id
            )
            st.session_state["external_prepared"] = {
                "signature": signature,
                "payload": payload,
            }
        except (WorkbenchError, OSError, RuntimeError) as error:
            LOGGER.exception("External model preparation failed")
            st.error(str(error))
    prepared = st.session_state.get("external_prepared")
    if prepared:
        payload = prepared["payload"]
        st.download_button(
            "Download prepared external-tool ZIP",
            payload,
            file_name="workbench_external_models.zip",
        )
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            manifest = list(
                csv.DictReader(
                    io.StringIO(archive.read("manifest.tsv").decode()), delimiter="\t"
                )
            )
        st.dataframe(
            [
                {
                    k: row[k]
                    for k in ("model_index", "sample_id", "sequence_id", "status")
                }
                for row in manifest
            ],
            hide_index=True,
            width="stretch",
        )
        included = [
            r["sample_id"]
            for r in manifest
            if r["status"] == "included_prepared_target_chain"
        ]
        if included:
            model_id = st.selectbox(
                "Individual model from the prepared ZIP",
                included,
                format_func=lambda key: labels[key],
            )
            content, filename = bundle_model_file(bundle=payload, sample_id=model_id)
            st.download_button(
                "Download this audited bundle model (mmCIF)",
                content,
                file_name=filename,
            )
        st.link_button(
            "Open Multi-Model Inspector for manual ZIP upload", AF3_INSPECTOR_URL
        )
        st.caption(
            "The ZIP includes complete prepared model files, model-index hashes, pocket"
            " and residue TSVs, exact available input FASTA and coordinate-frame audit."
            " Read HANDOFF.txt. Missing PAE/AF3 summary metrics stay unknown."
        )
    with st.expander("Tool start pages and preparation notes", expanded=not records):
        for resource in RESOURCES:
            st.link_button(resource["name"], resource["url"])
            st.caption(resource["purpose"] + " " + resource["preparation"])
