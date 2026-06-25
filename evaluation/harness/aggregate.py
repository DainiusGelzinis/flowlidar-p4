#!/usr/bin/env python3
"""
aggregate.py — collapse per-chunk rows in summary.csv into per-group
mean+std rows.

Typical use: after the harness has run a (variant, pcap) sweep with K
chunks per pcap, you want ONE row per (variant, pcap) for the
datasets-on-x charts. Group by those two cols, compute mean+std of
every numeric metric.

Usage:
    aggregate.py SUMMARY_CSV [--group-by COL1,COL2,...] [--out OUT.csv]

Defaults:
    --group-by  variant,pcap
    --out       SUMMARY_CSV with "_aggregated.csv" suffix
                (e.g. summary.csv -> summary_aggregated.csv)

Output schema: one row per group. For each numeric column in the
input, two output columns: <col>_mean and <col>_std. Non-numeric meta
columns in --group-by are kept as-is. The number of chunks per group
is reported as `n_chunks`.

Example:
    # For section 6.3 (lazy vs traditional, pcaps on x):
    aggregate.py results/summary/summary.csv \\
        --group-by variant,pcap \\
        --out results/summary/by_variant_pcap.csv

    # For section 6.4.3 (stress, chunk size on x):
    aggregate.py results/summary/summary.csv \\
        --group-by variant,pcap,chunk \\
        --out results/summary/by_variant_pcap_chunk.csv
"""
import sys
import csv
import math
import argparse
from collections import defaultdict

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("summary")
    p.add_argument("--group-by", default="variant,pcap",
                   help="Comma-separated grouping columns (default: variant,pcap)")
    p.add_argument("--out", default=None,
                   help="Output CSV (default: <input>_aggregated.csv)")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args()

def is_numeric(s):
    if s == "" or s is None:
        return False
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False

def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0

def std(xs):
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))

def main():
    args = parse_args()

    group_cols = [c.strip() for c in args.group_by.split(",") if c.strip()]
    if not group_cols:
        print("[ERROR] --group-by needs at least one column", file=sys.stderr)
        sys.exit(1)

    out_path = args.out
    if out_path is None:
        base = args.summary
        if base.endswith(".csv"):
            out_path = base[:-4] + "_aggregated.csv"
        else:
            out_path = base + "_aggregated.csv"

    with open(args.summary) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    if not rows:
        print(f"[WARN] {args.summary} is empty -- nothing to aggregate")
        return

    for c in group_cols:
        if c not in fieldnames:
            print(f"[ERROR] group column not found in summary: {c}",
                  file=sys.stderr)
            print(f"        available: {fieldnames}", file=sys.stderr)
            sys.exit(1)

    numeric_cols = []
    for c in fieldnames:
        if c in group_cols:
            continue
        if any(is_numeric(r.get(c)) for r in rows):
            numeric_cols.append(c)

    groups = defaultdict(list)
    for r in rows:
        key = tuple(r[c] for c in group_cols)
        groups[key].append(r)

    out_cols = list(group_cols) + ["n_chunks"]
    for c in numeric_cols:
        out_cols.append(f"{c}_mean")
        out_cols.append(f"{c}_std")

    out_rows = []
    for key, rs in sorted(groups.items()):
        out = {group_cols[i]: key[i] for i in range(len(group_cols))}
        out["n_chunks"] = len(rs)
        for c in numeric_cols:
            xs = [float(r[c]) for r in rs if is_numeric(r.get(c))]
            out[f"{c}_mean"] = mean(xs)
            out[f"{c}_std"]  = std(xs)
        out_rows.append(out)

    with open(out_path, "w") as f:
        w = csv.DictWriter(f, fieldnames=out_cols)
        w.writeheader()
        w.writerows(out_rows)

    if not args.quiet:
        print(f"Aggregated {len(rows)} rows -> {len(out_rows)} groups")
        print(f"  group cols : {group_cols}")
        print(f"  numeric    : {len(numeric_cols)} columns (mean+std)")
        print(f"  output     : {out_path}")
        if len(out_rows) <= 20:
            print()
            preview_cols = group_cols + ["n_chunks"]
            for c in ("coverage", "ARE", "AAE", "pct_exact"):
                if f"{c}_mean" in out_cols:
                    preview_cols.append(f"{c}_mean")
            print("  preview:")
            print("    " + "  ".join(f"{c:>14}" for c in preview_cols))
            for r in out_rows:
                vals = []
                for c in preview_cols:
                    v = r[c]
                    if isinstance(v, float):
                        vals.append(f"{v:>14.4f}")
                    else:
                        vals.append(f"{str(v):>14}")
                print("    " + "  ".join(vals))

if __name__ == "__main__":
    main()
