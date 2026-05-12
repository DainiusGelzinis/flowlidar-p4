#!/usr/bin/env python3
"""
make_synthetic_pcap.py — Build a synthetic test pcap with N unique 5-tuples,
each repeated K times. Use this to stress-test FlowLiDAR with a known truth
distribution while controlling flow structure.

Two flow-key styles:
  - random  : src/dst IPs and ports are uniformly random (good hash inputs)
              Isolates "BF capacity" effects from any structural-hash issue.
  - linear  : sequential src IPs (10.X.Y.Z incrementing), single dst, fixed
              ports. Mimics correlated-flow structure similar to CAIDA.

Usage:
    python3 make_synthetic_pcap.py N K [style] [output_path] [--seed S]

Examples:
    python3 make_synthetic_pcap.py 100 10                   # 100 flows × 10 pkts, random
    python3 make_synthetic_pcap.py 10000 5 random /tmp/test.pcap
    python3 make_synthetic_pcap.py 50000 5 linear           # CAIDA-like clusters
"""

import sys
import random
import argparse
from scapy.all import Ether, IP, UDP
from scapy.utils import PcapWriter


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('n_flows', type=int, help='Number of unique 5-tuples')
    p.add_argument('k_packets', type=int, help='Packets per flow')
    p.add_argument('style', nargs='?', choices=('random', 'linear'),
                   default='random', help='Flow key generation style')
    p.add_argument('output', nargs='?', default='synth.pcap')
    p.add_argument('--seed', type=int, default=42)
    return p.parse_args()


def random_ip():
    # Avoid 0.x and 224.x+ to keep packets uncontroversial.
    return f'{random.randint(1, 223)}.{random.randint(0, 255)}.' \
           f'{random.randint(0, 255)}.{random.randint(1, 254)}'


def gen_flows(n_flows, style):
    """Yield (src_ip, sport, dst_ip, dport) for n_flows distinct flows."""
    if style == 'random':
        seen = set()
        while len(seen) < n_flows:
            f = (random_ip(), random.randint(1024, 65535),
                 '10.0.0.1',     random.randint(1, 65535))
            if f not in seen:
                seen.add(f)
                yield f
    else:  # linear
        # Walk through 10.0.0.1 .. 10.A.B.C, fixed dst, fixed dport.
        # Forces sequential IP structure to test hash quality on correlated input.
        for i in range(n_flows):
            a = (i >> 16) & 0xff
            b = (i >>  8) & 0xff
            c = (i      ) & 0xff
            yield (f'10.{a}.{b}.{c+1 if c < 254 else 1}',
                   1024 + (i % 60000),
                   '10.0.0.1', 80)


def build_packet(src, sport, dst, dport):
    return (Ether(src='00:11:22:33:44:55', dst='00:aa:bb:cc:dd:ee') /
            IP(src=src, dst=dst, ttl=64) /
            UDP(sport=sport, dport=dport) /
            (b'\x00' * 16))


def main():
    args = parse_args()
    random.seed(args.seed)

    flows = list(gen_flows(args.n_flows, args.style))
    if len(flows) != args.n_flows:
        print(f'Warning: only generated {len(flows)} unique flows', file=sys.stderr)

    total = 0
    with PcapWriter(args.output, sync=True) as writer:
        for src, sport, dst, dport in flows:
            pkt = build_packet(src, sport, dst, dport)
            for _ in range(args.k_packets):
                writer.write(pkt.copy())
                total += 1

    print(f'Wrote {total} packets ({len(flows)} unique flows × {args.k_packets} pkts)')
    print(f'  style       : {args.style}')
    print(f'  seed        : {args.seed}')
    print(f'  output      : {args.output}')
    print()
    print(f'  Expected at line rate / fresh BF:')
    print(f'    Visible flows  ≈ {len(flows)} (×P_visible from BF FP rate)')
    print(f'    Total packets  = {total}')
    print(f'    Avg pkts/flow  = {args.k_packets:.1f} (truth)')


if __name__ == '__main__':
    main()
