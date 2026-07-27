import os
import json


def _remove_gz(item):
    if item.endswith(".gz"):
        return item.replace(".gz", "")
    else:
        return item

def _remove_fasta(item):
    if item.endswith(".fasta"):
        return item.replace(".fasta", "")
    elif item.endswith(".fa"):
        return item.replace(".fa", "")

def get_sample_name(file_list):
    new_list = []
    for item in file_list:
        item = _remove_gz(item)
        new_list.append(_remove_fasta(item))
    return new_list



compressed_list = os.listdir("files/fasta_files/")
# fasta_list = os.listdir("files/fasta/")
samples = get_sample_name(compressed_list)
# samples.extend(get_sample_name(fasta_list))

# samples= list(set(samples))

sample_dict = {"Samples": samples}

with open("samples.json", "w") as f:
    json.dump(sample_dict, f)

