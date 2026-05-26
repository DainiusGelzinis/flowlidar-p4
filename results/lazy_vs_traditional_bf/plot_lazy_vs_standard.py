#!/usr/bin/env python3
"""Render lazy vs standard BF line charts from summary_chunk0.csv.

x axis: BF bits per row (log)
y axis: one metric per figure (coverage, ARE, AAE, exact rate)
"""

import csv
import os
import re

import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "summary_chunk0.csv")
OUT = os.path.join(HERE, "plots")
os.makedirs(OUT, exist_ok=True)

SIZES = {
    "131k": 131072,
    "262k": 262144,
    "524k": 524288,
    "1m":   1048576,
    "2m":   2097152,
}

# Keep the most recent row per variant. The "variant" column from compare.py
# includes the full --meta string ("lazy_bf131k_..,pcap=130000,chunk=00000"),
# so split on comma and use just the leading variant name.
rows = {}
with open(SRC) as f:
    for row in csv.DictReader(f):
        key = row["variant"].split(",", 1)[0]
        rows[key] = row


def collect(mode):
    pts = []
    for tag, bits in SIZES.items():
        name = f"{mode}_bf{tag}_cms256x1024"
        if name not in rows:
            continue
        r = rows[name]
        pts.append((
            bits,
            float(r["coverage"]) * 100.0,
            float(r["ARE"]) * 100.0,
            float(r["AAE"]),
            float(r["pct_exact"]) * 100.0,
        ))
    pts.sort()
    return list(zip(*pts))


lazy     = collect("lazy")
standard = collect("traditional")  # P4 program prefix is still "traditional_"

PLOTS = [
    (1, "Coverage (\\%)",              "coverage.png"),
    (2, "Average relative error (\\%)", "are.png"),
    (3, "Average absolute error",      "aae.png"),
    (4, "Exact rate (\\%)",            "exact.png"),
]

for col, ylabel, fname in PLOTS:
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    ax.plot(lazy[0],     lazy[col],     marker="o", label="Lazy BF",     color="#1f77b4")
    ax.plot(standard[0], standard[col], marker="s", label="Standard BF", color="#d62728")
    ax.set_xscale("log", base=2)
    ax.set_xlabel("Bloom Filter bits per row")
    ax.set_ylabel(ylabel.replace("\\%", "%"))
    ax.set_xticks(list(SIZES.values()))
    ax.set_xticklabels(["131k", "262k", "524k", "1M", "2M"])
    ax.grid(True, which="both", linestyle=":", alpha=0.4)
    ax.legend()
    fig.tight_layout()
    out_path = os.path.join(OUT, fname)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    print(f"[wrote] {out_path}")
