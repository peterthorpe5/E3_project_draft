"""Versioned, explicit SQL and TSV schemas, including empty-result tables."""

SCHEMA_VERSION = "1.0"

# (column, SQL type, meaning). Fractions are 0..1 and pLDDT is 0..100.
COMMON = {
    "sample_id": ("VARCHAR", "Unique input model identifier"),
    "method": ("VARCHAR", "fpocket, p2rank or p2rank_rescore; kept separate"),
    "pocket_id": ("INTEGER", "Native cavity number or method-specific rank"),
    "rank": ("INTEGER", "Native tool rank within this model and method"),
    "score": ("DOUBLE", "Native method score; different methods have different scales"),
    "probability": (
        "DOUBLE",
        "P2Rank calibrated site probability, 0..1; not drug efficacy",
    ),
    "druggability_score": ("DOUBLE", "fpocket druggability descriptor, 0..1"),
    "volume_a3": ("DOUBLE", "fpocket cavity volume in cubic angstroms"),
    "mean_plddt": (
        "DOUBLE",
        "Unweighted mean of mapped residues' heavy-atom mean pLDDT",
    ),
    "fraction_ge_threshold": (
        "DOUBLE",
        "Residues with pLDDT >= configured threshold / ALL predicted residues",
    ),
    "residue_count": ("INTEGER", "Number of unique protein residues in this record"),
    "mapped_residue_count": (
        "INTEGER",
        "Predicted lining residues mapped to the model",
    ),
    "unmapped_residue_count": (
        "INTEGER",
        "Predicted lining residues not mapped to the model",
    ),
    "confidence_status": (
        "VARCHAR",
        "Explicit local confidence rule outcome, not druggability",
    ),
    "fpocket_pocket_id": (
        "INTEGER",
        "Original fpocket cavity ID; never new P2Rank rank",
    ),
    "residue_key": ("VARCHAR", "Prepared chain and residue number, e.g. A_15"),
    "author_chain": ("VARCHAR", "Original author chain identifier"),
    "author_residue_number": ("INTEGER", "Original author residue number"),
    "insertion_code": ("VARCHAR", "Original residue insertion code; empty if absent"),
    "fasta_position": ("INTEGER", "One-based position in supplied FASTA, or NULL"),
    "plddt": ("DOUBLE", "Mean heavy-atom pLDDT for this residue, 0..100, or NULL"),
    "status": ("VARCHAR", "Explicit completion/no_pockets/failed/skipped state"),
    "error": ("VARCHAR", "Specific failure detail; empty on success"),
}

SAMPLE_EXTRA = {
    "cluster": ("VARCHAR", "Optional user-supplied cluster label"),
    "sequence_id": ("VARCHAR", "Exact supplied FASTA identifier"),
    "source_model": ("VARCHAR", "Relative path to retained unmodified input structure"),
    "prepared_model": ("VARCHAR", "Relative path to normalised protein-only PDB"),
    "chain_count": ("INTEGER", "Number of analysed protein chains"),
    "sequence_status": ("VARCHAR", "exact, unique_exact_fragment or not_supplied"),
    "fasta_length": ("INTEGER", "Supplied FASTA sequence length, or NULL"),
    "fasta_coverage": ("DOUBLE", "Mapped model residues / FASTA length, 0..1, or NULL"),
    "warnings": ("VARCHAR", "Specific model preparation and confidence warnings"),
    "fpocket_status": ("VARCHAR", "Completion state of fpocket analysis"),
    "p2rank_status": ("VARCHAR", "Completion state of independent P2Rank prediction"),
    "rescore_status": ("VARCHAR", "Completion state of P2Rank fpocket rescoring"),
}

POCKET_EXTRA = {
    "centre_x": ("DOUBLE", "P2Rank pocket centre X coordinate, angstroms, or NULL"),
    "centre_y": ("DOUBLE", "P2Rank pocket centre Y coordinate, angstroms, or NULL"),
    "centre_z": ("DOUBLE", "P2Rank pocket centre Z coordinate, angstroms, or NULL"),
    "residue_ids": (
        "VARCHAR",
        "Semicolon-separated prepared residue keys; see membership table",
    ),
}

RANK_EXTRA = {
    "review_rank": ("INTEGER", "One-based rank of fpocket cavities within one model"),
    "ranking_basis": (
        "VARCHAR",
        "p2rank_rescore, otherwise fpocket_druggability fallback",
    ),
    "p2rank_rescore_rank": (
        "INTEGER",
        "Native P2Rank rank after rescoring this cavity",
    ),
    "p2rank_rescore_score": ("DOUBLE", "P2Rank score for this same fpocket cavity"),
    "p2rank_rescore_probability": (
        "DOUBLE",
        "Calibrated rescored-cavity site probability, 0..1",
    ),
    "independent_p2rank_match": (
        "INTEGER",
        "Best overlapping independent P2Rank pocket rank",
    ),
    "match_jaccard": ("DOUBLE", "Best within-model residue intersection / union, 0..1"),
}

