import requests
import pandas as pd
import argparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os
import time
import sqlite3

class API():
    def download_data(self, url, filename):
        retry_strategy = Retry(
            total= 10,
            connect= 10,
            read= 10,
            backoff_factor= 10,
            status_forcelist= [429, 500, 502, 503, 504],
            allowed_methods= ["GET"],
            respect_retry_after_header= True
            )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        http = requests.Session()
        http.mount("https://", adapter)
        http.mount("http://", adapter)
        response = http.get(url, timeout= 35)
        with open(filename, "wb") as f:
            f.write(response.content)
    
    def get_file(self, url, file_path):
        file = url.split("/").pop()
        self.download_data(url, f"{file_path}/{file}")

        

class main():
    parser = argparse.ArgumentParser(description='Downloads models produced from get_pLDDT_scores')
    parser.add_argument('-infile', help='Input file')
    parser.add_argument('-out', help='Output directory')
    parser.add_argument('-organism_id', help='Organism ID')
    args = parser.parse_args()
    infile = args.infile
    out = args.out
    org_id = args.organism_id

    if infile.endswith(".csv"):
        df = pd.read_csv(infile)
    elif infile.endswith(".db"):
        conn = sqlite3.connect(infile)
        query = """SELECT accession, cifUrl, paeDocUrl, msaUrl FROM alphafold_metadata 
        LEFT JOIN e3_ligases ON alphafold_metadata.accession = e3_ligases.entry
        WHERE alphafold_metadata.fractionModToHigh >= 0.5
        AND e3_ligases.organism_id =:org_id;"""
        df = pd.read_sql(query, params= {"org_id": org_id}, con= conn)
    

    api = API()


    os.makedirs(out, exist_ok= True)

    count = len(df)
    for index, row in df.iterrows():
        print(f"Downloading {row["accession"]}")
        os.makedirs(f"{out}/{row["accession"]}", exist_ok = True)
        api.get_file(row["cifUrl"], f"{out}/{row["accession"]}")
        time.sleep(0.2)
        api.get_file(row["paeDocUrl"], f"{out}/{row["accession"]}")
        time.sleep(0.2)
        api.get_file(row["msaUrl"], f"{out}/{row["accession"]}")
        time.sleep(1)
        count = count - 1
        print(f"{count} remaining")
  
    accession_list = df["accession"].tolist()
    with open(f"{out}/accession_list.txt", "w") as f:
        for accession in accession_list:
            f.write(f"{accession}\n")

            
if __name__ == "__main__":
    main()