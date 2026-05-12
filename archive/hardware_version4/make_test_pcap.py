#!/usr/bin/env python3
"""
make_test_pcap.py — Build a deterministic 27-packet test pcap matching the
6 flows / counts used by test_packet.py. Run on the local VM (or wherever
scapy is installed) and scp the resulting pcap to hotpot, then feed it to
test_flows.click.

Output: test_packets.pcap   (27 packets, 6 unique 5-tuples)

Per-flow packet counts:
    Flow A — TCP 10.1.0.1:1000 -> 10.0.0.1:80   × 12
    Flow B — TCP 10.1.0.2:2000 -> 10.0.0.1:80   ×  6
    Flow C — TCP 10.1.0.3:3000 -> 10.0.0.1:80   ×  3
    Flow D — TCP 10.1.0.4:4000 -> 10.0.0.1:443  ×  2
    Flow E — UDP 10.1.0.5:5000 -> 10.0.0.1:53   ×  2
    Flow F — UDP 10.1.0.6:6000 -> 10.0.0.1:53   ×  2

Usage:
    python3 make_test_pcap.py [output_path]
"""

import sys
from scapy.all import Ether, IP, TCP, UDP
from scapy.utils import PcapWriter

OUT = sys.argv[1] if len(sys.argv) > 1 else 'test_packets.pcap'

SRC_MAC = '00:11:22:33:44:55'
DST_MAC = '00:aa:bb:cc:dd:ee'

def build_tcp(src, sport, dst, dport):
    return (Ether(src=SRC_MAC, dst=DST_MAC) /
            IP(src=src, dst=dst, ttl=64) /
            TCP(sport=sport, dport=dport, flags='S'))

def build_udp(src, sport, dst, dport):
    # Note the parens around (b'\x00' * 4): without them, Python's left-to-right
    # precedence parses it as (packet / b'\x00') * 4, and scapy's Packet.__mul__
    # returns a 4-element PacketList — so each call would emit 4 UDP packets
    # instead of one.
    return (Ether(src=SRC_MAC, dst=DST_MAC) /
            IP(src=src, dst=dst, ttl=64) /
            UDP(sport=sport, dport=dport) /
            (b'\x00' * 4))

# Each entry: (label, builder-callable, count). The builder is called once
# per packet so every packet in the list is a distinct object — scapy's
# wrpcap doesn't tolerate repeated references to the same packet.
flows = [
    ('A', lambda: build_tcp('10.1.0.1', 1000, '10.0.0.1', 80),  12),
    ('B', lambda: build_tcp('10.1.0.2', 2000, '10.0.0.1', 80),   6),
    ('C', lambda: build_tcp('10.1.0.3', 3000, '10.0.0.1', 80),   3),
    ('D', lambda: build_tcp('10.1.0.4', 4000, '10.0.0.1', 443),  2),
    ('E', lambda: build_udp('10.1.0.5', 5000, '10.0.0.1', 53),   2),
    ('F', lambda: build_udp('10.1.0.6', 6000, '10.0.0.1', 53),   2),
]

total = 0
with PcapWriter(OUT, sync=True) as writer:
    for label, build, count in flows:
        for _ in range(count):
            writer.write(build())
            total += 1

print(f'Wrote {total} packets ({len(flows)} unique 5-tuples) to {OUT}')
for label, _, count in flows:
    print(f'  Flow {label}: {count} packets')
