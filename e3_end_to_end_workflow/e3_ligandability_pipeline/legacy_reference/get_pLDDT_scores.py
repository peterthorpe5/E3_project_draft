import requests
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import argparse
import time
import os
import sqlite3


class API():
    def query_alphafold(self, accession):
        link = f"https://alphafold.ebi.ac.uk/api/prediction/{accession}"
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
        response = http.get(link, timeout= 35)
        return response.json()[0]



class AF_structure():
    def __init__(self, accession):
        self.accession = accession
        self.data = {}

    def get_data(self):
        api = API()
        try:
            response = api.query_alphafold(self.accession)
        except KeyError:
            print(f"No AlphaFold model associated with: {self.accession}")
            self.data["accession"] = self.accession
            self.data["globalMetricValue"] = None
            self.data["fractionPlddtVeryLow"] = None
            self.data["fractionPlddtLow"] = None
            self.data["fractionPlddtConfident"] = None
            self.data["fractionPlddtVeryHigh"] = None
            self.data["fractionModToHigh"] = None
            self.data["cifUrl"] = None
            self.data["msaUrl"] = None
            self.data["plddtDocUrl"] = None
            self.data["paeDocUrl"] = None

        else:
            self.data["accession"] = self.accession
            self.data["globalMetricValue"] = response["globalMetricValue"]
            self.data["fractionPlddtVeryLow"] = response["fractionPlddtVeryLow"]
            self.data["fractionPlddtLow"] = response["fractionPlddtLow"]
            self.data["fractionPlddtConfident"] = response["fractionPlddtConfident"]
            self.data["fractionPlddtVeryHigh"] = response["fractionPlddtVeryHigh"]
            self.data["fractionModToHigh"] = self.data["fractionPlddtConfident"] + self.data["fractionPlddtVeryHigh"]
            self.data["cifUrl"] = response["cifUrl"]
            self.data["msaUrl"] = response["msaUrl"]
            self.data["plddtDocUrl"] = response["plddtDocUrl"]
            self.data["paeDocUrl"] = response["paeDocUrl"]



class main():
    parser = argparse.ArgumentParser(description='Get confidence and file locations from AlphaFold')
    parser.add_argument('-infile', help='Input file')
    parser.add_argument('-out', help='Output directory')
    parser.add_argument('-outfile', help= "Output filename")
    parser.add_argument('-organism_id', help="Organim ID for retrieving from SQL database")
    args = parser.parse_args()
    infile = args.infile
    out = args.out
    out_name = args.outfile
    org_id = args.organism_id


    if infile.endswith(".txt"):
        with open(infile, "r") as f:
            accession_list = [accession.strip() for accession in f.readlines()]
    elif infile.endswith(".db"):
        conn = sqlite3.connect(infile)
        cursor = conn.cursor()
        query = """SELECT entry FROM e3_ligases WHERE organism_id = ?;"""
        cursor.execute(query, [org_id])
        accession_list = [x[0] for x in cursor.fetchall()]
        conn.close()
    
    alphafold_structures = [AF_structure(accession) for accession in accession_list]
    
    structure_metadata = []

    model_count = len(alphafold_structures)
    for model in alphafold_structures:
        print(f"Retrieving {model.accession}")
        model.get_data()
        structure_metadata.append(model.data)

        model_count = model_count - 1
        print(f"{(model_count)} remaining")
        time.sleep(1)
    

    df = pd.DataFrame(structure_metadata)

    if out_name.endswith(".db"):
        conn = sqlite3.connect(out_name)
        cursor = conn.cursor()
        query = """CREATE TABLE IF NOT EXISTS alphafold_metadata(
        id INTEGER PRIMARY KEY,
        accession TEXT,
        globalMetricValue REAL,
        fractionPlddtVeryLow REAL,
        fractionPlddtLow REAL,
        fractionPlddtConfident REAL,
        fractionPlddtVeryHigh REAL,
        fractionModToHigh REAL,
        cifUrl TEXT,
        msaUrl TEXT,
        plddtDocUrl TEXT,
        paeDocUrl TEXT
        );"""
        cursor.execute(query)
        df.to_sql("alphafold_metadata", conn, index = False, if_exists= "append")

    else:
        try:
            df.to_csv(f"{out}/{out_name}_af_metadata.csv", index = False)
        except OSError:
            os.makedirs(out, exist_ok = True)
            df.to_csv(f"{out}/{out_name}_af_metadata.csv", index = False)




if __name__ == "__main__":
    main()
    





