import pandas as pd
from Bio import SeqIO
import argparse
import hashlib

parser = argparse.ArgumentParser(description='This script will read a fasta file, hash the sequence and create a parquet output')
parser.add_argument('-o', help='output')
parser.add_argument('-f', help='Fasta file')
args = parser.parse_args() 
output = args.o
fasta = args.f


d1 = {}
count = 0
with open(fasta, "r") as handle:
    for record in SeqIO.parse(handle, "fasta"):
        if "|" in record.id:
            d1[count] = {"accession": record.id, "entry": record.id.split("|")[1], "sequence": str(record.seq), "md5": hashlib.md5(str(record.seq).encode()).hexdigest()}
            count += 1
        else:
            d1[count] = {"accession": record.id, "entry": record.id, "sequence": str(record.seq), "md5": hashlib.md5(str(record.seq).encode()).hexdigest()}
            count += 1

df = pd.DataFrame.from_dict(d1, orient = "index")
df.to_parquet(output, compression = None)

