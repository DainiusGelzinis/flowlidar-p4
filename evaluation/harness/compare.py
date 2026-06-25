#!/usr/bin/env python3
"""
compare.py — join per-flow truth + per-flow CP estimate, compute metrics,
append one row to a summary CSV.

Usage:
    compare.py TRUTH_CSV ESTIMATE_CSV SUMMARY_CSV [--meta key=value ...]

The optional --meta arguments are tagged on to the summary row so the
harness can attach (variant, pcap, chunk_size, run_id, speed_mbps, etc.)
to each test point. Anything not provided will be left blank.

Truth CSV format (from truth_csv.sh):
    src_ip,dst_ip,proto,src_port,dst_port,true_pkts

Estimate CSV format (from C++/Python CP --csv-out):
    src_ip,dst_ip,proto,src_port,dst_port,digest_count,estimated_packets,solver_path

Summary CSV row (appended; header written automatically if file empty):
    timestamp, ... --meta cols ... ,
    true_flows, visible_flows, hidden_flows, coverage,
    true_packets, est_packets, packet_acc,
    AAE, ARE, pct_exact,
    alg4_pct, alg5_pct, exact_pct, alg6_pct, min_pct,
    AAE_1pkt, AAE_2pkt, AAE_3pkt, AAE_4_10, AAE_11_100, AAE_101plus,
    ARE_1pkt, ARE_2pkt, ARE_3pkt, ARE_4_10, ARE_11_100, ARE_101plus
"""
import sys
import os
import csv
import time
import argparse
from collections import defaultdict

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("truth")
    p.add_argument("estimate")
    p.add_argument("summary")
    p.add_argument("--meta", action="append", default=[],
                   help='Tag the row with "key=value" (repeatable)')
    p.add_argument("--quiet", action="store_true",
                   help="Suppress the human-readable summary print")
    return p.parse_args()

def load_truth(path):
    flows = {}
    with open(path) as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            if len(row) < 6:
                continue
            key = tuple(row[0:5])
            flows[key] = int(row[5])
    return flows

def load_estimate(path):
    flows = {}
    with open(path) as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            if len(row) < 8:
                continue
            key = tuple(row[0:5])
            flows[key] = (int(row[5]), int(row[6]), row[7])
    return flows

def size_class(pkts):
    if pkts == 1:    return "1pkt"
    if pkts == 2:    return "2pkt"
    if pkts == 3:    return "3pkt"
    if pkts <= 10:   return "4_10"
    if pkts <= 100:  return "11_100"
    return "101plus"

def mean(xs):
    if not xs: return 0.0
    return sum(xs) / len(xs)

def main():
    args = parse_args()

    truth = load_truth(args.truth)
    est   = load_estimate(args.estimate)

    visible = set(est.keys()) & set(truth.keys())
    hidden  = set(truth.keys()) - set(est.keys())
    spurious = set(est.keys()) - set(truth.keys())

    true_pkts_total = sum(truth.values())
    est_pkts_total  = sum(v[1] for v in est.values())

    abs_err   = []
    rel_err   = []
    exacts    = 0
    per_class = defaultdict(lambda: {"abs": [], "rel": []})
    path_counts = defaultdict(int)

    for k in visible:
        true_pkts = truth[k]
        est_pkts  = est[k][1]
        path      = est[k][2]
        path_counts[path] += 1
        err = abs(est_pkts - true_pkts)
        abs_err.append(err)
        if true_pkts > 0:
            rel_err.append(err / true_pkts)
        if est_pkts == true_pkts:
            exacts += 1
        cls = size_class(true_pkts)
        per_class[cls]["abs"].append(err)
        if true_pkts > 0:
            per_class[cls]["rel"].append(err / true_pkts)

    n_true    = len(truth)
    n_visible = len(visible)
    n_hidden  = len(hidden)

    summary = {
        "timestamp":    time.strftime("%Y-%m-%dT%H:%M:%S"),
        "true_flows":   n_true,
        "visible_flows": n_visible,
        "hidden_flows":  n_hidden,
        "spurious_flows": len(spurious),
        "coverage":     n_visible / n_true if n_true else 0.0,
        "true_packets": true_pkts_total,
        "est_packets":  est_pkts_total,
        "packet_acc":   est_pkts_total / true_pkts_total if true_pkts_total else 0.0,
        "AAE":          mean(abs_err),
        "ARE":          mean(rel_err),
        "pct_exact":    exacts / n_visible if n_visible else 0.0,
        "alg4_pct":     path_counts.get("alg4", 0)  / n_visible if n_visible else 0.0,
        "alg5_pct":     path_counts.get("alg5", 0)  / n_visible if n_visible else 0.0,
        "exact_pct":    path_counts.get("exact", 0) / n_visible if n_visible else 0.0,
        "alg6_pct":     path_counts.get("alg6", 0)  / n_visible if n_visible else 0.0,
        "min_pct":      path_counts.get("min", 0)   / n_visible if n_visible else 0.0,
    }
    for cls in ("1pkt", "2pkt", "3pkt", "4_10", "11_100", "101plus"):
        summary[f"AAE_{cls}"] = mean(per_class[cls]["abs"])
        summary[f"ARE_{cls}"] = mean(per_class[cls]["rel"])

    meta = {}
    for kv in args.meta:
        if "=" in kv:
            k, v = kv.split("=", 1)
            meta[k] = v

    columns = list(meta.keys()) + list(summary.keys())
    row     = {**meta, **summary}

    new_file = not os.path.exists(args.summary) or os.path.getsize(args.summary) == 0
    with open(args.summary, "a") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        if new_file:
            w.writeheader()
        w.writerow(row)

    if not args.quiet:
        print(f"Wrote 1 row to {args.summary}")
        print(f"  coverage   : {summary['coverage']*100:.2f}%  "
              f"({n_visible}/{n_true})")
        print(f"  packet_acc : {summary['packet_acc']*100:.2f}%  "
              f"({est_pkts_total}/{true_pkts_total})")
        print(f"  AAE        : {summary['AAE']:.3f}")
        print(f"  ARE        : {summary['ARE']:.4f}")
        print(f"  pct_exact  : {summary['pct_exact']*100:.2f}%")
        print(f"  paths      : alg4={summary['alg4_pct']*100:.1f}%  "
              f"alg5={summary['alg5_pct']*100:.1f}%  "
              f"exact={summary['exact_pct']*100:.1f}%  "
              f"alg6={summary['alg6_pct']*100:.1f}%  "
              f"min={summary['min_pct']*100:.1f}%")

if __name__ == "__main__":
    main()