POCKET_FIELDS = [
    "sample_id",
    "method",
    "pocket_id",
    "rank",
    "score",
    "probability",
    "druggability_score",
    "volume_a3",
    "fpocket_pocket_id",
    "residue_count",
    "mapped_residue_count",
    "unmapped_residue_count",
    "mean_plddt",
    "fraction_ge_threshold",
    "confidence_status",
    "centre_x",
    "centre_y",
    "centre_z",
    "residue_ids",
]

TABLE_FIELDS = {
    "samples": [
        "sample_id",
        "cluster",
        "sequence_id",
        "status",
        "fpocket_status",
        "p2rank_status",
        "rescore_status",
        "residue_count",
        "chain_count",
        "mean_plddt",
        "fraction_ge_threshold",
        "fasta_length",
        "fasta_coverage",
        "sequence_status",
        "warnings",
        "error",
        "source_model",
        "prepared_model",
    ],
    "ranked_pockets": [
        "sample_id",
        "review_rank",
        "pocket_id",
        "ranking_basis",
        "p2rank_rescore_rank",
        "p2rank_rescore_score",
        "p2rank_rescore_probability",
        "druggability_score",
        "volume_a3",
        "score",
        "residue_count",
        "mean_plddt",
        "fraction_ge_threshold",
        "confidence_status",
        "mapped_residue_count",
        "unmapped_residue_count",
        "independent_p2rank_match",
        "match_jaccard",
        "residue_ids",
    ],
    "pockets": POCKET_FIELDS,
    "residues": [
        "sample_id",
        "residue_key",
        "tool_chain",
        "tool_residue_number",
        "author_chain",
        "author_residue_number",
        "insertion_code",
        "residue_name",
        "amino_acid",
        "fasta_position",
        "plddt",
    ],
    "pocket_residues": [
        "sample_id",
        "method",
        "pocket_id",
        "residue_key",
        "mapped",
        "plddt",
        "author_chain",
        "author_residue_number",
        "insertion_code",
        "fasta_position",
    ],
    "matches": [
        "sample_id",
        "fpocket_pocket_id",
        "p2rank_pocket_id",
        "shared_residue_count",
        "union_residue_count",
        "jaccard",
    ],
    "method_runs": ["sample_id", "method", "status", "error", "log_prefix"],
    "fpocket_descriptors": ["sample_id", "pocket_id", "descriptor", "value"],
    "run_info": ["key", "value"],
}

OTHER = {
    "tool_chain": ("VARCHAR", "Normalised single-character chain given to tools"),
    "tool_residue_number": (
        "INTEGER",
        "One-based prepared residue number within chain",
    ),
    "residue_name": ("VARCHAR", "Original three-letter amino acid residue name"),
    "amino_acid": ("VARCHAR", "One-letter amino acid for sequence validation"),
    "mapped": ("BOOLEAN", "Whether a predicted residue maps to the prepared model"),
    "p2rank_pocket_id": ("INTEGER", "Independent P2Rank pocket rank in this model"),
    "shared_residue_count": (
        "INTEGER",
        "Lining residues shared by the two predictions",
    ),
    "union_residue_count": (
        "INTEGER",
        "Distinct lining residues across both predictions",
    ),
    "jaccard": ("DOUBLE", "Within-model residue intersection divided by union, 0..1"),
    "log_prefix": ("VARCHAR", "Relative command/stdout/stderr log path prefix"),
    "descriptor": ("VARCHAR", "Original fpocket descriptor, normalised to snake_case"),
    "value": ("DOUBLE", "Original numeric descriptor value, unmodified"),
    "key": ("VARCHAR", "Run metadata key"),
}

DEFINITIONS = {**COMMON, **SAMPLE_EXTRA, **POCKET_EXTRA, **RANK_EXTRA, **OTHER}
SCHEMAS = {
    table: [
        (column, "VARCHAR" if table == "run_info" else DEFINITIONS[column][0])
        for column in columns
    ]
    for table, columns in TABLE_FIELDS.items()
}
PRIMARY_KEYS = {
    "samples": ["sample_id"],
    "ranked_pockets": ["sample_id", "pocket_id"],
    "pockets": ["sample_id", "method", "pocket_id"],
    "residues": ["sample_id", "residue_key"],
    "pocket_residues": ["sample_id", "method", "pocket_id", "residue_key"],
    "matches": ["sample_id", "fpocket_pocket_id", "p2rank_pocket_id"],
    "method_runs": ["sample_id", "method"],
    "fpocket_descriptors": ["sample_id", "pocket_id", "descriptor"],
    "run_info": ["key"],
}
