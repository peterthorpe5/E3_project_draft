-- Top E3-seeded clusters by plant/species breadth and strict membership.
SELECT
    representative_id,
    known_e3_seed_ids,
    species_count,
    sample_count,
    raw_member_count,
    strict_member_count,
    median_observed_pident,
    median_member_coverage
FROM e3_seeded_cluster_summary
ORDER BY species_count DESC, strict_member_count DESC;

-- All known seeds and the source sequences that matched them.
SELECT *
FROM sequence_seed_matches
ORDER BY seed_id, species, internal_id;

-- Strict members for one cluster.
SELECT
    representative_id,
    member_id,
    species,
    proteome_id,
    entry,
    pident,
    representative_coverage,
    member_coverage,
    evalue,
    bitscore,
    is_known_e3_seed
FROM strict_e3_seeded_cluster_members
WHERE representative_id = 'REPLACE_WITH_CLUSTER_ID'
ORDER BY species, member_id;

-- Raw members lacking a realignment record or failing strict criteria.
SELECT
    representative_id,
    member_id,
    species,
    pident,
    representative_coverage,
    member_coverage,
    evalue,
    bitscore
FROM e3_seeded_cluster_members
WHERE NOT passes_strict_thresholds
ORDER BY representative_id, species, member_id;

-- Thresholds embedded in this resource.
SELECT *
FROM workflow_thresholds
ORDER BY threshold_name;
