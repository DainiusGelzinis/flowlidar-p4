#!/usr/bin/env bash
# truth_csv.sh — emit per-flow ground truth CSV from a pcap chunk.
#
# Usage:
#   truth_csv.sh PCAP OUT.csv
#
# Format of OUT.csv:
#   src_ip,dst_ip,proto,src_port,dst_port,true_pkts
#
# Matches the P4 5-tuple exactly: only IPv4 packets, TCP/UDP ports or 0.
# Designed to be joined with the CP's --csv-out file on the (5-tuple)
# key so per-flow AAE / ARE / %exact can be computed.
#
# Idempotent: skips work if OUT.csv already exists.
#
# Requires: tshark (wireshark-common).

set -euo pipefail

if [[ "${1:-}" == "" || "${2:-}" == "" ]]; then
    echo "usage: $0 PCAP OUT.csv"
    exit 1
fi

PCAP="$1"
OUT="$2"

if [[ ! -r "$PCAP" ]]; then
    echo "[ERROR] cannot read pcap: $PCAP"; exit 1
fi

if [[ -s "$OUT" ]]; then
    n=$(($(wc -l <"$OUT") - 1))
    echo "[skip] $OUT already exists ($n flows)"
    exit 0
fi

if ! command -v tshark >/dev/null 2>&1; then
    echo "[ERROR] tshark not found; install wireshark-common"; exit 1
fi

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

# Pull the 5-tuple fields for every IPv4 packet, aggregate in awk.
tshark -r "$PCAP" -Y "ip" \
       -T fields \
       -e ip.src -e ip.dst -e ip.proto \
       -e tcp.srcport -e tcp.dstport \
       -e udp.srcport -e udp.dstport 2>/dev/null \
| awk -F'\t' '
    $1 == "" || $2 == "" { next }
    {
        sport = ($4 != "" ? $4 : ($6 != "" ? $6 : "0"))
        dport = ($5 != "" ? $5 : ($7 != "" ? $7 : "0"))
        key = $1 "," $2 "," $3 "," sport "," dport
        count[key]++
    }
    END {
        for (k in count) print k "," count[k]
    }
' > "$tmp"

n=$(wc -l <"$tmp")

# Sort for stable output (helps git diffs of truth files in regression tests).
{ echo "src_ip,dst_ip,proto,src_port,dst_port,true_pkts"
  sort "$tmp"
} > "$OUT"

echo "[wrote] $OUT ($n flows)"
