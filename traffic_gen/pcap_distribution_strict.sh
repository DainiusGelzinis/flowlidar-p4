#!/usr/bin/env bash
# pcap_distribution_strict.sh — IPv4-only ground truth that matches the P4's
# flow definition exactly. Differs from pcap_distribution.sh in:
#   - filters to only IPv4 packets at tshark level (skips IPv6, ARP, MPLS, etc.)
#   - reports how many packets were filtered out
#   - the 5-tuple key is {src, dst, proto, sport, dport} where sport/dport are
#     literally the TCP or UDP ports if present, otherwise 0 — same as our P4
#
# This is the right truth for FlowLiDAR coverage comparisons.
#
# Usage:
#   ./pcap_distribution_strict.sh                       # whole default pcap
#   ./pcap_distribution_strict.sh 2300000               # first 2.3M packets
#   ./pcap_distribution_strict.sh 2300000 /path.pcap    # first N of custom pcap
#   ./pcap_distribution_strict.sh /path.pcap            # whole custom pcap

set -euo pipefail

DEFAULT_PCAP="/opt/p4eval/data/equinix_2019/equinix-nyc.dirA.20190117-130000.UTC.anon.pcap"

LIMIT=""
PCAP="$DEFAULT_PCAP"

if [[ -n "${1:-}" ]]; then
    if [[ "$1" =~ ^[0-9]+$ ]]; then
        LIMIT="$1"
        PCAP="${2:-$DEFAULT_PCAP}"
    else
        PCAP="$1"
    fi
fi

if [[ ! -r "$PCAP" ]]; then
    echo "[ERROR] cannot read pcap: $PCAP"
    exit 1
fi

if ! command -v tshark >/dev/null 2>&1; then
    echo "[ERROR] tshark not found in PATH"
    exit 1
fi

echo "============================================================"
if [[ -n "$LIMIT" ]]; then
    echo "  First $LIMIT packets (IPv4-only filter, P4-equivalent flow key) of:"
else
    echo "  Full pcap (IPv4-only filter, P4-equivalent flow key):"
fi
echo "    $(basename "$PCAP")"
echo "============================================================"

# Step 1 — Get raw packet count for "filtered out" comparison.
# This counts ALL packets in the window we sample.
TSHARK_TOTAL_ARGS=( -r "$PCAP" -T fields -e frame.number )
[[ -n "$LIMIT" ]] && TSHARK_TOTAL_ARGS+=( -c "$LIMIT" )

TOTAL_PKTS=$(tshark "${TSHARK_TOTAL_ARGS[@]}" 2>/dev/null | wc -l)
echo "  Raw packets in window      : $TOTAL_PKTS"

# Step 2 — IPv4-only count and distribution. We use -Y "ip" so tshark
# discards everything that isn't an IPv4 packet from the same window.
# Note: -c happens BEFORE -Y, so we still sample exactly N raw packets and
# only some of them survive the filter — same as what the switch would see.
TSHARK_IPV4_ARGS=( -r "$PCAP" -Y "ip"
                   -T fields
                   -e ip.src -e ip.dst -e ip.proto
                   -e tcp.srcport -e tcp.dstport
                   -e udp.srcport -e udp.dstport )
[[ -n "$LIMIT" ]] && TSHARK_IPV4_ARGS+=( -c "$LIMIT" )

tshark "${TSHARK_IPV4_ARGS[@]}" 2>/dev/null \
  | awk -F'\t' -v total="$TOTAL_PKTS" '
        # Skip rows that somehow have empty src/dst (defensive — should not
        # happen with -Y "ip" but guards against malformed packets).
        $1 == "" || $2 == "" { skipped++; next }
        {
            # Mirror the P4 5-tuple exactly:
            #   src | dst | proto | (tcp.sport OR udp.sport OR 0) | (... dport ...)
            sport = ($4 != "" ? $4 : ($6 != "" ? $6 : "0"))
            dport = ($5 != "" ? $5 : ($7 != "" ? $7 : "0"))
            key = $1 "|" $2 "|" $3 "|" sport "|" dport
            f[key]++
            ipv4_pkts++
        }
        END {
            for (k in f) {
                n_flows++
                if      (f[k] == 1) one++
                else if (f[k] == 2) two++
                else if (f[k] == 3) three++
                else if (f[k] <= 10) four_to_ten++
                else if (f[k] <= 100) eleven_to_hundred++
                else                  hundred_plus++
            }
            printf "  IPv4 packets (P4-visible)  : %d (%.1f%% of raw)\n", ipv4_pkts, ipv4_pkts*100/total
            printf "  Non-IPv4 (silently passed) : %d\n", total - ipv4_pkts
            printf "  Defensive skipped rows     : %d\n", skipped+0
            printf "\n"
            printf "  Flows (P4-equivalent)      : %d\n", n_flows
            printf "  Avg packets/flow           : %.2f\n", ipv4_pkts / n_flows
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
