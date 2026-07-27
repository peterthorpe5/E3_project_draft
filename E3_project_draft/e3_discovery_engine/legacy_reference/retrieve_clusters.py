import duckdb
from Bio import SeqIO 
from Bio.SeqRecord import SeqRecord
from Bio.Seq import Seq
import pandas as pd
import argparse


def write_seqs(sql_results, filename):
    seqs = [SeqRecord(Seq(x[1]), id = x[0], description = "") for x in sql_results]
    with open(filename, "w") as handle:
        SeqIO.write(seqs, handle, "fasta")



def main():
    parser = argparse.ArgumentParser(description='Retrieves E3 clusters from DuckDB')
    parser.add_argument('-db', help='Database')
    parser.add_argument('-aln', help='Name of output deepclust alignment file')
    parser.add_argument('-rep', help= "Name of representatives file")
    parser.add_argument('-seqs', help="Name of all E3 clusters sequences file")
    args = parser.parse_args()
    db = args.db
    aln = args.aln
    rep = args.rep
    seq_file = args.seqs


    con = duckdb.connect(db)

    # 1. Retrieve aln results for all centroids containing E3 ligase members
    cseqids = con.sql("SELECT DISTINCT(cseqid) FROM deepclust_aln_results LEFT JOIN sequences ON deepclust_aln_results.mseqid = sequences.accession INNER JOIN e3_ligases ON sequences.entry = e3_ligases.Entry;").fetchall()
    cseqids_list = [x[0] for x in cseqids]
    aln_data = con.sql("SELECT * FROM deepclust_aln_results WHERE cseqid = ANY(?);", params = [cseqids_list])
    aln_data.write_parquet(aln)


    # 2. Retrieve sequences for all E3 centroids into a fasta file
    cseqid_seqs = con.sql("SELECT accession, sequence FROM sequences WHERE accession = ANY(?);", params = [cseqids_list]).fetchall()
    write_seqs(cseqid_seqs, rep)


    # 3. Retrieve sequences for all centroids and members of E3 ligase clusters into a single file
    mseqids = con.sql("SELECT mseqid FROM deepclust_aln_results WHERE cseqid = ANY(?)", params = [cseqids_list]).fetchall()
    mseqids_list = [x[0] for x in mseqids]
    mseqid_seqs = con.sql("SELECT accession, sequence FROM sequences WHERE accession = ANY(?);", params = [mseqids_list]).fetchall()
    write_seqs(mseqid_seqs, seq_file)


if __name__ == "__main__":
    main()

