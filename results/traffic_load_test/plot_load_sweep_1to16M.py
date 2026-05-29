#!/usr/bin/env python3
"""Load-sweep line charts (1M to 16M, lazy vs standard) at bf2m_cms64x1024.

Reads /tmp/load_sweep.csv (10 rows: 2 modes × 5 loads).
Emits one PNG per key metric under plots_load_sweep_1to16M/.
"""

import csv
import os

import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
SRC  = "/tmp/load_sweep.csv"
OUT  = os.path.join(HERE, "plots_load_sweep_1to16M")
os.makedirs(OUT, exist_ok=True)

LOADS = [1_000_000, 2_000_000, 4_000_000, 8_000_000, 16_000_000]
XLABELS = ["1M", "2M", "4M", "8M", "16M"]

# Read into dict: rows[(variant, load)] = full row dict
rows = {}
with open(SRC) as f:
    for r in csv.DictReader(f):
        # The --meta tags land in a single "variant" cell like
        # "lazy,load=8000000". Parse both halves out.
        parts = r["variant"].split(",")
        variant = parts[0]
        load = None
        for p in parts[1:]:
            if p.startswith("load="):
                load = int(p.split("=", 1)[1])
        rows[(variant, load)] = r

def collect(mode, key, scale=1.0):
    return [float(rows[(mode, n)][key]) * scale for n in LOADS]

def make_plot(y_lazy, y_trad, ylabel, fname, log_y=False, ylim=None):
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    ax.plot(XLABELS, y_lazy, marker="o", linewidth=2, label="Lazy BF",     color="#1f77b4")
    ax.plot(XLABELS, y_trad, marker="s", linewidth=2, label="Standard BF", color="#d62728")
    if log_y:
        ax.set_yscale("log")
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.set_xlabel("traffic load (packets)")
    ax.set_ylabel(ylabel)
    ax.grid(True, which="both", linestyle=":", alpha=0.4)
    ax.legend()
    fig.tight_layout()
    out_path = os.path.join(OUT, fname)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    print(f"[wrote] {out_path}")

# ---- Five key metrics ----

# Coverage (%)
make_plot(
    collect("lazy",        "coverage", 100.0),
    collect("traditional", "coverage", 100.0),
    "Coverage (%)", "coverage.png",
    ylim=(0, 105),
)

# ARE (no scale — already a fraction; plot in %)
make_plot(
    collect("lazy",        "ARE", 100.0),
    collect("traditional", "ARE", 100.0),
    "Average relative error (%)", "are.png",
)

# AAE (packets)
make_plot(
    collect("lazy",        "AAE"),
    collect("traditional", "AAE"),
    "Average absolute error (packets)", "aae.png",
)

# Exact rate (%)
make_plot(
    collect("lazy",        "pct_exact", 100.0),
    collect("traditional", "pct_exact", 100.0),
    "Flows reconstructed exactly (%)", "pct_exact.png",
    ylim=(0, 105),
)

# Alg6 share (%) — only meaningful at heavy load
make_plot(
    collect("lazy",        "alg6_pct", 100.0),
    collect("traditional", "alg6_pct", 100.0),
    "Bucket-solver flows using alg6 (%)", "alg6_share.png",
    ylim=(0, 105),
)

# Hidden-flow share (%) — fraction of true flows the BF didn't expose
def hidden_share(mode):
    out = []
    for n in LOADS:
        r = rows[(mode, n)]
        out.append(100.0 * int(r["hidden_flows"]) / int(r["true_flows"]))
    return out

make_plot(
    hidden_share("lazy"),
    hidden_share("traditional"),
    "Hidden flows (% of true)", "hidden_share.png",
)

# ---- Print the table ----
print()
hdr = f"{'load':>6}  {'mode':>12}  {'cov%':>6}  {'pkt%':>7}  {'AAE':>8}  {'ARE%':>8}  {'exact%':>7}  {'alg6%':>7}"
print(hdr)
print("-" * len(hdr))
for n, lab in zip(LOADS, XLABELS):
    for mode in ("lazy", "traditional"):
        r = rows[(mode, n)]
        print(f"{lab:>6}  {mode:>12}  {float(r['coverage'])*100:6.2f}  "
              f"{float(r['packet_acc'])*100:7.2f}  {float(r['AAE']):8.2f}  "
              f"{float(r['ARE'])*100:8.2f}  {float(r['pct_exact'])*100:7.2f}  "
              f"{float(r['alg6_pct'])*100:7.2f}")
