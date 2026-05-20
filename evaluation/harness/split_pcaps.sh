#!/usr/bin/env bash
# split_pcaps.sh — pre-split CAIDA pcaps into N-million-packet chunks.
#
# Usage:
#   split_pcaps.sh CHUNK_SIZE_M [PCAP_DIR] [OUTPUT_DIR]
#
# Examples:
#   split_pcaps.sh 5             # 5M-packet chunks, defaults for dirs
#   split_pcaps.sh 1 /data /out  # 1M-pkt chunks, custom paths
#
# Produces, for each pcap, a sibling directory of chunk files:
#   OUTPUT_DIR/
#   ├── 125910_chunk5M/
#   │   ├── chunk_00000_<time>.pcap   (first 5M pkts)
#   │   ├── chunk_00001_<time>.pcap   (next 5M pkts)
#   │   └── ...
#   └── ...
#
# Idempotent: if an output dir already has chunk files, that pcap is
# skipped. Delete the dir manually to force re-split.
#
# Requires: editcap (from wireshark-common).

set -euo pipefail

if [[ "${1:-}" == "" ]]; then
    echo "usage: $0 CHUNK_SIZE_M [PCAP_DIR] [OUTPUT_DIR]"
    exit 1
fi

CHUNK_SIZE_M="$1"
PCAP_DIR="${2:-/opt/p4eval/data/equinix_2019}"
OUTPUT_DIR="${3:-$HOME/chunks}"

CHUNK_PKTS=$((CHUNK_SIZE_M * 1000000))

if ! command -v editcap >/dev/null 2>&1; then
    echo "[ERROR] editcap not found. Install: sudo apt-get install wireshark-common"
    exit 1
fi

if [[ ! -d "$PCAP_DIR" ]]; then
    echo "[ERROR] PCAP_DIR does not exist: $PCAP_DIR"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "============================================================"
echo "  split_pcaps.sh"
echo "  Chunk size : ${CHUNK_SIZE_M}M packets ($CHUNK_PKTS pkts)"
echo "  Source     : $PCAP_DIR"
echo "  Output     : $OUTPUT_DIR"
echo "============================================================"

total_in=0
total_chunks_made=0

for pcap in "$PCAP_DIR"/*.pcap; do
    [[ -e "$pcap" ]] || { echo "[ERROR] no .pcap files in $PCAP_DIR"; exit 1; }
    total_in=$((total_in + 1))

    base=$(basename "$pcap" .pcap)
    # equinix-nyc.dirA.20190117-130000.UTC.anon -> 130000
    short=$(echo "$base" \
        | sed -E 's/^equinix-nyc\.dir[A-Z]\.[0-9]+-//;
                  s/\.UTC\.anon$//;
                  s/[^0-9A-Za-z_]/_/g')
    out="$OUTPUT_DIR/${short}_chunk${CHUNK_SIZE_M}M"

    if [[ -d "$out" ]] && compgen -G "$out/chunk_*.pcap" > /dev/null; then
        n=$(ls "$out"/chunk_*.pcap 2>/dev/null | wc -l)
        echo "[skip] $short (already split: $n chunks in $out)"
        continue
    fi

    mkdir -p "$out"
    echo "[split] $base"
    echo "        -> $out"

    # editcap -c N input output  →  writes output_00000_*.pcap,
    # output_00001_*.pcap, ... each with N packets (last may be shorter).
    editcap -c "$CHUNK_PKTS" "$pcap" "$out/chunk.pcap" 2>/dev/null

    n=$(ls "$out"/chunk_*.pcap 2>/dev/null | wc -l)
    sz=$(du -sh "$out" | cut -f1)
    echo "        -> $n chunks ($sz)"
    total_chunks_made=$((total_chunks_made + n))
done

echo "============================================================"
echo "  Done. Processed $total_in pcaps."
echo "  Created $total_chunks_made new chunks under $OUTPUT_DIR"
echo "============================================================"
