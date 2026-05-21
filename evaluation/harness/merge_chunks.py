#!/usr/bin/env python3
"""
merge_chunks.py — merge per-chunk estimate CSVs into one whole-pcap CSV.

Sums per-5-tuple `digest_count` and `estimated_packets` across all input
chunks. Picks a representative `solver_path` (the most-common path the
flow was resolved with, or "mixed" if there's no majority).

Usage:
    merge_chunks.py CHUNK1.csv CHUNK2.csv ... [-o OUTPUT.csv]

Defaults: output goes to stdout if -o not given.

Input format (from CP --csv-out):
    src_ip,dst_ip,proto,src_port,dst_port,digest_count,estimated_packets,solver_path

Output format: same schema.
"""
import sys
import csv
import argparse
from collections import defaultdict, Counter


def main():
    p = argparse.ArgumentParser()
    p.add_argument("chunks", nargs="+", help="Per-chunk estimate CSVs")
    p.add_argument("-o", "--out", default="-",
                   help='Output CSV path (default "-" = stdout)')
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    digest    = defaultdict(int)
    estimated = defaultdict(int)
    paths     = defaultdict(Counter)

    total_rows = 0
    for path in args.chunks:
        with open(path) as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                continue
            for row in reader:
                if len(row) < 8:
                    continue
                key = tuple(row[0:5])
                digest[key]    += int(row[5])
                estimated[key] += int(row[6])
                paths[key][row[7]] += 1
                total_rows += 1

    fout = sys.stdout if args.out == "-" else open(args.out, "w")
    w = csv.writer(fout)
    w.writerow(["src_ip", "dst_ip", "proto", "src_port", "dst_port",
                "digest_count", "estimated_packets", "solver_path"])
    for key in sorted(digest.keys()):
        path_counter = paths[key]
        top, top_count = path_counter.most_common(1)[0]
        total = sum(path_counter.values())
        # Tag as "mixed" if there's no clear majority path
        rep_path = top if top_count > total / 2 else "mixed"
        w.writerow([*key, digest[key], estimated[key], rep_path])
    if args.out != "-":
        fout.close()

    if not args.quiet:
        print(f"[merge] {len(args.chunks)} chunks, {total_rows} rows -> "
              f"{len(digest)} distinct flows", file=sys.stderr)


if __name__ == "__main__":
    main()
