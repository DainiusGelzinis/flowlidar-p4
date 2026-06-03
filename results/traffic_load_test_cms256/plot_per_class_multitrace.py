#!/usr/bin/env python3
"""§5.3 per-class ARE/AAE at 4M and 8M, 3-trace mean — cms256 variant.

Mirror of traffic_load_test/plot_per_class_multitrace.py but using the
cms256x1024 sweep data. Reads the three per-trace summaries and plots
per-class ARE and AAE markers (lazy vs traditional) at 4M and 8M loads.

Output: plots_per_class_multitrace/{4M,8M}_{are,aae}.png
"""

import csv
import os
import statistics

import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "plots_per_class_multitrace")
os.makedirs(OUT, exist_ok=True)

SUMMARIES = {
    "130000": os.path.join(HERE, "130000", "summary.csv"),
    "130100": os.path.join(HERE, "130100", "summary.csv"),
    "130200": os.path.join(HERE, "130200", "summary.csv"),
}

CLASSES       = ["1pkt", "2pkt", "3pkt", "4_10", "11_100", "101plus"]
CLASS_LABELS  = ["1", "2", "3", "4-10", "11-100", "101+"]

MODES = {
    "lazy":        "lazy_bf2m_cms256x1024",
    "traditional": "traditional_bf2m_cms256x1024",
}

LOADS = {"4M": 4_000_000, "8M": 8_000_000}

# rows[(mode_short, load_int, trace)] = row dict
rows = {}
for trace, path in SUMMARIES.items():
    with open(path) as f:
        for r in csv.DictReader(f):
            parts = r["variant"].split(",")
            variant_full = parts[0]
            load = None
            for p in parts[1:]:
                if p.startswith("load="):
                    load = int(p.split("=", 1)[1])
            mode = next((m for m, v in MODES.items() if v == variant_full), None)
            if mode is None or load is None:
                continue
            rows[(mode, load, trace)] = r


def collect_class_stats(mode, load_int, metric):
    """metric in {'AAE', 'ARE'}. Returns (means, stds) per class."""
    means, stds = [], []
    for cls in CLASSES:
        key = f"{metric}_{cls}"
        vals = []
        for t in SUMMARIES:
            r = rows.get((mode, load_int, t))
            if r is None or r.get(key, "") == "":
                continue
            vals.append(float(r[key]))
        if not vals:
            means.append(0.0); stds.append(0.0)
            continue
        means.append(statistics.mean(vals))
        stds.append(statistics.stdev(vals) if len(vals) > 1 else 0.0)
    return means, stds


def grouped_bar(load_label, load_int, metric, ylabel, fname, log_y=False):
    mlazy, _ = collect_class_stats("lazy",        load_int, metric)
    mtrad, _ = collect_class_stats("traditional", load_int, metric)

    x = np.arange(len(CLASSES))
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.plot(x, mlazy, marker="o", markersize=9, linestyle="none",
            label="Lazy BF",     color="#1f77b4")
    ax.plot(x, mtrad, marker="s", markersize=9, linestyle="none",
            label="Standard BF", color="#d62728")

    if log_y:
        ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(CLASS_LABELS)
    ax.set_xlabel("True packet count class")
    ax.set_ylabel(ylabel)
    ax.set_title(f"{load_label} load — {metric} by flow size class")
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)
    ax.legend()
    fig.tight_layout()
    out_path = os.path.join(OUT, fname)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    print(f"[wrote] {out_path}")


for load_label, load_int in LOADS.items():
    grouped_bar(load_label, load_int, "ARE",
                "Average relative error (%)", f"{load_label.lower()}_are.png", log_y=True)
    grouped_bar(load_label, load_int, "AAE",
                "Average absolute error (packets)", f"{load_label.lower()}_aae.png", log_y=True)


# ---- Headline table ----
print()
hdr = f"{'load':>5}  {'mode':>12}  " + "  ".join(f"{c:>11}" for c in CLASS_LABELS)
print(f"=== ARE (% with 3-trace ±std) ===")
print(hdr)
print("-" * len(hdr))
for load_label, load_int in LOADS.items():
    for mode in ("lazy", "traditional"):
        cells = []
        for cls in CLASSES:
            key = f"ARE_{cls}"
            vals = []
            for t in SUMMARIES:
                r = rows.get((mode, load_int, t))
                if r is not None and r.get(key, "") != "":
                    vals.append(100.0 * float(r[key]))
            if not vals:
                cells.append("n/a")
            elif len(vals) == 1:
                cells.append(f"{vals[0]:.2f}±0.00")
            else:
                cells.append(f"{statistics.mean(vals):.2f}±{statistics.stdev(vals):.2f}")
        print(f"{load_label:>5}  {mode:>12}  " + "  ".join(f"{c:>11}" for c in cells))
