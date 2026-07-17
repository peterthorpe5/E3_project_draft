from biopandas.mmcif import PandasMmcif
import sqlite3
import argparse
import pandas as pd

def get_pocket_residues(con, organism_id):
    query = """SELECT Accession, name, residue_ids 
    FROM pocket_details
    LEFT JOIN e3_ligases ON pocket_details.Accession = e3_ligases.entry
    WHERE organism_id = (?);"""
    df = pd.read_sql(query, params= [organism_id], con= con)
    df["residue_ids"] = df["residue_ids"].str.strip().str.split(" ")
    df = df.explode("residue_ids")
    df[["chain", "residue_ids"]] = df["residue_ids"].str.split("_", expand = True)
    df["residue_ids"] = df["residue_ids"].astype(int)
    return df

def residue_pLDDT_scores(filepath, accession):
    fullpath = f"{filepath}/{accession}/AF-{accession}-F1-model_v6.cif"
    df = PandasMmcif().read_mmcif(fullpath).df["ATOM"]
    df = df[["label_asym_id", "B_iso_or_equiv", "label_seq_id"]]
    df = df.drop_duplicates()
    return df

def combine_data(pocket_details, mmcif_data):
    df = pd.merge(pocket_details, mmcif_data, how = "inner", left_on= ["chain", "residue_ids"], right_on=["label_asym_id", "label_seq_id"])
    df = df.drop(columns = ["label_asym_id", "label_seq_id"])
    return df



parser = argparse.ArgumentParser(description='Analyses mmcif to extract pocket pLDDT scores')
parser.add_argument('-db', help='Database')
parser.add_argument('-input', help='Input directory')
parser.add_argument('-organism_id', help='Organism ID')
args = parser.parse_args()
db = args.db
input_dir = args.input
org_id = args.organism_id


conn = sqlite3.connect(db)
cursor = conn.cursor()


pocket_residues = get_pocket_residues(conn, org_id)
accession_list = list(set(pocket_residues["Accession"].tolist()))



pocket_stats = pd.DataFrame()
count = len(accession_list)
print(count)
for accession in accession_list:
    print(f"Analysing {accession}")
    mmcif = residue_pLDDT_scores(input_dir, accession)

    filtered_pockets = pocket_residues.loc[pocket_residues["Accession"] == accession]

    data = combine_data(filtered_pockets, mmcif)
    pocket_scores = (data.groupby(["Accession", "name", "chain"])
                    .agg(total_pocket_residues=("B_iso_or_equiv", "count"), 
                        num_ge70=("B_iso_or_equiv", lambda x: (x >= 70).sum()), 
                        num_ge90=("B_iso_or_equiv", lambda x: (x >= 90).sum())
                    )).reset_index()
    pocket_scores["ratio_ge_70"] = pocket_scores.apply(lambda x: x["num_ge70"]/x["total_pocket_residues"], 1)
    pocket_scores["ratio_ge_90"] = pocket_scores.apply(lambda x: x["num_ge90"]/x["total_pocket_residues"], 1)
    pocket_scores["percent_ge_70"] = pocket_scores.apply(lambda x: x["num_ge70"]/x["total_pocket_residues"]*100, 1)
    pocket_scores["percent_ge_90"] = pocket_scores.apply(lambda x: x["num_ge90"]/x["total_pocket_residues"]*100, 1)
    pocket_stats = pd.concat([pocket_stats, pocket_scores], ignore_index= True)

    count = count - 1
    print(f"{count} remaining")

pocket_stats.to_sql("pocket_scores", conn, index = False, if_exists= "append")
