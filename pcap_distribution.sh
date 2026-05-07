#!/usr/bin/env bash
# pcap_distribution.sh — Compute true flow-size distribution for the first N
# packets of a CAIDA pcap. Used to compare against FlowLiDAR ground truth.
#
# Usage:
#   ./pcap_distribution.sh                    # uses default pcap, both Run A (3M) and Run C (1.2M)
#   ./pcap_distribution.sh 1200000            # only that packet count
#   ./pcap_distribution.sh 3000000 /path/to/other.pcap

set -euo pipefail

DEFAULT_PCAP="/opt/p4eval/data/equinix_2019/equinix-nyc.dirA.20190117-130000.UTC.anon.pcap"
PCAP="${2:-$DEFAULT_PCAP}"

if [[ ! -r "$PCAP" ]]; then
    echo "[ERROR] cannot read pcap: $PCAP"
    exit 1
fi

if ! command -v tshark >/dev/null 2>&1; then
    echo "[ERROR] tshark not found in PATH"
    exit 1
fi

run_one() {
    local N="$1"
    echo "============================================================"
    echo "  First $N packets of:"
    echo "    $(basename "$PCAP")"
    echo "============================================================"

    tshark -r "$PCAP" \
           -T fields \
           -e ip.src -e ip.dst -e ip.proto \
           -e tcp.srcport -e tcp.dstport \
           -e udp.srcport -e udp.dstport \
           -c "$N" \
           2>/dev/null \
      | awk -F'\t' '
            {
                # 5-tuple key. TCP and UDP ports are in different columns; concat
                # the relevant pair into one field for the key.
                key = $1 "|" $2 "|" $3 "|" $4 $6 "|" $5 $7
                f[key]++
            }
            END {
                for (k in f) {
                    n_flows++
                    total_pkts += f[k]
                    if      (f[k] == 1) one++
                    else if (f[k] == 2) two++
                    else if (f[k] == 3) three++
                    else if (f[k] <= 10) four_to_ten++
                    else if (f[k] <= 100) eleven_to_hundred++
                    else                  hundred_plus++
                }
                printf "  Flows                : %d\n", n_flows
                printf "  Packets              : %d\n", total_pkts
                printf "  Avg packets/flow     : %.2f\n", total_pkts / n_flows
                printf "\n  Distribution:\n"
                printf "    1-pkt              : %d (%.1f%%)\n",  one,                  one*100/n_flows
                printf "    2-pkt              : %d (%.1f%%)\n",  two,                  two*100/n_flows
                printf "    3-pkt              : %d (%.1f%%)\n",  three,                three*100/n_flows
                printf "    4-10 pkt           : %d (%.1f%%)\n",  four_to_ten,          four_to_ten*100/n_flows
                printf "    11-100 pkt         : %d (%.1f%%)\n",  eleven_to_hundred,    eleven_to_hundred*100/n_flows
                printf "    101+ pkt           : %d (%.1f%%)\n",  hundred_plus,         hundred_plus*100/n_flows
                printf "\n  FlowLiDAR equivalents (without false positives):\n"
                printf "    Alg4 candidates    : %.1f%%   (1-pkt + 2-pkt)\n",     (one+two)*100/n_flows
                printf "    Alg5 candidates    : %.1f%%   (3-pkt)\n",             three*100/n_flows
                printf "    Solver candidates  : %.1f%%   (4+ pkt)\n",            (four_to_ten+eleven_to_hundred+hundred_plus)*100/n_flows
            }
        '
    echo ""
}

if [[ -n "${1:-}" ]]; then
    run_one "$1"
else
    # Default: run both — Run C (10s epoch, 8.5s effective) and Run A (15s epoch, 13.5s effective)
    run_one 1200000
    run_one 3000000
fi
