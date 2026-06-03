#!/usr/bin/env python3
"""Compute flow distribution by size class and capture rates (CMS256).

For each load, reads truth files from all 3 traces and computes:
1. True distribution of flows by size class
2. Percentage of each class that is captured (visible) vs hidden
"""

import csv
import os
import statistics

# Truth files are in the cms64 directory
TRAFFIC_LOAD_TEST = os.path.join(os.path.dirname(__file__), "..", "traffic_load_test")
TRUTH_ROOTS = {
    "130000": TRAFFIC_LOAD_TEST,
    "130100": os.path.join(TRAFFIC_LOAD_TEST, "130100"),
    "130200": os.path.join(TRAFFIC_LOAD_TEST, "130200"),
}

# Estimate files are in cms256
HERE = os.path.dirname(os.path.abspath(__file__))
EST_ROOTS = {
    "130000": os.path.join(HERE, "130000"),
    "130100": os.path.join(HERE, "130100"),
    "130200": os.path.join(HERE, "130200"),
}

MODES = {
    "lazy":        "lazy_bf2m_cms256x1024",
    "traditional": "traditional_bf2m_cms256x1024",
}

LOADS = [1_000_000, 2_000_000, 4_000_000, 8_000_000, 16_000_000]
XLABELS = ["1M", "2M", "4M", "8M", "16M"]

CLASSES = ["1pkt", "2pkt", "3pkt", "4_10", "11_100", "101plus"]
CLASS_LABELS = ["1 pkt", "2 pkt", "3 pkt", "4-10", "11-100", "101+"]


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


def compute_flow_distribution(truth_csv):
    """Compute distribution of flows by size class from truth CSV."""
    counts = {c: 0 for c in CLASSES}
    with open(truth_csv) as f:
        for r in csv.DictReader(f):
            pkts = int(r["true_pkts"])
            counts[size_class(pkts)] += 1
    return counts


def compute_capture_rates(truth_csv, est_csv, mode_full):
    """Compute capture rate (% of visible flows) for each size class."""
    truth_counts = {c: 0 for c in CLASSES}
    visible_counts = {c: 0 for c in CLASSES}

    # Load truth
    truth_keys = {}
    with open(truth_csv) as f:
        for r in csv.DictReader(f):
            k = (r["src_ip"], r["dst_ip"], r["proto"], r["src_port"], r["dst_port"])
            pkts = int(r["true_pkts"])
            cls = size_class(pkts)
            truth_keys[k] = cls
            truth_counts[cls] += 1

    # Load estimates
    est_keys = set()
    with open(est_csv) as f:
        for r in csv.DictReader(f):
            k = (r["src_ip"], r["dst_ip"], r["proto"], r["src_port"], r["dst_port"])
            est_keys.add(k)

    # Count visible (captured) flows
    for k, cls in truth_keys.items():
        if k in est_keys:
            visible_counts[cls] += 1

    return truth_counts, visible_counts


def build_data(mode_short):
    """Returns aggregated data across 3 traces."""
    trace_data = {}

    for load_int, load_label in zip(LOADS, XLABELS):
        all_truth_counts = {c: [] for c in CLASSES}
        all_visible_counts = {c: [] for c in CLASSES}

        for trace in TRUTH_ROOTS:
            tp = truth_path(trace, load_int)
            mode_full = MODES[mode_short]
            ep = est_path(trace, mode_full, load_int)

            if not (os.path.exists(tp) and os.path.exists(ep)):
                print(f"[skip] {trace} {load_label} {mode_short}: missing files")
                continue

            truth_counts, visible_counts = compute_capture_rates(tp, ep, mode_full)
            for c in CLASSES:
                all_truth_counts[c].append(truth_counts[c])
                all_visible_counts[c].append(visible_counts[c])

        # Aggregate across traces
        mean_truth = {c: statistics.mean(all_truth_counts[c]) if all_truth_counts[c] else 0
                     for c in CLASSES}
        mean_visible = {c: statistics.mean(all_visible_counts[c]) if all_visible_counts[c] else 0
                       for c in CLASSES}

        trace_data[load_label] = (mean_truth, mean_visible)

    return trace_data


