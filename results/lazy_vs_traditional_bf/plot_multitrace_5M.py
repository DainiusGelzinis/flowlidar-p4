#!/usr/bin/env python3
"""§5.1 Figure 4 — 5M / 10-variant BF sweep, 3-trace mean lines.

Reads the three per-trace summary CSVs (130000 baseline + 130100/130200
validation) and plots coverage, ARE, AAE, exact rate vs Bloom Filter
size for the lazy and traditional update policies.

Output: plots_multitrace_5M/{coverage,are,aae,exact}.png
"""

import csv
import os
import statistics

import matplotlib.pyplot as plt

plt.rcParams.update({
    "font.size":        15,
    "axes.titlesize":   17,
    "axes.labelsize":   16,
    "xtick.labelsize":  14,
    "ytick.labelsize":  14,
    "legend.fontsize":  14,
})

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "plots_multitrace_5M")
os.makedirs(OUT, exist_ok=True)

# 130000 summary lives at the root (older convention); others are in subdirs
SUMMARIES = {
    "130000": os.path.join(HERE, "summary_chunk0.csv"),
    "130100": os.path.join(HERE, "130100", "summary_chunk0.csv"),
    "130200": os.path.join(HERE, "130200", "summary_chunk0.csv"),
}

BF_SIZES = [131072, 262144, 524288, 1048576, 2097152]
XLABELS  = ["131K", "262K", "524K", "1M", "2M"]

MODES = {
    "lazy":        ["lazy_bf131k_cms256x1024", "lazy_bf262k_cms256x1024",
                    "lazy_bf524k_cms256x1024", "lazy_bf1m_cms256x1024",
                    "lazy_bf2m_cms256x1024"],
    "traditional": ["traditional_bf131k_cms256x1024", "traditional_bf262k_cms256x1024",
                    "traditional_bf524k_cms256x1024", "traditional_bf1m_cms256x1024",
                    "traditional_bf2m_cms256x1024"],
}

# rows[(mode_short, bf_size, trace)] = row dict
rows = {}
for trace, path in SUMMARIES.items():
    with open(path) as f:
        for r in csv.DictReader(f):
            parts = r["variant"].split(",")
            variant_full = parts[0]
            # find mode + bf size
            mode = None
            idx  = None
            for m, vs in MODES.items():
                if variant_full in vs:
                    mode = m
                    idx  = vs.index(variant_full)
                    break
            if mode is None:
                continue
            rows[(mode, BF_SIZES[idx], trace)] = r

print("rows loaded:")
for mode in MODES:
    for sz, lab in zip(BF_SIZES, XLABELS):
        present = [t for t in SUMMARIES if (mode, sz, t) in rows]
        print(f"  {mode:>11} {lab:>5}  traces: {present}")


def collect_mean(mode, key, scale=1.0):
    means, stds = [], []
    for sz in BF_SIZES:
        vals = [float(rows[(mode, sz, t)][key]) * scale
                for t in SUMMARIES if (mode, sz, t) in rows]
        means.append(statistics.mean(vals))
        stds.append(statistics.stdev(vals) if len(vals) > 1 else 0.0)
    return means, stds


def make_plot(mlazy, slazy, mtrad, strad, ylabel, fname, ylim=None):
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    ax.plot(XLABELS, mlazy, marker="o", linewidth=2,
            label="Lazy BF",     color="#1f77b4")
    ax.plot(XLABELS, mtrad, marker="s", linewidth=2,
            label="Standard BF", color="#d62728")
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.set_xlabel("Bloom Filter size (bits per row)")
    ax.set_ylabel(ylabel, fontsize=14)
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.legend()
    fig.tight_layout(pad=0.2)
    out_path = os.path.join(OUT, fname)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    print(f"[wrote] {out_path}")


def hidden_share(mode):
    means, stds = [], []
    for sz in BF_SIZES:
        vals = []
        for t in SUMMARIES:
            r = rows.get((mode, sz, t))
            if r is not None:
                vals.append(100.0 * int(r["hidden_flows"]) / int(r["true_flows"]))
        means.append(statistics.mean(vals))
        stds.append(statistics.stdev(vals) if len(vals) > 1 else 0.0)
    return means, stds

ml, sl = hidden_share("lazy")
mt, st = hidden_share("traditional")
make_plot(ml, sl, mt, st, "Hidden flows (% of true)", "hidden_share.png")

ml, sl = collect_mean("lazy",        "ARE", 100.0)
mt, st = collect_mean("traditional", "ARE", 100.0)
make_plot(ml, sl, mt, st, "Average relative error (%)", "are.png")

ml, sl = collect_mean("lazy",        "AAE")
mt, st = collect_mean("traditional", "AAE")
make_plot(ml, sl, mt, st, "Average absolute error", "aae.png")

ml, sl = collect_mean("lazy",        "pct_exact", 100.0)
mt, st = collect_mean("traditional", "pct_exact", 100.0)
make_plot(ml, sl, mt, st, "Flows reconstructed exactly (%)", "exact.png",
          ylim=(0, 100))


print()
hdr = f"{'BF':>5}  {'mode':>12}  {'cov%':>10}  {'ARE%':>12}  {'AAE':>10}  {'exact%':>11}"
print(hdr)
print("-" * len(hdr))
for sz, lab in zip(BF_SIZES, XLABELS):
    for mode in ("lazy", "traditional"):
        cv = [float(rows[(mode, sz, t)]["coverage"]) * 100 for t in SUMMARIES if (mode, sz, t) in rows]
        ar = [float(rows[(mode, sz, t)]["ARE"])      * 100 for t in SUMMARIES if (mode, sz, t) in rows]
        ae = [float(rows[(mode, sz, t)]["AAE"])             for t in SUMMARIES if (mode, sz, t) in rows]
        ex = [float(rows[(mode, sz, t)]["pct_exact"]) * 100 for t in SUMMARIES if (mode, sz, t) in rows]
        def fmt(xs):
            if len(xs) <= 1: return f"{xs[0]:.2f}±0.00"
            return f"{statistics.mean(xs):.2f}±{statistics.stdev(xs):.2f}"
        print(f"{lab:>5}  {mode:>12}  {fmt(cv):>10}  {fmt(ar):>12}  {fmt(ae):>10}  {fmt(ex):>11}")
