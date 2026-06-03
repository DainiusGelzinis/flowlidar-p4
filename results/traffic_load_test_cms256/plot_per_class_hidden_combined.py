#!/usr/bin/env python3
"""Hidden-flow distribution over loads for cms256 configuration.

For each load in {1M, 2M, 4M, 8M, 16M}, computes the number of hidden
flows (in truth but missing from the CP output) broken down by
true-packet-count class (1, 2, 3, 4-10, 11-100, 101+). Averages across
the three traces (130000, 130100, 130200).

Emits combined chart: hidden_dist_combined.png (Lazy vs Standard side-by-side).
"""

import csv
import os
import statistics

import matplotlib.pyplot as plt
import numpy as np

plt.rcParams.update({
    "font.size":        13,
    "axes.titlesize":   15,
    "axes.labelsize":   14,
    "xtick.labelsize":  12,
    "ytick.labelsize":  12,
    "legend.fontsize":  12,
})

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "plots_per_class_multitrace")
os.makedirs(OUT, exist_ok=True)

# Truth files are shared from the cms64 traffic_load_test directory
TRAFFIC_LOAD_TEST = os.path.join(os.path.dirname(HERE), "traffic_load_test")
TRUTH_ROOTS = {
    "130000": TRAFFIC_LOAD_TEST,
    "130100": os.path.join(TRAFFIC_LOAD_TEST, "130100"),
    "130200": os.path.join(TRAFFIC_LOAD_TEST, "130200"),
}

# Estimates live in <root>/<variant>/
EST_ROOTS = {
    "130000": os.path.join(HERE, "130000"),
    "130100": os.path.join(HERE, "130100"),
    "130200": os.path.join(HERE, "130200"),
}

MODES = {
    "lazy":        "lazy_bf2m_cms256x1024",
    "traditional": "traditional_bf2m_cms256x1024",
}

LOADS    = [1_000_000, 2_000_000, 4_000_000, 8_000_000, 16_000_000]
XLABELS  = ["1M", "2M", "4M", "8M", "16M"]

CLASSES      = ["1pkt", "2pkt", "3pkt", "4_10", "11_100", "101plus"]
CLASS_LABELS = ["1 pkt", "2 pkt", "3 pkt", "4-10", "11-100", "101+"]
CLASS_COLORS = ["#1f77b4", "#17becf", "#2ca02c", "#bcbd22", "#ff7f0e", "#d62728"]


def size_class(p):
    if p == 1: return "1pkt"
    if p == 2: return "2pkt"
    if p == 3: return "3pkt"
    if p <= 10: return "4_10"
    if p <= 100: return "11_100"
    return "101plus"


def truth_path(trace, load):
    return os.path.join(TRUTH_ROOTS[trace], f"load_{load}_truth.csv")


def est_path(trace, mode_full, load):
    return os.path.join(EST_ROOTS[trace], mode_full, f"est_load_{load}.csv")


def hidden_counts_per_class(truth_csv, est_csv):
    truth = {}
    with open(truth_csv) as f:
        for r in csv.DictReader(f):
            k = (r["src_ip"], r["dst_ip"], r["proto"], r["src_port"], r["dst_port"])
            truth[k] = int(r["true_pkts"])
    est_keys = set()
    with open(est_csv) as f:
        for r in csv.DictReader(f):
            k = (r["src_ip"], r["dst_ip"], r["proto"], r["src_port"], r["dst_port"])
            est_keys.add(k)
    counts = {c: 0 for c in CLASSES}
    for k, pkts in truth.items():
        if k not in est_keys:
            counts[size_class(pkts)] += 1
    return counts


def build_data(mode_short):
    """Returns dict[load][class] = mean count across 3 traces."""
    out = {n: {c: [] for c in CLASSES} for n in LOADS}
    mode_full = MODES[mode_short]
    for n in LOADS:
        for t in TRUTH_ROOTS:
            tp = truth_path(t, n)
            ep = est_path(t, mode_full, n)
            if not (os.path.exists(tp) and os.path.exists(ep)):
                print(f"[skip] {t} {n} {mode_short}: missing file")
                continue
            cls_counts = hidden_counts_per_class(tp, ep)
            for c in CLASSES:
                out[n][c].append(cls_counts[c])
    # collapse to means
    means = {}
    for n in LOADS:
        means[n] = {c: (statistics.mean(out[n][c]) if out[n][c] else 0)
                    for c in CLASSES}
    return means


def combined_grouped_bar(fname):
    print("Processing combined Lazy + Standard (CMS256):")
    lazy_data = build_data("lazy")
    trad_data = build_data("traditional")

    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    x = np.arange(len(LOADS))
    bar_width = 0.36

    def stack_at(positions, data_dict):
        bottoms = np.zeros(len(LOADS))
        for cls, label, color in zip(CLASSES, CLASS_LABELS, CLASS_COLORS):
            heights = np.array([data_dict[n][cls] for n in LOADS])
            ax.bar(positions, heights, bar_width, bottom=bottoms,
                   color=color, edgecolor="black", linewidth=0.4)
            bottoms += heights
        return bottoms

    lazy_totals = stack_at(x - bar_width/2 - 0.02, lazy_data)
    trad_totals = stack_at(x + bar_width/2 + 0.02, trad_data)

    # totals above each bar
    for i in range(len(LOADS)):
        ax.text(x[i] - bar_width/2 - 0.02, lazy_totals[i] + 1500,
                f"{int(lazy_totals[i]):,}", ha="center", fontsize=11, color="#222")
        ax.text(x[i] + bar_width/2 + 0.02, trad_totals[i] + 1500,
                f"{int(trad_totals[i]):,}", ha="center", fontsize=11, color="#222")

    # L / S labels below each bar
    for i in range(len(LOADS)):
        ax.text(x[i] - bar_width/2 - 0.02, -2200, "L",
                ha="center", fontsize=12, color="#1f77b4", fontweight="bold")
        ax.text(x[i] + bar_width/2 + 0.02, -2200, "S",
                ha="center", fontsize=12, color="#d62728", fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(XLABELS)
    ax.set_ylim(0, 43000)
    ax.set_xlabel("Traffic load (packets per epoch)")
    ax.set_ylabel("Hidden flows")
    ax.set_title("Hidden-flow distribution: Lazy (L) vs Standard (S)")
    # class-color legend only; mode disambiguation via L/S labels under bars
    handles = [plt.Rectangle((0, 0), 1, 1, color=c, edgecolor="black", linewidth=0.4)
               for c in CLASS_COLORS]
    ax.legend(handles, CLASS_LABELS, title="True packets",
              loc="upper left", fontsize=10, title_fontsize=10, ncol=2,
              framealpha=0.95)
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()

    out_path = os.path.join(OUT, fname)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    print(f"[wrote] {out_path}")


combined_grouped_bar("hidden_dist_combined.png")

# Headline table
print()
print("=== hidden-flow counts per class, 3-trace mean (CMS256) ===")
for mode_label, mode_short in [("Lazy", "lazy"), ("Standard", "traditional")]:
    data = build_data(mode_short)
    print(f"\n{mode_label}:")
    hdr = f"{'load':>5}  " + "  ".join(f"{c:>9}" for c in CLASS_LABELS) + "  " + f"{'total':>9}"
    print(hdr)
    print("-" * len(hdr))
    for n, lab in zip(LOADS, XLABELS):
        cells = [f"{int(data[n][c]):>9,}" for c in CLASSES]
        total = sum(data[n][c] for c in CLASSES)
        print(f"{lab:>5}  " + "  ".join(cells) + f"  {int(total):>9,}")
