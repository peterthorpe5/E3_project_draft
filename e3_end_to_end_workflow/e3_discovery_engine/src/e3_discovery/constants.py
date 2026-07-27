"""Shared schemas and column definitions for the workflow."""

SEQUENCE_COLUMNS = (
    "internal_id",
    "source_file_sample_id",
    "source_file_species",
    "sample_id",
    "species",
    "taxon_id",
    "proteome_id",
    "onekp_sample_code",
    "header_parser",
    "header_parse_status",
    "original_id",
    "entry",
    "description",
    "sequence",
    "sequence_length",
    "sequence_md5",
    "source_path",
    "source_sha256",
    "record_index",
    "sample_metadata_json",
)

REALIGN_COLUMNS = (
    "representative_id",
    "member_id",
    "pident",
    "representative_length",
    "member_length",
    "representative_start",
    "representative_end",
    "member_start",
    "member_end",
    "alignment_length",
    "evalue",
    "bitscore",
)

SNK_BENCHMARK_COLUMNS = (
    "s",
    "h:m:s",
    "max_rss",
    "max_vms",
    "max_uss",
    "max_pss",
    "io_in",
    "io_out",
    "mean_load",
    "cpu_time",
)

DEFAULT_SEED_COLUMN_CANDIDATES = (
    "Entry",
    "entry",
    "Accession",
    "accession",
    "protein_id",
    "Protein_ID",
)

PROTEIN_ALPHABET = frozenset("ABCDEFGHIKLMNPQRSTVWXYZUOJ*-.")
