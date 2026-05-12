#!/usr/bin/env python3
"""
FlowLiDAR Prototype 3 — Test Script

Verifies both the Bloom Filter (new-flow detection) and the Count-Min Sketch
(per-flow packet counting) by sending packets with known counts.

Run control_plane.py in a separate terminal first, then run this script.
After the epoch timer fires in control_plane.py, check that:
  - The CMS estimate for Flow A is ~11
  - The CMS estimate for Flow B is ~5
  - The CMS estimate for Flow C is ~2
  - All single-packet flows show ~1

Usage:
    sudo python3 test_packet.py

With very few flows and 1K entries per CMS row, hash collisions are nearly
impossible (~0.5% chance per row), so estimates should be exact.
"""

import time
from scapy.all import Ether, IP, TCP, UDP, sendp

SEND_IFACE = 'veth1'   # packets enter the switch on port 0 via veth1
DELAY      = 0.05      # seconds between individual packets

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
print('  FlowLiDAR Prototype 3 — BF + CMS Test')
print('  Make sure control_plane.py is running in another terminal.')
print('=' * 64)
print()

# ── Test 1: Register 6 new flows (1 packet each) ─────────────────────────────
print('[Test 1] Send 1 packet per flow (6 flows) → expect 6 BF digests')
print('         CMS counter at each flow position incremented to 1')
send('Flow A: 10.1.0.1:1000 -> 10.0.0.1:80  TCP', PKT_A)
send('Flow B: 10.1.0.2:2000 -> 10.0.0.1:80  TCP', PKT_B)
send('Flow C: 10.1.0.3:3000 -> 10.0.0.1:80  TCP', PKT_C)
send('Flow D: 10.1.0.4:4000 -> 10.0.0.1:443 TCP', PKT_D)
send('Flow E: 10.1.0.5:5000 -> 10.0.0.1:53  UDP', PKT_E)
send('Flow F: 10.1.0.6:6000 -> 10.0.0.1:53  UDP', PKT_F)
time.sleep(0.5)

# ── Test 2: Grow Flow A to 11 total packets ───────────────────────────────────
print()
print('[Test 2] Send 10 more packets for Flow A → expect 0 new digests')
print('         CMS(Flow A) should reach 11')
send('Flow A repeat x10', PKT_A, count=10, quiet=True)
print('  Sent 10x [Flow A repeat x10]')
time.sleep(0.5)

# ── Test 3: Grow Flow B to 5 total packets ────────────────────────────────────
print()
print('[Test 3] Send 4 more packets for Flow B → expect 0 new digests')
print('         CMS(Flow B) should reach 5')
send('Flow B repeat x4', PKT_B, count=4, quiet=True)
print('  Sent 4x [Flow B repeat x4]')
time.sleep(0.5)

# ── Test 4: Grow Flow C to 2 total packets ────────────────────────────────────
print()
print('[Test 4] Send 1 more packet for Flow C → expect 0 new digests')
print('         CMS(Flow C) should reach 2')
send('Flow C repeat x1', PKT_C)
time.sleep(0.5)

# ── Test 5: Re-send all flows to confirm BF suppression ──────────────────────
print()
print('[Test 5] Re-send all 6 flows once each → expect 0 new digests')
print('         (BF bits already set — all known flows suppressed)')
for label, pkt in [('Flow A', PKT_A), ('Flow B', PKT_B), ('Flow C', PKT_C),
                    ('Flow D', PKT_D), ('Flow E', PKT_E), ('Flow F', PKT_F)]:
    send(f'{label} re-send', pkt, quiet=True)
print('  Sent 1x [each of 6 flows]')
time.sleep(0.5)

print()
print('=' * 64)
print('  Done sending.')
print()
print('  Summary of expected counts in control_plane.py at next epoch:')
print('    Flow A (10.1.0.1:1000 -> 10.0.0.1:80  TCP)  →  CMS est. = 12')
print('    Flow B (10.1.0.2:2000 -> 10.0.0.1:80  TCP)  →  CMS est. =  6')
print('    Flow C (10.1.0.3:3000 -> 10.0.0.1:80  TCP)  →  CMS est. =  3')
print('    Flow D (10.1.0.4:4000 -> 10.0.0.1:443 TCP)  →  CMS est. =  2')
print('    Flow E (10.1.0.5:5000 -> 10.0.0.1:53  UDP)  →  CMS est. =  2')
print('    Flow F (10.1.0.6:6000 -> 10.0.0.1:53  UDP)  →  CMS est. =  2')
print()
print('  (Each flow gets +1 from Test 5. Estimates may be higher if collisions')
print('   occur, but with 6 flows and 1K counters per row, that is unlikely.)')
print()
print('  Wait for the epoch timer in control_plane.py, or press Ctrl-C there')
print('  to trigger an immediate epoch report.')
print('=' * 64)
