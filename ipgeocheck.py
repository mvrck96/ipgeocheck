#!/bin/python3

import os
import subprocess
from multiprocessing import Pool
from ipaddress import IPv4Address
from typing import Union
from time import time

import typer

from typing_extensions import Annotated
import scapy.all as sc
import pandas as pd
from rich import print
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.console import Console


console = Console()


def get_country_by_ip(ip: IPv4Address) -> Union[str, None]:
    """Get country code by ip address."""

    result = (
        subprocess.run(["whois", str(ip)], capture_output=True)
        .stdout.decode("utf-8")
        .split("\n")
    )
    country = list(filter(lambda x: x.lower().startswith("country"), result))
    if country:
        return (ip, country[-1].split(" ")[-1].strip())
    else:
        return (ip, None)


def main(
    file: str,
    packages: Annotated[
        int, typer.Option("--packages", "-p", help="Number of packages to inspect.")
    ] = None,
    trace: bool = False,
):
    """Analyses TCP packages to identify package geo-data.

    Args:

        file (str): Path to pcap file, from tcpdump command.

        packages (int, optional): Number of first packages to analyse.
        Defaults to None.

        report (bool, optional): Flag to generate xlsx report.
        Defaults to False. 
    """
    st = time()
    with Progress(SpinnerColumn(),
                  TextColumn("[progress.description]{task.description}"),
                transient=True) as progress:
        progress.add_task(
            f"Extracting packets from [bold]{file.split('/')[-1]}[/bold] file ...")
        if packages:
            packets = sc.rdpcap(file, count=packages)
        else:
            packets = sc.rdpcap(file)

        source = [IPv4Address(a[sc.IP].src) for a in packets if sc.IP in a]
        dest = [IPv4Address(a[sc.IP].dst) for a in packets if sc.IP in a]

    print(f"Extracted {len(packets)} packages")
    df = pd.DataFrame({"src": source, "dest": dest})
    
    # IP global check
    df["src_global"] = df["src"].apply(lambda x: x.is_global)
    df["dest_global"] = df["dest"].apply(lambda x: x.is_global)

    # multicast check
    df["src_not_multicast"] = df["src"].apply(lambda x: not x.is_multicast)
    df["dest_not_multicast"] = df["dest"].apply(lambda x: not x.is_multicast)

    # Get valid IP
    src_valid = df.loc[(df["src_global"]) & (df["src_not_multicast"]), "src"].values
    dest_valid = df.loc[(df["dest_global"]) & (df["dest_not_multicast"]), "dest"].values

    addrs = set([*src_valid, *dest_valid])

    # Get country by valid IP
    with Progress(SpinnerColumn(),
                  TextColumn("[progress.description]{task.description}"),
                transient=True) as progress:
        progress.add_task("Fetching country codes ...")

        av_cores = os.cpu_count()
        if av_cores >= 4:
            av_cores -= 2
        else:
            av_cores = 2

        pool = Pool(av_cores)
        res = pool.map(get_country_by_ip, addrs)
        mapping = {i[0]: i[1] for i in res}

    print(f"Processed {len(addrs)} global unique IP")

    df["src_country"] = df["src"].map(mapping)
    df["dest_country"] = df["dest"].map(mapping)

    df["src_country"].fillna("LOCAL", inplace=True)
    df["dest_country"].fillna("LOCAL", inplace=True)

    # Print result table
    table = Table("Source IP", "Destination IP", header_style="")
    inc = Table("Country", "%", show_edge=False, show_header=False)
    outc = Table("Country", "%", show_edge=False, show_header=False)

    src_cc_perc = df["src_country"].value_counts() / df.shape[0] * 100
    for c, p in zip(src_cc_perc.index, src_cc_perc.values):
        inc.add_row(c, f"{round(p, 2)} %")

    dest_cc_perc = df["dest_country"].value_counts() / df.shape[0] * 100
    for c, p in zip(dest_cc_perc.index, dest_cc_perc.values):
        outc.add_row(c, f"{round(p, 2)} %")

    table.add_row(inc, outc)

    console.print(table)

    if trace:
        tt = Table("IP", "Country")
        for k, v in mapping.items():
            tt.add_row(str(k), v)
        console.print(tt)

    ft = time()
    print(f"Elapsed time: {round(ft - st, 3)} sec")


if __name__ == "__main__":
    typer.run(main)
