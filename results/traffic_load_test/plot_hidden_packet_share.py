#!/usr/bin/env python3
"""Hidden-packet-share charts.

For each load and variant, computes the fraction of true packets lost
to hidden flows, broken down by the size class of those hidden flows.

Two outputs under plots_hidden_packet_share/:
  - hidden_pkt_share_<mode>.png   stacked bar per variant (packet share
                                  by class, stacked, one bar per load)
  - hidden_pkt_share_compare.png  side-by-side total share, lazy vs std
"""

import csv
import os

import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = HERE
OUT = os.path.join(HERE, "plots_hidden_packet_share")
os.makedirs(OUT, exist_ok=True)

LOADS = [1_000_000, 2_000_000, 4_000_000, 8_000_000, 16_000_000]
XLABELS = ["1M", "2M", "4M", "8M", "16M"]

VARIANTS = {
    "Lazy BF":     "lazy_bf2m_cms64x1024",
    "Standard BF": "traditional_bf2m_cms64x1024",
}

CLASSES = ["1pkt", "2pkt", "3pkt", "4_10", "11_100", "101plus"]
CLASS_LABELS = ["1", "2", "3", "4-10", "11-100", "101+"]
CLASS_COLORS = ["#1f77b4", "#17becf", "#2ca02c", "#bcbd22", "#ff7f0e", "#d62728"]


def size_class(pkts):
    if pkts == 1:    return "1pkt"
    if pkts == 2:    return "2pkt"
    if pkts == 3:    return "3pkt"
    if pkts <= 10:   return "4_10"
    if pkts <= 100:  return "11_100"
    return "101plus"


def load_truth(path):
    out = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            k = (row["src_ip"], row["dst_ip"], row["proto"],
                 row["src_port"], row["dst_port"])
            out[k] = int(row["true_pkts"])
    return out


def load_estimate_keys(path):
    keys = set()
    with open(path) as f:
        for row in csv.DictReader(f):
            k = (row["src_ip"], row["dst_ip"], row["proto"],
                 row["src_port"], row["dst_port"])
            keys.add(k)
    return keys


def hidden_packets_by_class(truth, est_keys):
    """Returns (per_class_pkts_dict, total_hidden_pkts, total_true_pkts)."""
    pc = {c: 0 for c in CLASSES}
    total_hidden = 0
    total_true = sum(truth.values())
    for k, pkts in truth.items():
        if k not in est_keys:
            pc[size_class(pkts)] += pkts
            total_hidden += pkts
    return pc, total_hidden, total_true


def build_data(variant_dir):
    """variant_dir -> dict load: { 'pc': {class: pkts}, 'total': X, 'truth': Y }"""
    out = {}
    for n in LOADS:
        truth_path = os.path.join(RESULTS_DIR, f"load_{n}_truth.csv")
        est_path   = os.path.join(RESULTS_DIR, variant_dir, f"est_load_{n}.csv")
        print(f"  {variant_dir} {n//1_000_000}M ... ", end="", flush=True)
        truth = load_truth(truth_path)
        est_keys = load_estimate_keys(est_path)
        pc, total_hidden, total_true = hidden_packets_by_class(truth, est_keys)
        out[n] = {"pc": pc, "total": total_hidden, "truth": total_true}
        share_pct = 100.0 * total_hidden / total_true
        print(f"hidden_pkts={total_hidden:>8,}  total_true={total_true:>10,}  "
              f"share={share_pct:5.2f}%")
    return out


# ---- Build data for both variants ----
data = {}
for name, vdir in VARIANTS.items():
    print(f"\n{name} ({vdir}):")
    data[name] = build_data(vdir)


# ---- Per-variant stacked bar: hidden packet share by class ----
for name in VARIANTS:
    d = data[name]
    fig, ax = plt.subplots(figsize=(6.0, 3.8))
    bottom = [0.0] * len(LOADS)
    for cls, label, color in zip(CLASSES, CLASS_LABELS, CLASS_COLORS):
        shares = [100.0 * d[n]["pc"][cls] / d[n]["truth"] for n in LOADS]
        ax.bar(XLABELS, shares, bottom=bottom, label=label, color=color)
        bottom = [b + s for b, s in zip(bottom, shares)]

    for i, n in enumerate(LOADS):
        total_share = 100.0 * d[n]["total"] / d[n]["truth"]
        ax.text(i, total_share * 1.02, f"{total_share:.2f}%", ha="center",
                fontsize=8, color="#444")

    ax.set_xlabel("traffic load (packets)")
    ax.set_ylabel("hidden packets (% of true)")
    ax.set_title(f"{name} — hidden packet share by hidden-flow class")
    ax.legend(title="hidden flow size", loc="upper left", fontsize=8,
              title_fontsize=8, ncol=2, framealpha=0.95)
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()

    fname = "hidden_pkt_share_" + ("lazy" if name == "Lazy BF" else "standard") + ".png"
    out_path = os.path.join(OUT, fname)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    print(f"[wrote] {out_path}")


# ---- Side-by-side: total hidden packet share lazy vs standard ----
fig, ax = plt.subplots(figsize=(5.6, 3.6))
lazy_share = [100.0 * data["Lazy BF"][n]["total"]     / data["Lazy BF"][n]["truth"]     for n in LOADS]
std_share  = [100.0 * data["Standard BF"][n]["total"] / data["Standard BF"][n]["truth"] for n in LOADS]
ax.plot(XLABELS, lazy_share, marker="o", linewidth=2, label="Lazy BF",     color="#1f77b4")
ax.plot(XLABELS, std_share,  marker="s", linewidth=2, label="Standard BF", color="#d62728")
ax.set_xlabel("traffic load (packets)")
ax.set_ylabel("hidden packet share (% of true)")
ax.set_title("Total hidden packet share — lazy vs standard")
ax.grid(True, linestyle=":", alpha=0.4)
ax.legend()
fig.tight_layout()
out_path = os.path.join(OUT, "hidden_pkt_share_compare.png")
fig.savefig(out_path, dpi=160)
plt.close(fig)
print(f"[wrote] {out_path}")

# ---- Print headline table ----
print()
print(f"{'load':>6}  {'mode':>12}  {'hidden_pkts':>12}  {'total_true':>12}  {'share%':>7}")
for n, lab in zip(LOADS, XLABELS):
    for name in VARIANTS:
        d = data[name][n]
        share = 100.0 * d["total"] / d["truth"]
        print(f"{lab:>6}  {name:>12}  {d['total']:>12,}  {d['truth']:>12,}  {share:7.2f}")
