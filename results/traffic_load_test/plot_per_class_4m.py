#!/usr/bin/env python3
"""Per-class ARE / AAE breakdown at 4M load, lazy vs standard.

Reads /tmp/per_class_4m.csv (two rows: lazy and standard) and emits four
figures under plots_per_class_4m/.
"""

import csv
import os

import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
SRC  = "/tmp/per_class_4m.csv"
OUT  = os.path.join(HERE, "plots_per_class_4m")
os.makedirs(OUT, exist_ok=True)

CLASSES   = ["1pkt", "2pkt", "3pkt", "4_10", "11_100", "101plus"]
X_LABELS  = ["1", "2", "3", "4-10", "11-100", "101+"]

rows = {}
with open(SRC) as f:
    for row in csv.DictReader(f):
        key = row["variant"].split(",", 1)[0]
        rows[key] = row

def collect(mode, prefix):
    return [float(rows[mode][f"{prefix}_{c}"]) for c in CLASSES]

lazy_are  = [v * 100.0 for v in collect("lazy",     "ARE")]
trad_are  = [v * 100.0 for v in collect("standard", "ARE")]
lazy_aae  =              collect("lazy",     "AAE")
trad_aae  =              collect("standard", "AAE")

def make_plot(y_lazy, y_trad, ylabel, fname, log=False):
    fig, ax = plt.subplots(figsize=(5.5, 3.6))
    ax.plot(X_LABELS, y_lazy, marker="o", label="Lazy BF",     color="#1f77b4", linewidth=2)
    ax.plot(X_LABELS, y_trad, marker="s", label="Standard BF", color="#d62728", linewidth=2)
    if log:
        ax.set_yscale("log")
    ax.set_xlabel("flow size (packets)")
    ax.set_ylabel(ylabel)
    ax.grid(True, which="both", linestyle=":", alpha=0.4)
    ax.legend()
    fig.tight_layout()
    out_path = os.path.join(OUT, fname)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    print(f"[wrote] {out_path}")

make_plot(lazy_are, trad_are, "Average relative error (%)",  "are.png",        log=True)
make_plot(lazy_are, trad_are, "Average relative error (%)",  "are_linear.png", log=False)
make_plot(lazy_aae, trad_aae, "Average absolute error (pkt)", "aae.png",        log=True)
make_plot(lazy_aae, trad_aae, "Average absolute error (pkt)", "aae_linear.png", log=False)

print()
print(f"{'class':>8}  {'lazy ARE%':>10}  {'std ARE%':>10}  {'lazy AAE':>10}  {'std AAE':>10}  {'ratio ARE':>10}")
for i, c in enumerate(X_LABELS):
    ratio = trad_are[i] / lazy_are[i] if lazy_are[i] > 0 else float('inf')
    print(f"{c:>8}  {lazy_are[i]:>10.2f}  {trad_are[i]:>10.2f}  {lazy_aae[i]:>10.3f}  {trad_aae[i]:>10.3f}  {ratio:>10.2f}")
