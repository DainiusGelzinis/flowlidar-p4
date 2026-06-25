#!/usr/bin/env bash
# E8 multi-trace prep — Phase 1: cut load-sized chunks from CAIDA pcaps.

set -euo pipefail

SRC_DIR=/opt/p4eval/data/equinix_2019
DEST_BASE=/home2/dgelzini/chunks
LOADS=(1000000 2000000 4000000 8000000 16000000)

TRACES=("$@")
if [ ${#TRACES[@]} -eq 0 ]; then
    TRACES=(130100 130200)
fi

for ts in "${TRACES[@]}"; do
    SOURCE="${SRC_DIR}/equinix-nyc.dirA.20190117-${ts}.UTC.anon.pcap"
    DEST="${DEST_BASE}/${ts}_loads"

    echo "=========================================================="
    echo "Trace ${ts}"
    echo "  source: ${SOURCE}"
    echo "  dest:   ${DEST}"
    echo "=========================================================="

    if [ ! -r "$SOURCE" ]; then
        echo "  [ERROR] source pcap not readable, skipping" >&2
        continue
    fi
    ls -lh "$SOURCE"

    mkdir -p "$DEST"

    for n in "${LOADS[@]}"; do
        OUT="${DEST}/load_${n}_legacy.pcap"
        if [ -e "$OUT" ]; then
            count=$(capinfos -c "$OUT" 2>/dev/null | awk -F: '/Number of packets/ {print $2}' | tr -d ' ,k')
            echo "  ${n} packets: already cut ($(ls -lh "$OUT" | awk '{print $5}')), skipping"
            continue
        fi
        echo "  cutting ${n} packets ..."
        editcap -F pcap -c "$n" "$SOURCE" "${DEST}/load_${n}_split.pcap"
        mv "${DEST}"/load_${n}_split_00000_*.pcap "$OUT"
        rm -f "${DEST}"/load_${n}_split_*.pcap
        capinfos -c "$OUT" | grep "Number of packets"
    done

    echo
    echo "Files in ${DEST}:"
    ls -lh "$DEST"
    echo
done

echo "=========================================================="
echo "Phase 1 done. Next: phase 2 — generate truth CSVs via tshark."
echo "  cd /home2/dgelzini/chunks/<ts>_loads/"
echo "  for n in 1000000 2000000 4000000 8000000 16000000; do"
echo "      ~/truth_csv.sh load_\${n}_legacy.pcap load_\${n}_truth.csv"
echo "  done"
echo "=========================================================="
