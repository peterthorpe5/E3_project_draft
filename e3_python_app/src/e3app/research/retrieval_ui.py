"""On-demand public protein sequence and AlphaFold model retrieval controls."""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256

import pandas as pd
import streamlit as st

from e3app.alphafold_hog_bundle import (
    AlphaFoldHogBundle, build_alphafold_hog_bundle, hog_model_candidates,
)
from e3app.errors import AppError
from e3app.exports import safe_file_stem
from e3app.external_hog import prepared_hog_model

from .sequence_retrieval import ProteinSequence, fetch_protein_sequence, sequence_lookup_target


def render_sequence_retrieval(
    *, members: pd.DataFrame, scope: str, key: str,
) -> dict[str, ProteinSequence]:
    """Offer accession lookup for missing member sequences on an explicit click.

    Args:
        members: Missing-member IDs, original identifiers and display labels.
        scope: Current release and HOG identity, for session isolation.
        key: Widget namespace.

    Returns:
        Sequences retrieved in the current session, keyed by exact member key.
    """
    candidates = {}
    for row in members.itertuples():
        target = (sequence_lookup_target(identifier=row.member_raw_identifier)
                  or sequence_lookup_target(identifier=row.identifier))
        if target is not None:
            candidates[row.member_key] = target
    if not candidates:
        if not members.empty:
            st.caption("Missing sequences have no supported public accession. Supply their FASTA "
                       "under Family analysis.")
        return {}
    labels = members.set_index("member_key")["label"].to_dict()
    state_key = f"{key}_retrieved_proteins"
    stored = st.session_state.get(state_key)
    if stored is None or stored[0] != scope:
        stored = (scope, {})
        st.session_state[state_key] = stored
    retrieved = stored[1]
    with st.expander("Retrieve missing protein sequences", expanded=len(members) == 1):
        selected = st.selectbox(
            "Protein accession to retrieve", options=list(candidates), format_func=labels.get,
            key=f"{key}_sequence_member",
        )
        provider, accession = candidates[selected]
        st.caption(f"{provider} lookup · {accession}")
        if st.button("Retrieve protein FASTA", key=f"{key}_fetch_sequence",
                     help="Looks up the selected public accession from the app host."):
            try:
                with st.spinner(f"Fetching {accession} from {provider}"):
                    retrieved[selected] = fetch_protein_sequence(identifier=accession)
            except AppError as exc:
                st.warning(str(exc))
        result = retrieved.get(selected)
        if result:
            st.caption(f"{result.source} · returned accession {result.accession} · "
                       f"{len(result.sequence):,} residues")
            st.download_button(
                "Download retrieved FASTA", data=f">{result.accession}\n{result.sequence}\n",
                file_name=f"{result.accession}.fasta", mime="text/x-fasta",
                key=f"{key}_sequence_fasta", on_click="ignore",
            )
    return {member: retrieved[member] for member in candidates if member in retrieved}


def render_alphafold_retrieval(
    *, members: pd.DataFrame, group_id: str, scope: str, key: str, single: bool = False,
) -> tuple[bytes, str] | None:
    """Fetch current AlphaFold models on demand through the existing model downloader.

    Args:
        members: Recorded HOG members with exact public accessions where available.
        group_id: Selected group, used in download names.
        scope: Current release and selection identity, to prevent stale reuse.
        key: Widget namespace.
        single: Show a single-protein action and return its model for an in-app view.

    Returns:
        Downloaded mmCIF and source URL in single-protein mode, otherwise None.
    """
    supported = members.get("canonical_accession")
    if supported is not None:
        members = members.loc[supported.fillna("").ne("")]
    candidates = hog_model_candidates(members=members)
    if not candidates:
        if single:
            st.caption("AlphaFold Database lookup requires a canonical UniProt accession.")
        return None
    labels = {item.accession: item.label for item in candidates}
    state_key = f"{key}_retrieved_alphafold"
    with st.expander("AlphaFold Database model" if single else "Retrieve HOG member models",
                     expanded=single):
        accession = next(iter(labels)) if single else st.selectbox(
            "Protein model to retrieve", options=list(labels), format_func=labels.get,
            key=f"{key}_alphafold_member",
        )
        fingerprint = (scope, group_id, accession)
        stored = st.session_state.get(state_key)
        if stored is not None and stored[0] != fingerprint:
            st.session_state.pop(state_key)
            stored = None
        st.caption("Retrieves the current AlphaFold Database mmCIF for the selected accession.")
        if st.button("Retrieve AlphaFold model", key=f"{key}_fetch_alphafold"):
            try:
                with st.spinner(f"Fetching AlphaFold model for {accession}"):
                    bundle = build_alphafold_hog_bundle(
                        hog_id=group_id, accessions=[accession], include_pae=False,
                    )
                if bundle.included_count:
                    stored = (fingerprint, bundle)
                    st.session_state[state_key] = stored
                else:
                    record = bundle.records[0]
                    st.info(f"{accession} · {record.detail or record.status}")
            except AppError as exc:
                st.warning(str(exc))
        if stored is None:
            return None
        bundle: AlphaFoldHogBundle = stored[1]
        model = prepared_hog_model(bundle=bundle, accession=accession)
        record = bundle.records[0]
        st.caption(f"AlphaFold Database · {accession} · SHA-256 {sha256(model).hexdigest()}")
        st.download_button(
            "Download AlphaFold model (mmCIF)", data=model,
            file_name=f"{safe_file_stem(value=group_id)}__{accession}_alphafold.cif",
            mime="chemical/x-mmcif", key=f"{key}_model_cif", on_click="ignore",
        )
        st.download_button(
            "Download model source (TSV)",
            data=pd.DataFrame([asdict(record)]).to_csv(sep="\t", index=False),
            file_name=f"{accession}_alphafold_source.tsv", mime="text/tab-separated-values",
            key=f"{key}_model_source", on_click="ignore",
        )
    return (model, record.model_url) if single else None
