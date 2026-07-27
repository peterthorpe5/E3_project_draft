#!/bin/zsh
#prank version: P2Rank 2.5.2-dev.2 - used for testing Piers' list
# prank version: P2Rank 2.5.1 - used for E3 ligase DB
# $1: accession list as .txt, $2: path to directory where models are located $3: path where output should be written

while IFS= read -r line; do
    echo $line

    CIF= "$2/${line}/AF-${line}-F1-model_v6.cif"
    /Users/ebutterfield/Documents/Drost_lab/other_peoples_stuff/p2rank_2.5.1/prank fpocket-rescore -f "${2}/${line}/AF-${line}-F1-model_v6.cif" -c rescore_2024 -o "$3" -threads 8 

done < "$1"
