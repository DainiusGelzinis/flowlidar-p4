#!/usr/bin/env bash
# E8 multi-trace prep — Phase 2: generate per-flow truth CSVs via tshark.

set -euo pipefail

CHUNKS_BASE=/home2/dgelzini/chunks
TRUTH_SCRIPT=~/truth_csv.sh
LOADS=(1000000 2000000 4000000 8000000 16000000)

TRACES=("$@")
if [ ${#TRACES[@]} -eq 0 ]; then
    TRACES=(130100 130200)
fi

if [ ! -x "$TRUTH_SCRIPT" ]; then
    echo "[ERROR] truth_csv.sh not found at $TRUTH_SCRIPT" >&2
    echo "        scp it from the VM first:" >&2
    echo "        scp evaluation/harness/truth_csv.sh dgelzini@hotpot:~/" >&2
    exit 1
fi

for ts in "${TRACES[@]}"; do
    DEST="${CHUNKS_BASE}/${ts}_loads"

    echo "=========================================================="
    echo "Trace ${ts} — truth CSVs in ${DEST}"
    echo "=========================================================="

    if [ ! -d "$DEST" ]; then
        echo "  [ERROR] ${DEST} does not exist (run phase1 first), skipping" >&2
        continue
    fi

    cd "$DEST"

    for n in "${LOADS[@]}"; do
        OUT="load_${n}_truth.csv"
        PCAP="load_${n}_legacy.pcap"
        if [ -e "$OUT" ]; then
            flows=$(tail -n +2 "$OUT" | wc -l)
            echo "  ${n}: already done (${flows} flows), skipping"
            continue
        fi
        if [ ! -e "$PCAP" ]; then
            echo "  [WARN] ${PCAP} missing, skipping" >&2
            continue
        fi
        echo "  ${n}: tshark on ${PCAP} (start $(date +%H:%M:%S)) ..."
        "$TRUTH_SCRIPT" "$PCAP" "$OUT"
        echo "         done $(date +%H:%M:%S)"
    done

    echo
    echo "Files in ${DEST}:"
    ls -lh load_*_truth.csv 2>/dev/null
    echo
done

echo "=========================================================="
echo "Phase 2 done. Next: phase 3 — switch runs."
echo "  Same runbook as the 130000 sweep, but point the CP at the new pcap:"
echo "  PCAP=/home2/dgelzini/chunks/<ts>_loads/load_\${LOAD}_legacy.pcap"
echo "=========================================================="
