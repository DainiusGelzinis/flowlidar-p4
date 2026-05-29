#!/usr/bin/env python3
"""Stacked bar charts: hidden flows broken down by true-packet size class.

For each load × variant, finds flows present in the truth CSV but NOT in
the estimate CSV (= hidden flows), then buckets them by their true packet
count into the same size classes compare.py uses. Emits one bar chart per
variant under plots_hidden_by_class/.
"""

import csv
import os

import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = HERE
OUT = os.path.join(HERE, "plots_hidden_by_class")
os.makedirs(OUT, exist_ok=True)

LOADS = [1_000_000, 2_000_000, 4_000_000, 8_000_000, 16_000_000]
XLABELS = ["1M", "2M", "4M", "8M", "16M"]

VARIANTS = {
    "Lazy BF":     "lazy_bf2m_cms64x1024",
    "Standard BF": "traditional_bf2m_cms64x1024",
}

CLASSES = ["1pkt", "2pkt", "3pkt", "4_10", "11_100", "101plus"]
CLASS_LABELS = ["1", "2", "3", "4-10", "11-100", "101+"]
# Stack colors from small (cool) to large (warm)
CLASS_COLORS = ["#1f77b4", "#17becf", "#2ca02c", "#bcbd22", "#ff7f0e", "#d62728"]


def size_class(pkts):
    if pkts == 1:    return "1pkt"
    if pkts == 2:    return "2pkt"
    if pkts == 3:    return "3pkt"
    if pkts <= 10:   return "4_10"
    if pkts <= 100:  return "11_100"
    return "101plus"


def load_truth_keys(path):
    keys = {}                    # 5-tuple -> true packet count
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            k = (row["src_ip"], row["dst_ip"], row["proto"],
                 row["src_port"], row["dst_port"])
            keys[k] = int(row["true_pkts"])
    return keys


def load_estimate_keys(path):
    keys = set()
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            k = (row["src_ip"], row["dst_ip"], row["proto"],
                 row["src_port"], row["dst_port"])
            keys.add(k)
    return keys


def hidden_per_class(truth_keys, est_keys):
    buckets = {c: 0 for c in CLASSES}
    for k, true_pkts in truth_keys.items():
        if k not in est_keys:
            buckets[size_class(true_pkts)] += 1
    return buckets


def build_data(variant_dir):
    """Returns: per-class counts keyed by load, plus the per-load totals."""
    rows = {}                    # load -> {class: count}
    totals = {}                  # load -> total hidden
    for n in LOADS:
        truth_path = os.path.join(RESULTS_DIR, f"load_{n}_truth.csv")
        est_path   = os.path.join(RESULTS_DIR, variant_dir, f"est_load_{n}.csv")
        print(f"  {variant_dir} {n//1_000_000}M  ... ", end="", flush=True)
        truth = load_truth_keys(truth_path)
        est   = load_estimate_keys(est_path)
        bucket = hidden_per_class(truth, est)
        rows[n] = bucket
        totals[n] = sum(bucket.values())
        print(f"hidden={totals[n]:>6}  by class: " +
              " ".join(f"{c}={bucket[c]}" for c in CLASSES))
    return rows, totals


def make_chart(name, variant_dir, fname):
    print(f"\nProcessing {name} ({variant_dir}):")
    data, totals = build_data(variant_dir)

    fig, ax = plt.subplots(figsize=(6.0, 3.8))
    bottom = [0.0] * len(LOADS)
    for cls, label, color in zip(CLASSES, CLASS_LABELS, CLASS_COLORS):
        counts = [data[n][cls] for n in LOADS]
        ax.bar(XLABELS, counts, bottom=bottom, label=label, color=color)
        bottom = [b + c for b, c in zip(bottom, counts)]

    # Annotate totals above each bar
    for i, n in enumerate(LOADS):
        ax.text(i, totals[n] * 1.02, f"{totals[n]:,}", ha="center",
                fontsize=8, color="#444")

    ax.set_xlabel("traffic load (packets)")
    ax.set_ylabel("hidden flows (count)")
    ax.set_title(f"{name} — hidden flows by true size class")
    ax.legend(title="true packets", loc="upper left",
              fontsize=8, title_fontsize=8, ncol=2, framealpha=0.95)
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    out_path = os.path.join(OUT, fname)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    print(f"[wrote] {out_path}")


for name, variant_dir in VARIANTS.items():
    fname = "hidden_" + variant_dir.split("_")[0] + ".png"
    make_chart(name, variant_dir, fname)
