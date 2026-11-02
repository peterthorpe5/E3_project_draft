"""Complete, provenance-preserving E3 Top-N to external DeepClust batch mapping."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path

import pandas as pd

from e3app.data import list_relations, quote_identifier, relation_columns

from .common import ResearchConfig, ResearchError, bounded_number, file_sha256, safe_path
from .jobs import submit_job
from .remote import exchange

LOGGER = logging.getLogger(__name__)
MAX_INPUT_ROWS = 200_000
MAX_MANIFEST_BYTES = 50_000_000
GROUP_COLUMNS = (
    "source_group_key", "source_group_type", "source_group_id", "source_rank",
    "source_relation",
)
INPUT_COLUMNS = (*GROUP_COLUMNS, "input_id", "raw_identifier", "species", "source_context")


@dataclass(frozen=True, kw_only=True)
class CampaignSelection:
    """Every selected published primary group and its complete identifier expansion."""

    groups: pd.DataFrame
    inputs: pd.DataFrame


def select_campaign(*, connection: object, maximum_groups: int = 200) -> CampaignSelection:
    """Select complete published primary HOG/orthogroup inputs independently of preview limits.

    Args:
        connection: Immutable E3 resource connection.
        maximum_groups: Number of distinct groups in recorded pre-structure rank order.

    Returns:
        Group inventory, including groups without identifiers, and complete member/seed inputs.

    Raises:
        ResearchError: If authoritative ranking/membership contracts or complete bounds fail.
    """
    maximum = bounded_number(
        value=maximum_groups, label="Top E3 groups", minimum=1, maximum=1000, integer=True,
    )
    relations = set(list_relations(connection))
    source, rank = "", ""
    for relation in ("final_evolutionary_candidate_prioritisation",
                     "evolutionary_candidate_group_ranking"):
        if relation not in relations:
            continue
        columns = set(relation_columns(connection, relation))
        selected_rank = next((field for field in (
            "prestructure_evolutionary_group_rank", "evolutionary_group_rank",
        ) if field in columns), "")
        if selected_rank and {"primary_group_id", "primary_group_type"}.issubset(columns):
            source, rank = relation, selected_rank
            break
    if not source:
        raise ResearchError("Top-N batch mapping requires the published evolutionary-group ranking")
    ranking = connection.execute(
        "SELECT * FROM " + quote_identifier(source)
        + " WHERE TRY_CAST(" + quote_identifier(rank) + " AS DOUBLE)>0 ORDER BY TRY_CAST("
        + quote_identifier(rank) + " AS DOUBLE),primary_group_type,primary_group_id LIMIT ?",
        [maximum],
    ).fetchdf()
    if ranking.empty:
        raise ResearchError("The published evolutionary-group ranking contains no ranked groups")
    group_rows = []
    for record in ranking.to_dict(orient="records"):
        group_type, group_id = str(record["primary_group_type"]), str(record["primary_group_id"])
        if group_type not in {"HIERARCHICAL_ORTHOGROUP", "ORTHOGROUP"} or not group_id.strip():
            raise ResearchError("Published Top-N contains an unsupported or empty group identifier")
        source_rank = bounded_number(
            value=record[rank], label="Published group rank", minimum=1,
            maximum=100_000_000, integer=True,
        )
        group_rows.append(dict(zip(GROUP_COLUMNS, (
            f"{group_type}:{group_id}", group_type, group_id, source_rank, source,
        ), strict=True)))
    groups = pd.DataFrame(data=group_rows)
    if groups["source_group_key"].duplicated().any() or groups["source_rank"].duplicated().any():
        raise ResearchError("Published evolutionary-group identities and ranks must be unique")
    inputs = []
    connection.register(view_name="research_campaign_groups", python_object=groups)
    try:
        for group_type, relation in (
            ("HIERARCHICAL_ORTHOGROUP", "hierarchical_membership"),
            ("ORTHOGROUP", "orthogroup_membership"),
        ):
            if group_type not in set(groups["source_group_type"]):
                continue
            if relation not in relations:
                raise ResearchError(f"Complete Top-N expansion requires {relation}")
            columns = set(relation_columns(connection, relation))
            if not {"group_id", "raw_identifier"}.issubset(columns):
                raise ResearchError(f"{relation} lacks exact group/member identifiers")
            accession = ("nullif(trim(CAST(m.parsed_accession AS VARCHAR)),'')"
                         if "parsed_accession" in columns else "NULL")
            species = next((field for field in ("species", "species_column") if field in columns),
                           "")
            species_sql = "CAST(m." + quote_identifier(species) + \
                " AS VARCHAR)" if species else "''"
            root = (" AND lower(m.record_type) IN ('root_hog','hierarchical_orthogroup')"
                    if group_type == "HIERARCHICAL_ORTHOGROUP" and "record_type" in columns else "")
            frame = connection.execute(
                "SELECT DISTINCT g.*,coalesce(" + accession
                + ",nullif(trim(CAST(m.raw_identifier AS VARCHAR)),'')) AS input_id, "
                "CAST(m.raw_identifier AS VARCHAR) AS raw_identifier," + species_sql
                + " AS species,'PUBLISHED_GROUP_MEMBER' AS source_context "
                "FROM research_campaign_groups g JOIN " + quote_identifier(relation)
                + " m ON CAST(m.group_id AS VARCHAR)=g.source_group_id "
                "WHERE g.source_group_type=?" + root + " LIMIT ?",
                [group_type, MAX_INPUT_ROWS + 1],
            ).fetchdf()
            inputs.extend(frame.to_dict(orient="records"))
    finally:
        connection.unregister(view_name="research_campaign_groups")
    seed_fields = [field for field in ("candidate_accessions", "lead_candidate_accessions")
                   if field in ranking]
    for record, context in zip(ranking.to_dict(orient="records"), group_rows, strict=True):
        for field in seed_fields:
            value = record[field]
            if pd.isna(value):
                continue
            for identifier in str(value).split(";"):
                if identifier.strip():
                    inputs.append({
                        **context, "input_id": identifier.strip(), "raw_identifier": identifier,
                        "species": "", "source_context": "RECORDED_CANDIDATE_ACCESSION",
                    })
    frame = pd.DataFrame(data=inputs, columns=INPUT_COLUMNS).fillna("").drop_duplicates()
    frame = frame.loc[frame["input_id"].astype(str).str.strip().ne("")].reset_index(drop=True)
    frame = frame.sort_values(by=["source_rank", "input_id", "species", "source_context"])
    if len(frame) > MAX_INPUT_ROWS:
        raise ResearchError("Complete Top-N mapping exceeds 200000 input rows; select fewer groups")
    LOGGER.info("Selected %d published groups and %d complete identifier/context rows",
                len(groups), len(frame))
    return CampaignSelection(groups=groups, inputs=frame)


def _snapshot(*, config: ResearchConfig, frame: pd.DataFrame) -> tuple[str, str]:
    """Persist immutable input TSV bytes addressed by checksum outside published resources."""
    data = frame.to_csv(sep="\t", index=False, lineterminator="\n").encode()
    if len(data) > MAX_MANIFEST_BYTES:
        raise ResearchError("Campaign input manifest exceeds 50 MB")
    digest = hashlib.sha256(data).hexdigest()
    relative = f"campaign_inputs/{digest}.tsv"
    path = safe_path(root=config.workspace, relative=relative)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with path.open(mode="xb") as handle:
            handle.write(data)
    except FileExistsError:
        if file_sha256(path=path) != digest:
            raise ResearchError("Existing campaign snapshot checksum differs")
    return relative, digest


def submit_campaign(
    *, config: ResearchConfig, selection: CampaignSelection, transport: str,
) -> str:
    """Queue a complete campaign using immutable manifests instead of large web-process requests.

    Args:
        config: Writable sidecar and established connection profile.
        selection: Published group inventory and complete identifiers.
        transport: worker or ssh, selected explicitly in the interface.

    Returns:
        Durable mapping job ID. No external query is executed in this function.

    Raises:
        ResearchError: If selection or transport is invalid.
    """
    if transport not in {"worker", "ssh"} or selection.groups.empty:
        raise ResearchError("Select published groups and a worker/ssh connection")
    if not set(GROUP_COLUMNS).issubset(selection.groups) or not set(INPUT_COLUMNS).issubset(
        selection.inputs
    ):
        raise ResearchError("Campaign manifests are missing source identifiers")
    groups_path, groups_hash = _snapshot(config=config, frame=selection.groups)
    inputs_path, inputs_hash = _snapshot(config=config, frame=selection.inputs)
    return submit_job(
        workspace=config.workspace, operation="deepclust_map",
        parameters={
            "transport": transport, "groups_manifest": groups_path,
            "groups_sha256": groups_hash, "inputs_manifest": inputs_path,
            "inputs_sha256": inputs_hash,
        },
    )


def _read_snapshot(
    *, config: ResearchConfig, parameters: dict, kind: str, columns: tuple[str, ...],
) -> pd.DataFrame:
    """Read only a bounded, checksum-matched campaign manifest inside the job sidecar."""
    path = safe_path(root=config.workspace, relative=str(parameters[f"{kind}_manifest"]))
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ResearchError("Campaign manifest exceeds its size bound")
    if file_sha256(path=path) != parameters[f"{kind}_sha256"]:
        raise ResearchError("Campaign source manifest checksum differs")
    frame = pd.read_csv(filepath_or_buffer=path, sep="\t", dtype=str, keep_default_na=False)
    if not set(columns).issubset(frame) or len(frame) > MAX_INPUT_ROWS:
        raise ResearchError("Campaign manifest schema or row bound is invalid")
    return frame


def run_campaign(
    *, config: ResearchConfig, parameters: dict, output: Path,
) -> dict[str, Path]:
    """Resolve all campaign inputs in bounded command-line batches and retain missing evidence.

    Args:
        config: Current worker profile.
        parameters: Queued immutable input snapshots and transport.
        output: Owned job artifact directory.

    Returns:
        Complete source, mapping, group-status and size-ranked cluster inventories.

    Raises:
        ResearchError: If snapshots, contexts or remote mapping results are inconsistent.
    """
    groups = _read_snapshot(config=config, parameters=parameters,
                            kind="groups", columns=GROUP_COLUMNS)
    inputs = _read_snapshot(config=config, parameters=parameters,
                            kind="inputs", columns=INPUT_COLUMNS)
    if not set(inputs["source_group_key"]).issubset(groups["source_group_key"]):
        raise ResearchError("Campaign inputs reference a group outside the selected inventory")
    identifiers = list(dict.fromkeys(inputs["input_id"]))
    mappings = []
    for offset in range(0, len(identifiers), 10_000):
        batch = identifiers[offset:offset + 10_000]
        directory = output / "mapping_batches" / f"batch_{offset // 10_000:05d}"
        result = exchange(
            config=config, request={"operation": "resolve", "identifiers": batch},
            output=directory, transport=str(parameters["transport"]),
        )
        frame = pd.read_csv(
            filepath_or_buffer=result["global_cluster_mapping.tsv"], sep="\t",
            dtype=str, keep_default_na=False,
        )
        required = {"input_id", "cluster_id", "member_count", "mapping_status"}
        if not required.issubset(frame) or set(frame["input_id"]) != set(batch):
            raise ResearchError("DeepClust mapping did not account for every requested identifier")
        mappings.append(frame)
        if sum(len(value) for value in mappings) > 1_000_000:
            raise ResearchError("Campaign mapping exceeds one million complete result rows")
    base = pd.concat(objs=mappings, ignore_index=True) if mappings else pd.DataFrame(columns=[
        "input_id", "cluster_id", "member_count", "mapping_status",
    ])
    mapped = base.merge(right=inputs, on="input_id", how="left", validate="many_to_many")
    group_status = []
    for group in groups.to_dict(orient="records"):
        selected = mapped.loc[mapped["source_group_key"] == group["source_group_key"]]
        source_ids = set(inputs.loc[
            inputs["source_group_key"] == group["source_group_key"], "input_id",
        ])
        hits = selected.loc[selected["cluster_id"].ne("")]
        matched = set(hits["input_id"])
        group_status.append({
            **group, "requested_identifier_count": len(source_ids),
            "matched_identifier_count": len(matched),
            "unmatched_identifier_count": len(source_ids - matched),
            "global_cluster_count": hits["cluster_id"].nunique(),
            "mapping_status": ("NO_IDENTIFIERS" if not source_ids else "UNMATCHED" if not matched
                               else "MAPPED" if matched == source_ids else "PARTIAL"),
        })
    hits = mapped.loc[mapped["cluster_id"].ne("")].copy()
    inventory = []
    for cluster_id, rows in hits.groupby(by="cluster_id", sort=True):
        sizes = pd.to_numeric(arg=rows["member_count"].replace("", pd.NA), errors="coerce")
        known = sizes.dropna().unique()
        if (rows["member_count"].ne("") & sizes.isna()).any():
            raise ResearchError("Published global cluster member counts are malformed")
        if len(known) > 1:
            raise ResearchError("The same global cluster has conflicting published member counts")
        if len(known) and (known[0] < 1 or known[0] % 1):
            raise ResearchError("Published global cluster member counts must be positive integers")
        size = int(known[0]) if len(known) else None
        inventory.append({
            "cluster_id": cluster_id, "member_count": size,
            "source_group_count": rows["source_group_key"].nunique(),
            "matched_input_count": rows["input_id"].nunique(), "retrievable": size is not None,
        })
    clusters = pd.DataFrame(data=inventory, columns=(
        "cluster_id", "member_count", "source_group_count", "matched_input_count", "retrievable",
    )).sort_values(by=["member_count", "cluster_id"], ascending=[False, True], na_position="last")
    frames = {
        "campaign_groups.tsv": pd.DataFrame(data=group_status), "campaign_inputs.tsv": inputs,
        "global_cluster_mapping.tsv": mapped, "global_clusters.tsv": clusters,
    }
    artifacts = {}
    for name, frame in frames.items():
        path = output / name
        frame.to_csv(path_or_buf=path, sep="\t", index=False)
        artifacts[name] = path
    LOGGER.info("Mapped %d E3 groups to %d global clusters from %d identifiers",
                len(groups), len(clusters), len(identifiers))
    return artifacts
