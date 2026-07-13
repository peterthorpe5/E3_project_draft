import duckdb
import argparse



def main():
    con = duckdb.connect('output/e3_discovery_db.db')

    # Add sequences table
    con.sql("CREATE TABLE sequences AS SELECT * FROM 'concat_file/concated_seqs.parquet';")

    # Add cluster results
    con.sql("CREATE TABLE deepclust_results AS FROM read_csv('diamond_files/concat_db_clustered.tsv', delim = '\t', columns = {'representative': 'VARCHAR', 'member': 'VARCHAR'});")

    # Add realigned results
    con.sql("CREATE TABLE deepclust_aln_results AS SELECT * FROM 'diamond_files/realigned_clusters.parquet';")
    # con.sql("""CREATE TABLE deepclust_aln_results AS FROM read_csv('data/small_dataset_aln_copy.tsv', delim = '\t', columns = {'cseqid': 'VARCHAR', 'mseqid': 'VARCHAR', 'approx_pident': 'FLOAT', 'cstart': 'INTEGER', 'cend': 'INTEGER', 'mstart': 'INTEGER', 'mend': 'INTEGER', 'evalue': 'VARCHAR', 'bitscore': 'FLOAT'});""")

    # Add E3 ligase data
    con.sql("CREATE TABLE e3_ligases AS FROM read_csv('files/e3_ligases.csv')")
    # con.sql("""CREATE TABLE category_data AS FROM read_csv('data/temp/Hs_testing_pipeline_filtered.csv', header = TRUE);""")


if __name__ == "__main__":
    main()
