import pandas as pd
import matplotlib.pyplot as plt
import argparse


class Plots():
    def __init__(self, out, outfile):
        self.out = out
        self.outfile = outfile

    def plot_distributions(self, df, column):
        ax = df[column].hist(bins = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100])
        ax.set_title("Distribution of average pLDDT scores")
        ax.figure.savefig(f"{self.out}/{self.outfile}_pLDDT_dists.png")
    

    

class main():
    parser = argparse.ArgumentParser(description='Plot pLDDT distributions')
    parser.add_argument('-infile', help='Input file')
    parser.add_argument('-out', help='Output directory')
    parser.add_argument('-outfile', help= "Output filename")
    args = parser.parse_args()
    infile = args.infile
    out = args.out
    out_name = args.outfile

    df = pd.read_csv(infile)
    plots = Plots(out, out_name)
    plots.plot_distributions(df, "globalMetricValue")

    ave_70 = df.loc[df["globalMetricValue"] >= 70]
    ave_70.to_csv(f"{out}/{out_name}_AveGE70.csv", index= False)
    prop_70 = df.loc[df["fractionModToHigh"] >= 0.5]
    prop_70.to_csv(f"{out}/{out_name}_ModToHighGE50.csv", index= False)

    ave_70_list = set(ave_70["accession"].tolist())
    prop_70_list = set(prop_70["accession"].tolist())

    print(f"Number of accessions with average pLDDT >= 70: {len(ave_70_list)}")
    print(f"Number of accessions with 50% residues >= 70: {len(prop_70_list)}")
    unique_ave = ave_70_list - prop_70_list
    unique_prop = prop_70_list - ave_70_list
    print(f"Number unique to average pLDDT >= 70: {len(unique_ave)}")
    print(unique_ave)
    print(f"Number unique to 50% residues >= 70: {len(unique_prop)}")
    print(unique_prop)


if __name__ == "__main__":
    main()
    

