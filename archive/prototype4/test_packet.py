#!/usr/bin/env python3
"""
FlowLiDAR Prototype 4 — Test Script (Lazy BF)

Verifies the Lazy Updates BF (Algorithm 2) + conditional CMS.

Key differences from prototype3 test expectations:
  - Each new flow generates up to k=3 digests (one per initial packet)
  - Flows with <= k=3 total packets have CMS count = 0
  - Total estimate = digest_count + min(cms_rows)

Expected digest count: 15 (not 6 as in prototype3)
Expected epoch report:
  Flow A: digests=3, CMS=9,  total=12
  Flow B: digests=3, CMS=3,  total=6
  Flow C: digests=3, CMS=0,  total=3
  Flow D: digests=2, CMS=0,  total=2
  Flow E: digests=2, CMS=0,  total=2
  Flow F: digests=2, CMS=0,  total=2

Usage:
    sudo python3 test_packet.py
"""

import time
from scapy.all import Ether, IP, TCP, UDP, sendp

SEND_IFACE = 'veth1'
DELAY      = 0.05      # 50ms between packets (fast, for CMS-only packets)
DIGEST_GAP = 1.5       # 1.5s between digest-generating packets (dedup window)

def send(desc, pkt, count=1, quiet=False):
    if not quiet:
        print(f'  Sending {count}x [{desc}]')
    for _ in range(count):
        sendp(pkt, iface=SEND_IFACE, verbose=False)
        time.sleep(DELAY)

# Pre-build packets
PKT_A = Ether()/IP(src='10.1.0.1', dst='10.0.0.1', ttl=64)/TCP(sport=1000, dport=80)
PKT_B = Ether()/IP(src='10.1.0.2', dst='10.0.0.1', ttl=64)/TCP(sport=2000, dport=80)
PKT_C = Ether()/IP(src='10.1.0.3', dst='10.0.0.1', ttl=64)/TCP(sport=3000, dport=80)
PKT_D = Ether()/IP(src='10.1.0.4', dst='10.0.0.1', ttl=64)/TCP(sport=4000, dport=443)
PKT_E = Ether()/IP(src='10.1.0.5', dst='10.0.0.1', ttl=64)/UDP(sport=5000, dport=53)
PKT_F = Ether()/IP(src='10.1.0.6', dst='10.0.0.1', ttl=64)/UDP(sport=6000, dport=53)

print('=' * 64)
print('  FlowLiDAR Prototype 4 — Lazy BF + CMS Test')
print('  Make sure control_plane.py is running in another terminal.')
print('=' * 64)
print()

# -- Test 1: First packet for each flow (6 digests, one per flow) --
print('[Test 1] Send 1 packet per flow (6 flows)')
print('         Lazy BF: each sets only bf_0 bit -> 6 digests (digest #1 each)')
send('Flow A: 10.1.0.1:1000 -> 10.0.0.1:80  TCP', PKT_A)
send('Flow B: 10.1.0.2:2000 -> 10.0.0.1:80  TCP', PKT_B)
send('Flow C: 10.1.0.3:3000 -> 10.0.0.1:80  TCP', PKT_C)
send('Flow D: 10.1.0.4:4000 -> 10.0.0.1:443 TCP', PKT_D)
send('Flow E: 10.1.0.5:5000 -> 10.0.0.1:53  UDP', PKT_E)
send('Flow F: 10.1.0.6:6000 -> 10.0.0.1:53  UDP', PKT_F)
time.sleep(DIGEST_GAP)

# -- Test 2: Packet 2 for A and B (digests #2) --
# Tofino's digest dedup requires spacing between same-flow digests.
print()
print('[Test 2] Send pkt 2 for A and B -> digests #2 (sets bf_1)')
send('Flow A pkt 2', PKT_A)
send('Flow B pkt 2', PKT_B)
time.sleep(DIGEST_GAP)

# -- Test 3: Packet 3 for A and B (digests #3 — all BF bits now set) --
print()
print('[Test 3] Send pkt 3 for A and B -> digests #3 (sets bf_2)')
send('Flow A pkt 3', PKT_A)
send('Flow B pkt 3', PKT_B)
time.sleep(DIGEST_GAP)

# -- Test 4: Remaining packets for A (pkts 4-11) and B (pkts 4-5) via CMS --
# All 3 BF bits are now set for A and B -> CMS only, no digests.
print()
print('[Test 4] Send 8 more for A, 2 more for B -> CMS only (no digests)')
send('Flow A x8 (CMS)', PKT_A, count=8, quiet=True)
print('  Sent 8x [Flow A] -> CMS = 8')
send('Flow B x2 (CMS)', PKT_B, count=2, quiet=True)
print('  Sent 2x [Flow B] -> CMS = 2')
time.sleep(0.5)

# -- Test 5: Pkt 2 for Flow C (digest #2, sets bf_1) --
print()
print('[Test 5] Send pkt 2 for Flow C -> digest #2 (sets bf_1)')
send('Flow C pkt 2', PKT_C)
time.sleep(DIGEST_GAP)

# -- Test 6: Re-send all flows once each --
# A: all bits set -> CMS+1 (total CMS=9)
# B: all bits set -> CMS+1 (total CMS=3)
# C: bf_0=1, bf_1=1, bf_2=0 -> set bf_2, digest #3
# D: bf_0=1, bf_1=0 -> set bf_1, digest #2
# E: bf_0=1, bf_1=0 -> set bf_1, digest #2
# F: bf_0=1, bf_1=0 -> set bf_1, digest #2
print()
print('[Test 6] Re-send all 6 flows once each')
print('         A,B: CMS+1. C: digest #3. D,E,F: digest #2.')
for label, pkt in [('Flow A', PKT_A), ('Flow B', PKT_B), ('Flow C', PKT_C),
                    ('Flow D', PKT_D), ('Flow E', PKT_E), ('Flow F', PKT_F)]:
    send(f'{label} re-send', pkt, quiet=True)
print('  Sent 1x [each of 6 flows]')
time.sleep(0.5)

print()
print('=' * 64)
print('  Done sending.')
print()
print('  Expected totals (digest + CMS = total):')
print('    Flow A: 3 + 9 = 12')
print('    Flow B: 3 + 3 =  6')
print('    Flow C: 3 + 0 =  3')
print('    Flow D: 2 + 0 =  2')
print('    Flow E: 2 + 0 =  2')
print('    Flow F: 2 + 0 =  2')
print()
print('  Total digests expected: 15')
print('  CMS non-zero flows: only A (9) and B (3)')
print()
print('  Wait for the epoch timer, or press Ctrl-C in control_plane.py.')
print('=' * 64)