# Compute for both modes
print("\n=== FLOW DISTRIBUTION AND CAPTURE RATES (CMS256) ===\n")

for mode_label, mode_short in [("Lazy BF", "lazy"), ("Standard BF", "traditional")]:
    data = build_data(mode_short)

    print(f"\n{mode_label}:")
    print(f"{'Load':>5}  " + "  ".join(f"{c:>9}" for c in CLASS_LABELS) + "  " + f"{'Total':>9}")
    print("-" * 100)

    for load_label in XLABELS:
        mean_truth, mean_visible = data[load_label]
        total_true = sum(mean_truth[c] for c in CLASSES)
        cells = [f"{int(mean_truth[c]):>9,}" for c in CLASSES]
        print(f"{load_label:>5}  " + "  ".join(cells) + f"  {int(total_true):>9,}")

    print("\nCapture rates (% of flows visible / captured):")
    print(f"{'Load':>5}  " + "  ".join(f"{c:>11}" for c in CLASS_LABELS))
    print("-" * 100)

    for load_label in XLABELS:
        mean_truth, mean_visible = data[load_label]
        rates = []
        for c in CLASSES:
            if mean_truth[c] > 0:
                rate = 100.0 * mean_visible[c] / mean_truth[c]
                rates.append(f"{rate:>10.1f}%")
            else:
                rates.append(f"{'n/a':>10}")
        print(f"{load_label:>5}  " + "  ".join(rates))

# Compute cms64 for comparison
print("\n\n=== FLOW DISTRIBUTION (CMS64 for comparison) ===\n")

TRAFFIC_LOAD_CMS64 = TRAFFIC_LOAD_TEST
TRUTH_ROOTS_CMS64 = {
    "130000": TRAFFIC_LOAD_CMS64,
    "130100": os.path.join(TRAFFIC_LOAD_CMS64, "130100"),
    "130200": os.path.join(TRAFFIC_LOAD_CMS64, "130200"),
}

def build_data_cms64():
    """Returns aggregated data across 3 traces for cms64."""
    trace_data = {}

    for load_int, load_label in zip(LOADS, XLABELS):
        all_true_counts = {c: 0 for c in CLASSES}

        for trace in TRUTH_ROOTS_CMS64:
            tp = os.path.join(TRUTH_ROOTS_CMS64[trace], f"load_{load_int}_truth.csv")
            if not os.path.exists(tp):
                print(f"[skip] {trace} {load_label}: missing truth file")
                continue

            dist = compute_flow_distribution(tp)
            for c in CLASSES:
                all_true_counts[c] += dist[c]

        # Average across traces
        mean_counts = {c: all_true_counts[c] / 3 for c in CLASSES}
        trace_data[load_label] = mean_counts

    return trace_data

data_cms64 = build_data_cms64()

print("Distribution of flows in traces (averaged across 3 CAIDA captures):")
print(f"{'Load':>5}  " + "  ".join(f"{c:>11}" for c in CLASS_LABELS) + "  " + f"{'Total':>9}")
print("-" * 120)

for load_label in XLABELS:
    mean_counts = data_cms64[load_label]
    total = sum(mean_counts[c] for c in CLASSES)
    cells = [f"{int(mean_counts[c]):>11,}" for c in CLASSES]
    print(f"{load_label:>5}  " + "  ".join(cells) + f"  {int(total):>9,}")

print("\nPercentage of total flows in each class:")
print(f"{'Load':>5}  " + "  ".join(f"{c:>11}" for c in CLASS_LABELS))
print("-" * 120)

for load_label in XLABELS:
    mean_counts = data_cms64[load_label]
    total = sum(mean_counts[c] for c in CLASSES)
    pcts = []
    for c in CLASSES:
        pct = 100.0 * mean_counts[c] / total
        pcts.append(f"{pct:>10.1f}%")
    print(f"{load_label:>5}  " + "  ".join(pcts))
